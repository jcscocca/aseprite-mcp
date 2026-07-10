"""Unit tests for Lua codegen — asserts on generated script text, no binary needed."""

from __future__ import annotations

from pathlib import Path

from aseprite_mcp.core import lua
from aseprite_mcp.core.ops import RGBA, Pixel, ShapeOp

SPR = Path("/tmp/art/slime.ase")


def test_lua_quote_escapes():
    assert lua.lua_quote('a"b\\c') == '"a\\"b\\\\c"'
    assert lua.lua_quote("line1\nline2") == '"line1\\nline2"'


def test_color_literal():
    assert lua.color_literal(RGBA(1, 2, 3, 128)) == "Color{ r=1, g=2, b=3, a=128 }"


def test_create_canvas_script():
    s = lua.script_create_canvas(SPR, 16, 24, "ColorMode.INDEXED", [RGBA(0, 0, 0), RGBA(255, 255, 255)])
    assert "Sprite(16, 24, ColorMode.INDEXED)" in s
    assert 'saveAs("/tmp/art/slime.ase")' in s
    assert "Palette(#colors)" in s
    assert "pal:setColor(i - 1, c)" in s
    assert "Color{ r=255, g=255, b=255, a=255 }" in s
    assert lua.RESULT_MARKER in s


def test_create_canvas_without_palette_skips_palette_code():
    s = lua.script_create_canvas(SPR, 8, 8, "ColorMode.RGB", None)
    assert "Palette" not in s


def test_create_canvas_refuses_missing_save():
    s = lua.script_create_canvas(SPR, 8, 8, "ColorMode.RGB", None)
    assert 'error("failed to save sprite' in s


def test_get_canvas_info_script():
    s = lua.script_get_canvas_info(SPR)
    assert f'app.open({lua.lua_quote(str(SPR))})' in s
    assert "could not open sprite" in s
    assert "duration_ms" in s
    assert "jesc" in s  # layer names are json-escaped
    assert lua.RESULT_MARKER in s


def test_draw_pixels_script_batches_colors_and_checks_bounds():
    pixels = [
        Pixel(0, 0, RGBA(255, 0, 0)),
        Pixel(1, 0, RGBA(255, 0, 0)),
        Pixel(2, 2, RGBA(0, 0, 255)),
    ]
    s = lua.script_draw_pixels(SPR, pixels, layer=None, frame=2)
    # distinct colors defined once in a table, via the mode-aware helper
    assert s.count("amcp_color(255, 0, 0, 255)") == 1
    assert "spr.colorMode == ColorMode.INDEXED" in s  # indexed colors resolve against the sprite palette
    assert "put(0, 0, C[1])" in s
    assert "put(1, 0, C[1])" in s
    assert "put(2, 2, C[2])" in s
    assert "out of bounds" in s
    # cel normalized to full canvas so putPixel can't silently no-op
    assert "drawImage" in s
    assert "newCel" in s
    assert "spr.layers[1]" in s  # default layer
    assert "frame 2 out of range" in s or "#spr.frames" in s
    assert "saveAs" in s


def test_draw_pixels_named_layer_lookup_lists_available():
    s = lua.script_draw_pixels(SPR, [Pixel(0, 0, RGBA(1, 1, 1))], layer="body", frame=1)
    assert 'spr.layers["body"]' in s
    assert "layer not found" in s
    assert "table.concat" in s  # error lists available layer names
    assert "isGroup" in s


def test_draw_shape_line_script():
    op = ShapeOp(tool="line", points=[(0, 0), (15, 15)], color=RGBA(0, 255, 0))
    s = lua.script_draw_shape(SPR, op, layer=None, frame=1)
    assert 'tool = "line"' in s
    assert "color = amcp_color(0, 255, 0, 255)" in s
    assert "Point(0, 0), Point(15, 15)" in s
    assert "app.useTool" in s
    assert "tolerance" not in s
    assert "saveAs" in s


def test_draw_scripts_report_snapped_indexed_colors():
    # indexed mode resolves colors to the nearest palette entry; the scripts
    # must report inexact matches so the agent hears about the substitution
    s = lua.script_draw_pixels(SPR, [Pixel(0, 0, RGBA(1, 1, 1))], layer=None, frame=1)
    assert "AMCP_SNAPPED" in s
    assert '"snapped"' in s
    op = ShapeOp(tool="line", points=[(0, 0), (1, 1)], color=RGBA(1, 1, 1))
    g = lua.script_draw_shape(SPR, op, layer=None, frame=1)
    assert "AMCP_SNAPPED" in g
    assert '"snapped"' in g


