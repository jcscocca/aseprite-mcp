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
_AMCP_COLOR = r"""
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
    return Color{ index = best }
  end
  return Color{ r = r, g = g, b = b, a = a }
end
"""


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
"""
        + f'print("{RESULT_MARKER} " .. string.format(\n'
        + "  '{\"width\": %d, \"height\": %d, \"color_mode\": \"%s\", \"layers\": [%s], \"frames\": [%s], \"palette\": [%s]}',\n"
        + "  spr.width, spr.height, cm,\n"
        + '  table.concat(layers, ", "), table.concat(frames, ", "), table.concat(pcolors, ", ")))\n'
    )


def script_set_palette(path: Path, colors: list[RGBA]) -> str:
    return _open_sprite(path) + _palette_snippet(colors) + _save_sprite(path)


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


def script_preview(path: Path, out_png: Path, scale: int, frame: int) -> str:
    q = lua_quote(str(out_png))
    return (
        _open_sprite(path)
        + _check_frame(frame)
        + f"if spr.width * {scale} > 4096 or spr.height * {scale} > 4096 then\n"
        f'  error(string.format("preview would be %dx%d; keep scaled size under 4096px (canvas %dx%d, scale {scale})",\n'
        f"    spr.width * {scale}, spr.height * {scale}, spr.width, spr.height))\n"
        "end\n"
        + "local img = Image(spr.width, spr.height, spr.colorMode)\n"
        + f"img:drawSprite(spr, {frame})\n"
        + f"img:resize{{ width = spr.width * {scale}, height = spr.height * {scale} }}\n"
        + f"img:saveAs{{ filename = {q}, palette = spr.palettes[1] }}\n"
        + f"local f = io.open({q}, \"rb\")\n"
        + f'if not f then error("preview PNG was not written: " .. {q}) end\n'
        + "f:close()\n"
    )


def script_export_flat(path: Path, out: Path) -> str:
    q = lua_quote(str(out))
    return (
        _open_sprite(path)
        + f"if not spr:saveCopyAs({q}) then error(\"failed to export: \" .. {q}) end\n"
        + f"local f = io.open({q}, \"rb\")\n"
        + f'if not f then error("export was not written: " .. {q}) end\n'
        + "f:close()\n"
        + f'print("{RESULT_MARKER} " .. string.format(\'{{"frames": %d}}\', #spr.frames))\n'
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
