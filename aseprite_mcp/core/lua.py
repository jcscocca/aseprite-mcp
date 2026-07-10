"""Pure Lua codegen: validated ops in, Aseprite batch scripts out.

Every script fails loudly via error() (nonzero exit code, message on stdout)
and reports structured results on a single line prefixed with RESULT_MARKER.

API names here are verified against the Aseprite Lua bindings
(src/app/script/*.cpp) — see docs/superpowers/plans/ for the reference notes.
"""

from __future__ import annotations

from pathlib import Path

from .ops import RGBA, Pixel, ShapeOp

RESULT_MARKER = "AMCP_RESULT"

_JESC = r"""
local function jesc(s)
  s = s:gsub("\\", "\\\\"):gsub('"', '\\"'):gsub("\n", "\\n"):gsub("\r", "\\r"):gsub("\t", "\\t")
  return s
end
"""


# Converting Color{r,g,b} to a pixel/tool color in INDEXED mode goes through the
# *app's* current palette, which in batch mode is not the sprite's palette — so
# the palette index is computed here from the sprite's own palette instead.
# Inexact matches are recorded in AMCP_SNAPPED for the snap report.
_AMCP_COLOR = r"""
local AMCP_SNAPPED = {}
local function amcp_color(r, g, b, a)
  if spr.colorMode == ColorMode.INDEXED then
    if a == 0 then return Color{ index = spr.transparentColor } end
    local pal = spr.palettes[1]
    local best, bestd = 0, math.huge
    for i = 0, #pal - 1 do
      local pc = pal:getColor(i)
      local dr, dg, db = pc.red - r, pc.green - g, pc.blue - b
      local d = dr * dr + dg * dg + db * db
      if d < bestd then best, bestd = i, d end
    end
    if bestd > 0 then
      local pc = pal:getColor(best)
      AMCP_SNAPPED[string.format("#%02x%02x%02x", r, g, b)] =
        string.format("#%02x%02x%02x", pc.red, pc.green, pc.blue)
    end
    return Color{ index = best }
  end
  return Color{ r = r, g = g, b = b, a = a }
end
"""

_SNAP_REPORT = (
    "local snaps = {}\n"
    "for req, got in pairs(AMCP_SNAPPED) do\n"
    "  snaps[#snaps + 1] = string.format('\"%s\": \"%s\"', req, got)\n"
    "end\n"
    "table.sort(snaps)\n"
    f'print("{RESULT_MARKER} " .. \'{{"snapped": {{\' .. table.concat(snaps, ", ") .. \'}}}}\')\n'
)