def test_draw_shape_fill_script_has_tolerance_and_bounds_check():
    op = ShapeOp(tool="paint_bucket", points=[(3, 4)], color=RGBA(9, 9, 9), tolerance=32)
    s = lua.script_draw_shape(SPR, op, layer=None, frame=1)
    assert 'tool = "paint_bucket"' in s
    assert "tolerance = 32" in s
    assert "contiguous = true" in s
    assert "out of bounds" in s


def test_flip_script_crops_flips_and_blits():
    s = lua.script_flip(SPR, "FlipType.HORIZONTAL", rect=(0, 0, 0, 0), layer=None, frame=1)
    assert "Image(img, Rectangle(rx, ry, rw, rh))" in s  # crop-copy of the region
    assert "flip(FlipType.HORIZONTAL)" in s
    assert ":clear(Rectangle(" in s  # drawImage blends, so clear before blitting back
    assert "nothing to flip" in s
    assert "past the canvas" in s
    assert "saveAs" in s


def test_mirror_script_flips_source_half_onto_dest():
    s = lua.script_mirror(SPR, "left", layer=None, frame=1)
    assert "FlipType.HORIZONTAL" in s
    assert "nothing to mirror" in s
    assert "saveAs" in s
    t = lua.script_mirror(SPR, "top", layer=None, frame=1)
    assert "FlipType.VERTICAL" in t


def test_shift_script_wrap_and_full_clear_guard():
    s = lua.script_shift(SPR, 1, -2, wrap=False, layer=None, frame=1)
    assert "off the canvas" in s  # a shift >= canvas size would silently blank the cel
    assert "nothing to shift" in s
    assert "saveAs" in s
    w = lua.script_shift(SPR, 1, 0, wrap=True, layer=None, frame=1)
    assert w.count("drawImage") >= 4  # four tiled copies cover the wrap seam


def test_rotate_script_square_guard_for_quarter_turns():
    s = lua.script_rotate(SPR, 90, layer=None, frame=1)
    assert "square" in s  # 90/270 swap dimensions, so the canvas must be square
    assert "getPixel" in s
    assert "nothing to rotate" in s
    t = lua.script_rotate(SPR, 180, layer=None, frame=1)
    assert "square" not in t  # 180 keeps dimensions — any canvas


def test_replace_color_script_probes_mode_correct_values():
    s = lua.script_replace_color(
        SPR, RGBA(255, 0, 0), RGBA(0, 0, 255), rect=(0, 0, 0, 0), layer=None, frame=1
    )
    # a 1x1 probe image renders both colors in the sprite's own color mode, so
    # matching works identically in rgb/indexed/grayscale
    assert "Image(1, 1, spr.colorMode)" in s
    assert "amcp_color(255, 0, 0, 255)" in s
    assert "amcp_color(0, 0, 255, 255)" in s
    assert "getPixel" in s
    assert '"replaced"' in s
    assert "nothing to replace" in s  # empty cel is a loud error
    assert "past the canvas" in s
    assert "saveAs" in s


def test_set_palette_script():
    s = lua.script_set_palette(SPR, [RGBA(1, 2, 3)])
    assert "spr:setPalette(pal)" in s
    assert "Color{ r=1, g=2, b=3, a=255 }" in s


def test_set_palette_script_guards_in_use_indices():
    s = lua.script_set_palette(SPR, [RGBA(1, 2, 3)])
    # shrinking below an in-use index silently blanks pixels, so every cel is
    # scanned before the palette is replaced
    assert "ColorMode.INDEXED" in s
    assert "cel.image:pixels()" in s
    assert "uses palette index" in s


def test_add_layer_script_fails_on_duplicate():
    s = lua.script_add_layer(SPR, "body")
    assert "spr:newLayer()" in s
    assert 'layer.name = "body"' in s
    assert "already exists" in s
    assert "string.lower" in s  # aseprite name lookup is case-insensitive


def test_add_frame_duplicate_mode():
    s = lua.script_add_frame(SPR, 150, "duplicate")
    assert "spr:newFrame()" in s  # no-arg form appends a copy of the last frame and returns it
    assert "fr.duration = 0.15" in s
    assert lua.RESULT_MARKER in s


def test_add_frame_empty_mode():
    s = lua.script_add_frame(SPR, 1000, "empty")
    assert "spr:newEmptyFrame(#spr.frames + 1)" in s
    assert "fr.duration = 1.0" in s


def test_add_tag_script():
    s = lua.script_add_tag(SPR, "walk", 2, 4, "AniDir.PING_PONG")
    assert "spr:newTag(2, 4)" in s
    assert 'tag.name = "walk"' in s
    assert "tag.aniDir = AniDir.PING_PONG" in s
    # newTag itself does no bounds checking, so the script must
    assert "frame 4 out of range" in s or "#spr.frames" in s
    assert "already exists" in s  # duplicate names would collide as animations
    assert "saveAs" in s


def test_delete_tag_script():
    s = lua.script_delete_tag(SPR, "walk")
    assert "spr:deleteTag(" in s
    assert "tag not found" in s
    assert "table.concat" in s  # error lists the existing tag names
    assert "saveAs" in s


def test_delete_layer_script_guards_last_layer():
    s = lua.script_delete_layer(SPR, "body")
    assert 'spr.layers["body"]' in s
    assert "spr:deleteLayer(layer)" in s
    assert "the only layer" in s
    assert "saveAs" in s


def test_rename_layer_script_checks_collisions():
    s = lua.script_rename_layer(SPR, "body", "torso")
    assert 'spr.layers["body"]' in s
    assert 'layer.name = "torso"' in s
    assert "already exists" in s
    assert "string.lower" in s  # collision check is case-insensitive, excluding self
    assert "saveAs" in s


def test_get_canvas_info_script_lists_tags():
    s = lua.script_get_canvas_info(SPR)
    assert "spr.tags" in s
    assert "aniDir" in s
    assert "pingpong_reverse" in s  # aniDir ints map to export direction strings


def test_delete_frame_script_guards_last_frame():
    s = lua.script_delete_frame(SPR, 2)
    assert "spr:deleteFrame(2)" in s
    assert "the only frame" in s  # a sprite must keep at least one frame
    assert "frame 2 out of range" in s or "#spr.frames" in s
    assert lua.RESULT_MARKER in s
    assert "saveAs" in s


def test_copy_cel_script():
    s = lua.script_copy_cel(SPR, 1, 3, layer="body")
    assert 'spr.layers["body"]' in s
    assert "layer:cel(1)" in s
    assert "nothing to copy" in s  # empty source cel is a loud error
    # newCel deep-copies the source image, so frames stay independent
    assert "spr:newCel(layer, 3, src.image, src.position)" in s
    assert "saveAs" in s


def test_set_frame_duration_script():
    s = lua.script_set_frame_duration(SPR, 2, 250)
    assert "spr.frames[2].duration = 0.25" in s
    assert "frame 2 out of range" in s or "#spr.frames" in s
    assert "saveAs" in s


def test_preview_script_scales_nearest_and_verifies_output():
    out = Path("/tmp/preview.png")
    s = lua.script_preview(SPR, out, scale=8, frame=1)
    assert "img:drawSprite(spr, 1)" in s
    assert "4096" in s  # guard against huge scaled previews
    assert "img:resize{ width = spr.width * 8, height = spr.height * 8 }" in s
    assert "palette = spr.palettes[1]" in s
    assert 'io.open("/tmp/preview.png", "rb")' in s
    assert "was not written" in s


def test_export_flat_png_and_gif():
    s = lua.script_export_flat(SPR, Path("/tmp/out.png"))
    assert 'saveCopyAs("/tmp/out.png")' in s
    assert lua.RESULT_MARKER in s  # reports frame count so caller can warn on multi-frame PNG
    g = lua.script_export_flat(SPR, Path("/tmp/out.gif"))
    assert 'saveCopyAs("/tmp/out.gif")' in g


def test_export_flat_reports_nonforward_tags():
    # GIF plays frames linearly; pingpong/reverse tags are silently dropped by
    # the format, so the script reports them for the caller to warn about
    s = lua.script_export_flat(SPR, Path("/tmp/out.gif"))
    assert "nonforward_tags" in s
    assert "aniDir" in s
    assert "pingpong" in s


def test_export_flat_scale_resizes_in_memory_only():
    s = lua.script_export_flat(SPR, Path("/tmp/out.gif"), scale=4)
    assert "spr:resize(spr.width * 4, spr.height * 4)" in s  # nearest-neighbor by default
    assert "saveAs" not in s.replace("saveCopyAs", "")  # resized sprite never saved back
    d = lua.script_export_flat(SPR, Path("/tmp/out.gif"))
    assert "resize" not in d