def lua_quote(s: str) -> str:
    escaped = (
        s.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def color_literal(c: RGBA) -> str:
    return f"Color{{ r={c.r}, g={c.g}, b={c.b}, a={c.a} }}"


def color_call(c: RGBA) -> str:
    """Mode-aware color expression; requires _AMCP_COLOR emitted after the sprite is open."""
    return f"amcp_color({c.r}, {c.g}, {c.b}, {c.a})"


def _open_sprite(path: Path) -> str:
    q = lua_quote(str(path))
    return f"local spr = app.open({q})\nif not spr then error(\"could not open sprite: \" .. {q}) end\n"


def _save_sprite(path: Path) -> str:
    q = lua_quote(str(path))
    return f"if not spr:saveAs({q}) then error(\"failed to save sprite: \" .. {q}) end\n"


def _check_frame(frame: int) -> str:
    return (
        f"if {frame} > #spr.frames then\n"
        f'  error("frame {frame} out of range: sprite has " .. #spr.frames .. " frame(s)")\n'
        "end\n"
    )


def _resolve_layer(layer: str | None) -> str:
    """Bind `layer`, failing with the list of available layer names."""
    if layer is None:
        lookup = "local layer = spr.layers[1]\n"
    else:
        q = lua_quote(layer)
        lookup = (
            f"local layer = spr.layers[{q}]\n"
            "if not layer then\n"
            "  local names = {}\n"
            "  for i = 1, #spr.layers do names[#names + 1] = spr.layers[i].name end\n"
            f'  error("layer not found: " .. {q} .. " (available: " .. table.concat(names, ", ") .. ")")\n'
            "end\n"
        )
    return lookup + (
        'if layer.isGroup then error("layer \'" .. layer.name .. "\' is a group; target an image layer") end\n'
    )


def _ensure_full_canvas_cel(frame: int) -> str:
    """Guarantee `cel` spans the whole canvas.

    Cel images are cropped to the cel bounds; putPixel outside them silently
    no-ops, so an existing cropped cel is redrawn onto a full-size image first.
    """
    return (
        f"local cel = layer:cel({frame})\n"
        "if cel == nil then\n"
        f"  cel = spr:newCel(layer, {frame})\n"
        "else\n"
        "  local full = Image(spr.width, spr.height, spr.colorMode)\n"
        "  full:drawImage(cel.image, cel.position)\n"
        f"  cel = spr:newCel(layer, {frame}, full, Point(0, 0))\n"
        "end\n"
    )


def script_create_canvas(
    path: Path, width: int, height: int, color_mode_lua: str, palette: list[RGBA] | None
) -> str:
    parts = [f"local spr = Sprite({width}, {height}, {color_mode_lua})\n"]
    if palette is not None:
        parts.append(_palette_snippet(palette))
    parts.append(_save_sprite(path))
    parts.append(_JESC)
    parts.append(
        f'print("{RESULT_MARKER} " .. string.format(\'{{"layer": "%s"}}\', jesc(spr.layers[1].name)))\n'
    )
    return "".join(parts)


def _palette_snippet(palette: list[RGBA]) -> str:
    colors = ", ".join(color_literal(c) for c in palette)
    return (
        f"local colors = {{ {colors} }}\n"
        "local pal = Palette(#colors)\n"
        "for i, c in ipairs(colors) do pal:setColor(i - 1, c) end\n"
        "spr:setPalette(pal)\n"
    )


def script_get_canvas_info(path: Path) -> str:
    return (
        _open_sprite(path)
        + _JESC
        + r"""
local cm = "unknown"
if spr.colorMode == ColorMode.RGB then cm = "rgb"
elseif spr.colorMode == ColorMode.INDEXED then cm = "indexed"
elseif spr.colorMode == ColorMode.GRAYSCALE then cm = "grayscale"
end
local layers = {}
for i = 1, #spr.layers do
  local l = spr.layers[i]
  layers[#layers + 1] = string.format(
    '{"name": "%s", "visible": %s, "is_group": %s}',
    jesc(l.name), tostring(l.isVisible), tostring(l.isGroup))
end
local frames = {}
for i = 1, #spr.frames do
  frames[#frames + 1] = string.format(
    '{"number": %d, "duration_ms": %d}',
    i, math.floor(spr.frames[i].duration * 1000 + 0.5))
end
local pal = spr.palettes[1]
local pcolors = {}
for i = 0, #pal - 1 do
  local c = pal:getColor(i)
  pcolors[#pcolors + 1] = string.format('"#%02x%02x%02x"', c.red, c.green, c.blue)
end
-- aniDir ints in the same order the spritesheet JSON export uses
local anidirs = { [0] = "forward", [1] = "reverse", [2] = "pingpong", [3] = "pingpong_reverse" }
local tags = {}
for i = 1, #spr.tags do
  local t = spr.tags[i]
  tags[#tags + 1] = string.format(
    '{"name": "%s", "from_frame": %d, "to_frame": %d, "direction": "%s"}',
    jesc(t.name), t.fromFrame.frameNumber, t.toFrame.frameNumber, anidirs[t.aniDir] or "forward")
end
"""
        + f'print("{RESULT_MARKER} " .. string.format(\n'
        + "  '{\"width\": %d, \"height\": %d, \"color_mode\": \"%s\", \"layers\": [%s], \"frames\": [%s], \"palette\": [%s], \"tags\": [%s]}',\n"
        + "  spr.width, spr.height, cm,\n"
        + '  table.concat(layers, ", "), table.concat(frames, ", "), table.concat(pcolors, ", "), table.concat(tags, ", ")))\n'
    )


def script_set_palette(path: Path, colors: list[RGBA]) -> str:
    n = len(colors)
    # Indexed pixels keep their index when the palette is replaced; any index
    # beyond the new palette would silently render blank, so scan every cel first.
    guard = (
        "if spr.colorMode == ColorMode.INDEXED then\n"
        "  for _, cel in ipairs(spr.cels) do\n"
        "    for it in cel.image:pixels() do\n"
        "      local idx = it()\n"
        f"      if idx >= {n} then\n"
        f'        error(string.format("cannot shrink palette to {n} color(s): '
        "pixel (%d,%d) on layer '%s' frame %d uses palette index %d — repaint "
        'those pixels first or pass at least %d colors",\n'
        "          it.x + cel.position.x, it.y + cel.position.y, cel.layer.name,"
        " cel.frameNumber, idx, idx + 1))\n"
        "      end\n"
        "    end\n"
        "  end\n"
        "end\n"
    )
    return _open_sprite(path) + guard + _palette_snippet(colors) + _save_sprite(path)


def script_draw_pixels(path: Path, pixels: list[Pixel], layer: str | None, frame: int) -> str:
    color_index: dict[RGBA, int] = {}
    for px in pixels:
        color_index.setdefault(px.color, len(color_index) + 1)
    color_table = ", ".join(
        color_call(c) for c, _ in sorted(color_index.items(), key=lambda kv: kv[1])
    )
    puts = "".join(
        f"put({px.x}, {px.y}, C[{color_index[px.color]}])\n" for px in pixels
    )
    return (
        _open_sprite(path)
        + _AMCP_COLOR
        + _check_frame(frame)
        + _resolve_layer(layer)
        + _ensure_full_canvas_cel(frame)
        + "local img = cel.image\n"
        + "local w, h = spr.width, spr.height\n"
        + f"local C = {{ {color_table} }}\n"
        + "local function put(x, y, c)\n"
        "  if x >= w or y >= h then\n"
        '    error(string.format("pixel (%d,%d) out of bounds for %dx%d canvas", x, y, w, h))\n'
        "  end\n"
        "  img:drawPixel(x, y, c)\n"
        "end\n"
        + puts
        + _save_sprite(path)
        + _SNAP_REPORT
    )


def script_draw_shape(path: Path, op: ShapeOp, layer: str | None, frame: int) -> str:
    points = ", ".join(f"Point({x}, {y})" for x, y in op.points)
    extra = ""
    bounds_check = ""
    if op.tool == "paint_bucket":
        extra = f"  contiguous = true,\n  tolerance = {op.tolerance},\n"
        x, y = op.points[0]
        bounds_check = (
            f"if {x} >= spr.width or {y} >= spr.height then\n"
            f'  error(string.format("fill point ({x},{y}) out of bounds for %dx%d canvas", spr.width, spr.height))\n'
            "end\n"
        )
    return (
        _open_sprite(path)
        + _AMCP_COLOR
        + _check_frame(frame)
        + _resolve_layer(layer)
        + bounds_check
        + _ensure_full_canvas_cel(frame)
        + "app.useTool{\n"
        f'  tool = "{op.tool}",\n'
        f"  color = {color_call(op.color)},\n"
        "  layer = layer,\n"
        f"  frame = {frame},\n"
        f"  points = {{ {points} }},\n"
        + extra
        + "}\n"
        + _save_sprite(path)
        + _SNAP_REPORT
    )


def script_clear_region(
    path: Path, rect: tuple[int, int, int, int], layer: str | None, frame: int
) -> str:
    x, y, w, h = rect
    return (
        _open_sprite(path)
        + _check_frame(frame)
        + _resolve_layer(layer)
        + f"local rx, ry, rw, rh = {x}, {y}, {w}, {h}\n"
        + "if rw == 0 then rw = spr.width - rx end\n"
        + "if rh == 0 then rh = spr.height - ry end\n"
        + "if rw < 1 or rh < 1 or rx + rw > spr.width or ry + rh > spr.height then\n"
        + '  error(string.format("clear region (%d,%d %dx%d) extends past the canvas (%dx%d)",\n'
        + "    rx, ry, rw, rh, spr.width, spr.height))\n"
        + "end\n"
        + f"local cel = layer:cel({frame})\n"
        + "if cel == nil then\n"
        + f'  error("layer \'" .. layer.name .. "\' has no content on frame {frame} — nothing to clear")\n'
        + "end\n"
        # Image:clear rects are image-local (offset by the cel position), so
        # normalize to a full-canvas cel first; canvas coords then apply directly.
        + "local full = Image(spr.width, spr.height, spr.colorMode)\n"
        + "full:drawImage(cel.image, cel.position)\n"
        + f"cel = spr:newCel(layer, {frame}, full, Point(0, 0))\n"
        + "cel.image:clear(Rectangle(rx, ry, rw, rh))\n"
        + _save_sprite(path)
    )


def script_add_layer(path: Path, name: str) -> str:
    q = lua_quote(name)
    return (
        _open_sprite(path)
        + "for i = 1, #spr.layers do\n"
        f"  if string.lower(spr.layers[i].name) == string.lower({q}) then\n"
        f'    error("layer already exists: " .. {q})\n'
        "  end\n"
        "end\n"
        "local layer = spr:newLayer()\n"
        f"layer.name = {q}\n"
        + _save_sprite(path)
    )


def script_add_frame(path: Path, duration_ms: int, mode: str) -> str:
    if mode == "duplicate":
        # no-arg newFrame appends a copy of the last frame and returns the new
        # frame; newFrame(n) returns the frame at position n, not the copy
        new_frame = "local fr = spr:newFrame()\n"
    else:
        new_frame = "local fr = spr:newEmptyFrame(#spr.frames + 1)\n"
    return (
        _open_sprite(path)
        + new_frame
        + f"fr.duration = {duration_ms / 1000!r}\n"
        + _save_sprite(path)
        + f'print("{RESULT_MARKER} " .. string.format(\'{{"frame": %d, "total_frames": %d}}\', fr.frameNumber, #spr.frames))\n'
    )


def script_add_tag(
    path: Path, name: str, from_frame: int, to_frame: int, anidir_lua: str
) -> str:
    q = lua_quote(name)
    return (
        _open_sprite(path)
        # newTag does not bounds-check its arguments; an out-of-range tag
        # silently corrupts later exports
        + _check_frame(to_frame)
        + "for i = 1, #spr.tags do\n"
        f"  if spr.tags[i].name == {q} then\n"
        f'    error("tag already exists: " .. {q})\n'
        "  end\n"
        "end\n"
        f"local tag = spr:newTag({from_frame}, {to_frame})\n"
        f"tag.name = {q}\n"
        f"tag.aniDir = {anidir_lua}\n"
        + _save_sprite(path)
    )


def script_set_frame_duration(path: Path, frame: int, duration_ms: int) -> str:
    return (
        _open_sprite(path)
        + _check_frame(frame)
        + f"spr.frames[{frame}].duration = {duration_ms / 1000!r}\n"
        + _save_sprite(path)
    )


def script_delete_frame(path: Path, frame: int) -> str:
    return (
        _open_sprite(path)
        + _check_frame(frame)
        + "if #spr.frames == 1 then\n"
        + '  error("cannot delete the only frame — a sprite needs at least one frame")\n'
        + "end\n"
        + f"spr:deleteFrame({frame})\n"
        + _save_sprite(path)
        + f'print("{RESULT_MARKER} " .. string.format(\'{{"deleted_frame": %d, "total_frames": %d}}\', {frame}, #spr.frames))\n'
    )


def script_copy_cel(path: Path, from_frame: int, to_frame: int, layer: str | None) -> str:
    return (
        _open_sprite(path)
        + _check_frame(from_frame)
        + _check_frame(to_frame)
        + _resolve_layer(layer)
        + f"local src = layer:cel({from_frame})\n"
        + "if src == nil then\n"
        + f'  error("layer \'" .. layer.name .. "\' has no content on frame {from_frame} — nothing to copy")\n'
        + "end\n"
        # newCel replaces any existing target cel and deep-copies the image
        + f"spr:newCel(layer, {to_frame}, src.image, src.position)\n"
        + _save_sprite(path)
    )


def script_preview(path: Path, out_png: Path, scale: int, frame: int, grid: int = 0) -> str:
    q = lua_quote(str(out_png))
    # Grid lines need an exact magenta in every color mode, so the in-memory
    # sprite is normalized to RGB first (preview never saves the sprite).
    grid_convert = (
        "if spr.colorMode ~= ColorMode.RGB then\n"
        '  app.command.ChangePixelFormat{ ui = false, format = "rgb" }\n'
        "end\n"
        if grid > 0
        else ""
    )
    grid_lines = (
        (
            f"local step = {grid * scale}\n"
            "local gcol = Color{ r=255, g=0, b=255, a=255 }\n"
            f"local gw, gh = spr.width * {scale}, spr.height * {scale}\n"
            "for gx = step, gw - 1, step do\n"
            "  for yy = 0, gh - 1 do img:drawPixel(gx, yy, gcol) end\n"
            "end\n"
            "for gy = step, gh - 1, step do\n"
            "  for xx = 0, gw - 1 do img:drawPixel(xx, gy, gcol) end\n"
            "end\n"
        )
        if grid > 0
        else ""
    )
    return (
        _open_sprite(path)
        + _check_frame(frame)
        + f"if spr.width * {scale} > 4096 or spr.height * {scale} > 4096 then\n"
        f'  error(string.format("preview would be %dx%d; keep scaled size under 4096px (canvas %dx%d, scale {scale})",\n'
        f"    spr.width * {scale}, spr.height * {scale}, spr.width, spr.height))\n"
        "end\n"
        + grid_convert
        + "local img = Image(spr.width, spr.height, spr.colorMode)\n"
        + f"img:drawSprite(spr, {frame})\n"
        + f"img:resize{{ width = spr.width * {scale}, height = spr.height * {scale} }}\n"
        + grid_lines
        + f"img:saveAs{{ filename = {q}, palette = spr.palettes[1] }}\n"
        + f"local f = io.open({q}, \"rb\")\n"
        + f'if not f then error("preview PNG was not written: " .. {q}) end\n'
        + "f:close()\n"
    )


_READ_KEYS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def script_read_pixels(path: Path, rect: tuple[int, int, int, int], frame: int) -> str:
    x, y, w, h = rect
    return (
        _open_sprite(path)
        + _check_frame(frame)
        + f"local rx, ry, rw, rh = {x}, {y}, {w}, {h}\n"
        + "if rw == 0 then rw = spr.width - rx end\n"
        + "if rh == 0 then rh = spr.height - ry end\n"
        + "if rw < 1 or rh < 1 or rx + rw > spr.width or ry + rh > spr.height then\n"
        + '  error(string.format("read region (%d,%d %dx%d) extends past the canvas (%dx%d)",\n'
        + "    rx, ry, rw, rh, spr.width, spr.height))\n"
        + "end\n"
        + "if rw * rh > 4096 then\n"
        + '  error(string.format("read region %dx%d is %d pixels; keep it at or under 4096 '
        + '— pass a smaller x/y/width/height window", rw, rh, rw * rh))\n'
        + "end\n"
        + "local img = Image(spr.width, spr.height, spr.colorMode)\n"
        + f"img:drawSprite(spr, {frame})\n"
        + "local pc = app.pixelColor\n"
        + f'local keys = "{_READ_KEYS}"\n'
        + r"""
local legend = {}
local order = {}
local rows = {}
for gy = ry, ry + rh - 1 do
  local row = {}
  for gx = rx, rx + rw - 1 do
    local v = img:getPixel(gx, gy)
    local r, g, b, a = 0, 0, 0, 0
    if spr.colorMode == ColorMode.GRAYSCALE then
      local gv = pc.grayaV(v)
      r, g, b, a = gv, gv, gv, pc.grayaA(v)
    elseif spr.colorMode == ColorMode.INDEXED then
      if v ~= spr.transparentColor then
        local c = spr.palettes[1]:getColor(v)
        r, g, b, a = c.red, c.green, c.blue, c.alpha
      end
    else
      r, g, b, a = pc.rgbaR(v), pc.rgbaG(v), pc.rgbaB(v), pc.rgbaA(v)
    end
    local ch = "."
    if a > 0 then
      local hex
      if a == 255 then hex = string.format("#%02x%02x%02x", r, g, b)
      else hex = string.format("#%02x%02x%02x%02x", r, g, b, a) end
      ch = legend[hex]
      if ch == nil then
        if #order >= #keys then
          error("read region has more than " .. #keys .. " distinct colors; read a smaller region")
        end
        ch = keys:sub(#order + 1, #order + 1)
        legend[hex] = ch
        order[#order + 1] = string.format('"%s": "%s"', ch, hex)
      end
    end
    row[#row + 1] = ch
  end
  rows[#rows + 1] = '"' .. table.concat(row) .. '"'
end
local legend_json = '".": "transparent"'
if #order > 0 then legend_json = legend_json .. ", " .. table.concat(order, ", ") end
"""
        + f'print("{RESULT_MARKER} " .. string.format(\n'
        + "  '{\"x\": %d, \"y\": %d, \"width\": %d, \"height\": %d, \"legend\": {%s}, \"rows\": [%s]}',\n"
        + '  rx, ry, rw, rh, legend_json, table.concat(rows, ", ")))\n'
    )


def script_export_flat(path: Path, out: Path) -> str:
    q = lua_quote(str(out))
    return (
        _open_sprite(path)
        + _JESC
        + f"if not spr:saveCopyAs({q}) then error(\"failed to export: \" .. {q}) end\n"
        + f"local f = io.open({q}, \"rb\")\n"
        + f'if not f then error("export was not written: " .. {q}) end\n'
        + "f:close()\n"
        # flat formats play frames forward only; report tags whose direction
        # the export just dropped so the caller can warn
        + 'local anidirs = { [1] = "reverse", [2] = "pingpong", [3] = "pingpong_reverse" }\n'
        + "local nf = {}\n"
        + "for i = 1, #spr.tags do\n"
        + "  local t = spr.tags[i]\n"
        + "  local d = anidirs[t.aniDir]\n"
        + "  if d then nf[#nf + 1] = string.format('\"%s (%s)\"', jesc(t.name), d) end\n"
        + "end\n"
        + f'print("{RESULT_MARKER} " .. string.format(\'{{"frames": %d, "nonforward_tags": [%s]}}\', #spr.frames, table.concat(nf, ", ")))\n'
    )


def script_export_spritesheet(
    path: Path,
    out_png: Path,
    data_json: Path,
    sheet_type: str,
    columns: int,
    padding: int,
) -> str:
    tq = lua_quote(str(out_png))
    dq = lua_quote(str(data_json))
    return (
        _open_sprite(path)
        + "app.command.ExportSpriteSheet{\n"
        "  ui = false,\n"
        "  askOverwrite = false,\n"
        "  recent = false,\n"
        f'  type = "{sheet_type}",\n'
        f"  columns = {columns},\n"
        f"  textureFilename = {tq},\n"
        f"  dataFilename = {dq},\n"
        '  dataFormat = "json-array",\n'
        f"  borderPadding = {padding},\n"
        f"  shapePadding = {padding},\n"
        "  innerPadding = 0,\n"
        "  trim = false,\n"
        "  listLayers = false,\n"
        "  listTags = true,\n"
        "  listSlices = false,\n"
        "}\n"
        + f"for _, p in ipairs({{ {tq}, {dq} }}) do\n"
        '  local f = io.open(p, "rb")\n'
        '  if not f then error("spritesheet output was not written: " .. p) end\n'
        "  f:close()\n"
        "end\n"
        + f'print("{RESULT_MARKER} " .. string.format(\'{{"frames": %d}}\', #spr.frames))\n'
    )