def test_export_spritesheet_scale():
    s = lua.script_export_spritesheet(
        SPR, Path("/tmp/sheet.png"), Path("/tmp/sheet.raw.json"),
        sheet_type="rows", columns=0, padding=0, scale=2,
    )
    assert "spr:resize(spr.width * 2, spr.height * 2)" in s


def test_export_spritesheet_script():
    s = lua.script_export_spritesheet(
        SPR, Path("/tmp/sheet.png"), Path("/tmp/sheet.raw.json"),
        sheet_type="rows", columns=3, padding=1,
    )
    assert "app.command.ExportSpriteSheet" in s
    assert "ui = false" in s
    assert "askOverwrite = false" in s
    assert 'type = "rows"' in s  # lowercase string form — enum table is not exposed in Lua
    assert "columns = 3" in s
    assert 'dataFormat = "json-array"' in s
    assert 'textureFilename = "/tmp/sheet.png"' in s
    assert 'dataFilename = "/tmp/sheet.raw.json"' in s
    assert "borderPadding = 1" in s
    assert "shapePadding = 1" in s
    assert "listTags = true" in s


def test_paths_with_quotes_are_escaped_everywhere():
    tricky = Path('/tmp/we"ird/sl\\ime.ase')
    s = lua.script_get_canvas_info(tricky)
    assert '"/tmp/we\\"ird/sl\\\\ime.ase"' in s


def test_read_pixels_script_builds_legend_grid():
    s = lua.script_read_pixels(SPR, rect=(2, 3, 8, 4), frame=2)
    assert "img:drawSprite(spr, 2)" in s
    assert "getPixel" in s
    assert "transparent" in s  # '.' legend entry
    assert "distinct colors" in s  # legend overflow fails loudly
    assert "4096" in s  # area cap enforced against the real canvas size
    assert "spr.transparentColor" in s  # indexed transparency
    assert "palettes[1]" in s  # indexed colors resolve via the sprite palette
    assert "grayaV" in s  # grayscale support
    assert lua.RESULT_MARKER in s
    assert "saveAs" not in s  # read-only: never writes the sprite


def test_read_pixels_layer_isolation():
    s = lua.script_read_pixels(SPR, rect=(0, 0, 0, 0), frame=1, layer="body")
    assert 'spr.layers["body"]' in s
    assert "layer:cel(1)" in s
    assert "drawSprite" not in s  # the layer's own cel, not the composite
    assert "layer not found" in s


def test_read_pixels_zero_rect_resolves_to_canvas_in_lua():
    s = lua.script_read_pixels(SPR, rect=(0, 0, 0, 0), frame=1)
    assert "spr.width" in s and "spr.height" in s
    assert "past the canvas" in s


def test_clear_region_script_raw_image_clear():
    s = lua.script_clear_region(SPR, rect=(2, 3, 4, 5), layer="fx", frame=2)
    assert 'spr.layers["fx"]' in s
    assert "nothing to clear" in s  # empty layer/frame is a loud error, not a no-op
    assert "drawImage" in s  # cel normalized to full canvas so rect coords = canvas coords
    assert ":clear(Rectangle(" in s
    assert "app.useTool" not in s  # raw image clear — tool strokes alpha-blend and can't erase
    assert "past the canvas" in s
    assert "saveAs" in s


def test_clear_region_zero_rect_resolves_to_canvas():
    s = lua.script_clear_region(SPR, rect=(0, 0, 0, 0), layer=None, frame=1)
    assert "spr.width" in s and "spr.height" in s


def test_preview_script_grid_overlay():
    s = lua.script_preview(SPR, Path("/tmp/p.png"), scale=8, frame=1, grid=8)
    assert "ChangePixelFormat" in s  # normalized to RGB so the grid color is exact in any mode
    assert 'format = "rgb"' in s
    assert "Color{ r=255, g=0, b=255, a=255 }" in s  # magenta lines
    assert "64" in s  # line spacing = grid * scale
    assert "drawPixel" in s


def test_preview_all_frames_contact_sheet():
    s = lua.script_preview(SPR, Path("/tmp/p.png"), scale=8, frame=1, all_frames=True)
    assert "#spr.frames" in s
    assert "drawSprite(spr, i" in s  # one tile per frame, 1px gap between
    assert "4096" in s  # size guard applies to the whole strip


def test_preview_script_no_grid_by_default():
    s = lua.script_preview(SPR, Path("/tmp/p.png"), scale=8, frame=1)
    assert "ChangePixelFormat" not in s
    assert "drawPixel" not in s
