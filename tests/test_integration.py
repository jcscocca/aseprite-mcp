"""Integration tests running the real Aseprite binary.

Skipped cleanly when the binary is missing (set ASEPRITE_BIN). Exported PNGs
are verified pixel-by-pixel with Pillow.
"""

from __future__ import annotations

import io
import os
from pathlib import Path

import pytest

from aseprite_mcp.core.runner import DEFAULT_ASEPRITE_BIN, AsepriteError

_BIN = os.environ.get("ASEPRITE_BIN", DEFAULT_ASEPRITE_BIN)
pytestmark = pytest.mark.skipif(
    not Path(_BIN).is_file(),
    reason="Aseprite binary not available (set ASEPRITE_BIN)",
)
pytest.importorskip("PIL.Image", reason="pillow required for pixel asserts")

from PIL import Image as PILImage  # noqa: E402

from aseprite_mcp.mcp import tools  # noqa: E402

RED = "#ff0000"
GREEN = "#00ff00"
BLUE = "#0000ff"


def _rgba(png_path) -> PILImage.Image:
    return PILImage.open(png_path).convert("RGBA")


def test_create_and_info_roundtrip(tmp_path):
    spr = str(tmp_path / "canvas.ase")
    msg = tools.create_canvas(spr, 16, 12)
    assert "16x12" in msg and "rgb" in msg
    info = tools.get_canvas_info(spr)
    assert info["width"] == 16
    assert info["height"] == 12
    assert info["color_mode"] == "rgb"
    assert len(info["layers"]) == 1
    assert info["layers"][0]["is_group"] is False
    assert len(info["frames"]) == 1
    assert info["frames"][0]["duration_ms"] > 0
    assert len(info["palette"]) > 0


def test_create_refuses_silent_overwrite(tmp_path):
    spr = str(tmp_path / "x.ase")
    tools.create_canvas(spr, 4, 4)
    with pytest.raises(ValueError, match="overwrite"):
        tools.create_canvas(spr, 4, 4)
    tools.create_canvas(spr, 8, 8, overwrite=True)
    assert tools.get_canvas_info(spr)["width"] == 8


def test_draw_pixels_exact_rgba(tmp_path):
    spr = str(tmp_path / "px.ase")
    out = tmp_path / "px.png"
    tools.create_canvas(spr, 4, 4)
    tools.draw_pixels(
        spr,
        [
            {"x": 0, "y": 0, "color": RED},
            {"x": 3, "y": 3, "color": "#0000ff80"},
        ],
    )
    tools.export(spr, str(out), format="png")
    img = _rgba(out)
    assert img.size == (4, 4)
    assert img.getpixel((0, 0)) == (255, 0, 0, 255)
    assert img.getpixel((3, 3)) == (0, 0, 255, 128)
    assert img.getpixel((1, 1))[3] == 0  # untouched pixel stays transparent


def test_draw_grid_roundtrips_with_read_pixels(tmp_path):
    spr = str(tmp_path / "grid.ase")
    tools.create_canvas(spr, 4, 4)
    msg = tools.draw_grid(spr, rows=[".rr.", "r..r"], legend={"r": RED}, x=0, y=1)
    assert "4 pixel(s)" in msg
    result = tools.read_pixels(spr)
    assert result["rows"] == ["....", ".aa.", "a..a", "...."]
    assert result["legend"]["a"] == RED


def test_draw_grid_erases_with_transparent_legend_color(tmp_path):
    spr = str(tmp_path / "gerase.ase")
    tools.create_canvas(spr, 2, 1)
    tools.draw_shape(spr, "rectangle", [[0, 0], [1, 0]], GREEN, filled=True)
    tools.draw_grid(spr, rows=["e."], legend={"e": "#00000000"})
    px = tools.read_pixels(spr)
    assert px["rows"] == [".a"]
    assert px["legend"]["a"] == GREEN


def test_filled_rectangle(tmp_path):
    spr = str(tmp_path / "rect.ase")
    out = tmp_path / "rect.png"
    tools.create_canvas(spr, 8, 8)
    tools.draw_shape(spr, "rectangle", [[1, 1], [6, 6]], GREEN, filled=True)
    tools.export(spr, str(out), format="png")
    img = _rgba(out)
    for xy in [(1, 1), (6, 6), (3, 4)]:
        assert img.getpixel(xy) == (0, 255, 0, 255), xy
    assert img.getpixel((0, 0))[3] == 0
    assert img.getpixel((7, 7))[3] == 0


def test_line(tmp_path):
    spr = str(tmp_path / "line.ase")
    out = tmp_path / "line.png"
    tools.create_canvas(spr, 8, 8)
    tools.draw_shape(spr, "line", [[0, 0], [7, 7]], RED)
    tools.export(spr, str(out), format="png")
    img = _rgba(out)
    for i in range(8):
        assert img.getpixel((i, i)) == (255, 0, 0, 255), i
    assert img.getpixel((7, 0))[3] == 0


def test_flood_fill_replaces_contiguous_region(tmp_path):
    spr = str(tmp_path / "fill.ase")
    out = tmp_path / "fill.png"
    tools.create_canvas(spr, 8, 8)
    tools.draw_shape(spr, "rectangle", [[1, 1], [6, 6]], GREEN, filled=True)
    tools.draw_shape(spr, "fill", [[3, 3]], BLUE)
    tools.export(spr, str(out), format="png")
    img = _rgba(out)
    assert img.getpixel((1, 1)) == (0, 0, 255, 255)
    assert img.getpixel((6, 6)) == (0, 0, 255, 255)
    assert img.getpixel((0, 0))[3] == 0  # outside the region untouched


def test_flip_horizontal_region_then_whole(tmp_path):
    spr = str(tmp_path / "flip.ase")
    tools.create_canvas(spr, 4, 1)
    tools.draw_grid(spr, rows=["rg.."], legend={"r": RED, "g": GREEN})
    tools.flip(spr, "horizontal", x=0, y=0, width=2, height=1)
    px = tools.read_pixels(spr)
    assert px["rows"] == ["ab.."]
    assert (px["legend"]["a"], px["legend"]["b"]) == (GREEN, RED)
    tools.flip(spr, "horizontal")  # whole canvas
    px = tools.read_pixels(spr)
    assert px["rows"] == ["..ab"]
    assert (px["legend"]["a"], px["legend"]["b"]) == (RED, GREEN)


def test_flip_vertical(tmp_path):
    spr = str(tmp_path / "flipv.ase")
    tools.create_canvas(spr, 1, 2)
    tools.draw_grid(spr, rows=["r", "."], legend={"r": RED})
    tools.flip(spr, "vertical")
    assert tools.read_pixels(spr)["rows"] == [".", "a"]


def test_mirror_completes_left_half(tmp_path):
    spr = str(tmp_path / "mirror.ase")
    tools.create_canvas(spr, 4, 2)
    tools.draw_grid(spr, rows=["r.", "rg"], legend={"r": RED, "g": GREEN})
    tools.mirror(spr, source="left")
    px = tools.read_pixels(spr)
    assert px["rows"] == ["a..a", "abba"]
    assert (px["legend"]["a"], px["legend"]["b"]) == (RED, GREEN)


def test_shift_drops_offcanvas_pixels(tmp_path):
    spr = str(tmp_path / "shift.ase")
    tools.create_canvas(spr, 2, 2)
    tools.draw_grid(spr, rows=["r.", ".g"], legend={"r": RED, "g": GREEN})
    tools.shift(spr, dx=1)
    assert tools.read_pixels(spr)["rows"] == [".a", ".."]
    with pytest.raises(AsepriteError, match="off the canvas"):
        tools.shift(spr, dx=2)


def test_shift_wraps_when_asked(tmp_path):
    spr = str(tmp_path / "shiftwrap.ase")
    tools.create_canvas(spr, 2, 2)
    tools.draw_grid(spr, rows=["r.", ".g"], legend={"r": RED, "g": GREEN})
    tools.shift(spr, dx=1, wrap=True)
    px = tools.read_pixels(spr)
    assert px["rows"] == [".a", "b."]
    assert px["legend"] == {".": "transparent", "a": RED, "b": GREEN}


def test_rotate_90_180_and_square_guard(tmp_path):
    spr = str(tmp_path / "rot.ase")
    tools.create_canvas(spr, 2, 2)
    tools.draw_grid(spr, rows=["rg", ".."], legend={"r": RED, "g": GREEN})
    tools.rotate(spr, 90)  # clockwise: top row becomes the right column
    assert tools.read_pixels(spr)["rows"] == [".a", ".b"]
    tools.rotate(spr, 270)  # undo
    tools.rotate(spr, 180)
    px = tools.read_pixels(spr)
    assert px["rows"] == ["..", "ab"]
    assert (px["legend"]["a"], px["legend"]["b"]) == (GREEN, RED)
    wide = str(tmp_path / "rotwide.ase")
    tools.create_canvas(wide, 4, 2)
    tools.draw_pixels(wide, [{"x": 0, "y": 0, "color": RED}])
    with pytest.raises(AsepriteError, match="square"):
        tools.rotate(wide, 90)


def test_replace_color_swaps_matches_in_region_and_reports_count(tmp_path):
    spr = str(tmp_path / "swap.ase")
    tools.create_canvas(spr, 4, 2)
    tools.draw_grid(spr, rows=["rrgg", "rrgg"], legend={"r": RED, "g": GREEN})
    msg = tools.replace_color(spr, RED, BLUE, x=0, y=0, width=2, height=1)
    assert "2 pixel(s)" in msg
    px = tools.read_pixels(spr)
    assert px["rows"] == ["aabb", "ccbb"]
    assert px["legend"]["a"] == BLUE
    assert px["legend"]["c"] == RED  # outside the rect untouched


def test_replace_color_zero_matches_notes_it(tmp_path):
    spr = str(tmp_path / "swap0.ase")
    tools.create_canvas(spr, 2, 1)
    tools.draw_pixels(spr, [{"x": 0, "y": 0, "color": RED}])
    msg = tools.replace_color(spr, GREEN, BLUE)
    assert "0 pixel(s)" in msg
    assert "not found" in msg


def test_replace_color_transparent_target_erases(tmp_path):
    spr = str(tmp_path / "swaperase.ase")
    tools.create_canvas(spr, 2, 1)
    tools.draw_grid(spr, rows=["rg"], legend={"r": RED, "g": GREEN})
    tools.replace_color(spr, RED, "#00000000")
    px = tools.read_pixels(spr)
    assert px["rows"] == [".a"]
    assert px["legend"]["a"] == GREEN


def test_replace_color_indexed_mode(tmp_path):
    spr = str(tmp_path / "swapix.ase")
    tools.create_canvas(spr, 2, 1, color_mode="indexed", palette="pico8")
    tools.draw_pixels(spr, [{"x": 0, "y": 0, "color": "#ff004d"}])
    tools.replace_color(spr, "#ff004d", "#29adff")
    px = tools.read_pixels(spr)
    assert px["legend"]["a"] == "#29adff"


def test_indexed_gameboy_palette(tmp_path):
    spr = str(tmp_path / "gb.ase")
    out = tmp_path / "gb.png"
    tools.create_canvas(spr, 4, 4, color_mode="indexed", palette="gameboy")
    info = tools.get_canvas_info(spr)
    assert info["color_mode"] == "indexed"
    assert info["palette"] == ["#0f380f", "#306230", "#8bac0f", "#9bbc0f"]
    tools.draw_pixels(spr, [{"x": 1, "y": 1, "color": "#8bac0f"}])
    tools.export(spr, str(out), format="png")
    img = _rgba(out)
    assert img.getpixel((1, 1)) == (0x8B, 0xAC, 0x0F, 255)
    assert img.getpixel((0, 0))[3] == 0  # index 0 is transparent on transparent layers


def test_set_palette(tmp_path):
    spr = str(tmp_path / "pal.ase")
    tools.create_canvas(spr, 4, 4)
    tools.set_palette(spr, ["#112233", "#445566"])
    assert tools.get_canvas_info(spr)["palette"] == ["#112233", "#445566"]


def test_indexed_offpalette_color_snap_is_reported(tmp_path):
    spr = str(tmp_path / "snap.ase")
    tools.create_canvas(spr, 4, 4, color_mode="indexed", palette="pico8")
    msg = tools.draw_pixels(spr, [{"x": 0, "y": 0, "color": "#123456"}])
    assert "snapped" in msg
    assert "#123456" in msg and "#1d2b53" in msg  # nearest pico8 entry


def test_indexed_exact_color_has_no_snap_note(tmp_path):
    spr = str(tmp_path / "nosnap.ase")
    tools.create_canvas(spr, 4, 4, color_mode="indexed", palette="pico8")
    msg = tools.draw_pixels(spr, [{"x": 0, "y": 0, "color": "#ff004d"}])
    assert "snapped" not in msg


def test_rgb_draw_has_no_snap_note(tmp_path):
    spr = str(tmp_path / "rgbnosnap.ase")
    tools.create_canvas(spr, 4, 4)
    msg = tools.draw_shape(spr, "line", [[0, 0], [1, 1]], "#123456")
    assert "snapped" not in msg


def test_set_palette_shrink_below_used_index_fails(tmp_path):
    spr = str(tmp_path / "shrink.ase")
    tools.create_canvas(spr, 4, 4, color_mode="indexed", palette="pico8")
    tools.draw_pixels(spr, [{"x": 0, "y": 0, "color": "#ff004d"}])  # pico8 index 8
    with pytest.raises(AsepriteError, match="palette index 8"):
        tools.set_palette(spr, ["#000000", "#ff0000"])
    assert len(tools.get_canvas_info(spr)["palette"]) == 16  # palette unchanged


def test_set_palette_shrink_covering_used_indices_ok(tmp_path):
    spr = str(tmp_path / "shrinkok.ase")
    tools.create_canvas(spr, 4, 4, color_mode="indexed", palette="pico8")
    tools.draw_pixels(spr, [{"x": 0, "y": 0, "color": "#1d2b53"}])  # pico8 index 1
    tools.set_palette(spr, ["#000000", "#1d2b53"])
    assert len(tools.get_canvas_info(spr)["palette"]) == 2


def test_add_layer_and_duplicate_name_fails(tmp_path):
    spr = str(tmp_path / "layers.ase")
    tools.create_canvas(spr, 4, 4)
    tools.add_layer(spr, "body")
    names = [l["name"] for l in tools.get_canvas_info(spr)["layers"]]
    assert "body" in names
    with pytest.raises(AsepriteError, match="already exists"):
        tools.add_layer(spr, "BODY")  # aseprite layer lookup is case-insensitive


def test_draw_on_named_layer_and_missing_layer_error(tmp_path):
    spr = str(tmp_path / "target.ase")
    out = tmp_path / "target.png"
    tools.create_canvas(spr, 4, 4)
    tools.add_layer(spr, "fx")
    tools.draw_pixels(spr, [{"x": 0, "y": 0, "color": RED}], layer="fx")
    tools.export(spr, str(out), format="png")
    assert _rgba(out).getpixel((0, 0)) == (255, 0, 0, 255)
    with pytest.raises(AsepriteError, match="fx"):
        tools.draw_pixels(spr, [{"x": 0, "y": 0, "color": RED}], layer="nope")


def test_add_frame_durations_and_gif_export(tmp_path):
    spr = str(tmp_path / "anim.ase")
    gif = tmp_path / "anim.gif"
    tools.create_canvas(spr, 4, 4)
    tools.draw_pixels(spr, [{"x": 0, "y": 0, "color": RED}])
    result = tools.add_frame(spr, duration_ms=80)
    assert result["frame"] == 2
    assert result["total_frames"] == 2
    info = tools.get_canvas_info(spr)
    assert [f["duration_ms"] for f in info["frames"]] == [100, 80]
    exported = tools.export(spr, str(gif), format="gif")
    assert exported["frames"] == 2
    assert gif.read_bytes()[:4] == b"GIF8"


def test_gif_export_notes_dropped_tag_direction(tmp_path):
    spr = str(tmp_path / "pp.ase")
    gif = tmp_path / "pp.gif"
    tools.create_canvas(spr, 4, 4)
    tools.draw_pixels(spr, [{"x": 0, "y": 0, "color": RED}])
    tools.add_frame(spr)
    tools.add_tag(spr, "bounce", 1, 2, direction="pingpong")
    result = tools.export(spr, str(gif), format="gif")
    assert "bounce" in result["note"]
    assert "pingpong" in result["note"]


def test_gif_export_forward_tags_need_no_note(tmp_path):
    spr = str(tmp_path / "fwd.ase")
    gif = tmp_path / "fwd.gif"
    tools.create_canvas(spr, 4, 4)
    tools.draw_pixels(spr, [{"x": 0, "y": 0, "color": RED}])
    tools.add_frame(spr)
    tools.add_tag(spr, "walk", 1, 2)
    result = tools.export(spr, str(gif), format="gif")
    assert "note" not in result


def test_set_frame_duration(tmp_path):
    spr = str(tmp_path / "dur.ase")
    tools.create_canvas(spr, 4, 4)
    tools.add_frame(spr, duration_ms=80)
    msg = tools.set_frame_duration(spr, frame=1, duration_ms=250)
    assert "250" in msg
    info = tools.get_canvas_info(spr)
    assert [f["duration_ms"] for f in info["frames"]] == [250, 80]
    with pytest.raises(AsepriteError, match="out of range"):
        tools.set_frame_duration(spr, frame=9, duration_ms=100)


def test_add_empty_frame_and_frame_targeted_drawing(tmp_path):
    spr = str(tmp_path / "empty.ase")
    tools.create_canvas(spr, 4, 4)
    tools.draw_pixels(spr, [{"x": 0, "y": 0, "color": RED}])
    tools.add_frame(spr, duration_ms=100, mode="empty")
    tools.draw_pixels(spr, [{"x": 1, "y": 1, "color": BLUE}], frame=2)
    img2 = PILImage.open(io.BytesIO(tools.preview(spr, scale=1, frame=2).data)).convert("RGBA")
    assert img2.getpixel((1, 1)) == (0, 0, 255, 255)
    assert img2.getpixel((0, 0))[3] == 0  # frame 2 started empty — no red from frame 1


def test_add_tag_named_animations_in_spritesheet(tmp_path):
    spr = str(tmp_path / "tagged.ase")
    out = tmp_path / "tagged.png"
    tools.create_canvas(spr, 8, 8)
    tools.draw_pixels(spr, [{"x": 0, "y": 0, "color": RED}])
    tools.add_frame(spr, duration_ms=120)
    tools.add_frame(spr, duration_ms=120)
    tools.add_tag(spr, "idle", 1, 1)
    tools.add_tag(spr, "walk", 2, 3, direction="pingpong")
    info = tools.get_canvas_info(spr)
    assert info["tags"] == [
        {"name": "idle", "from_frame": 1, "to_frame": 1, "direction": "forward"},
        {"name": "walk", "from_frame": 2, "to_frame": 3, "direction": "pingpong"},
    ]
    result = tools.export(spr, str(out), format="spritesheet")
    anims = {a["name"]: a for a in result["godot_metadata"]["animations"]}
    assert set(anims) == {"idle", "walk"}
    assert anims["idle"]["frames"] == [0]
    assert anims["walk"]["frames"] == [1, 2]
    assert anims["walk"]["direction"] == "pingpong"
    assert anims["walk"]["durations_ms"] == [120, 120]


def test_add_tag_out_of_range_and_duplicate_fail(tmp_path):
    spr = str(tmp_path / "tagbad.ase")
    tools.create_canvas(spr, 4, 4)
    with pytest.raises(AsepriteError, match="out of range"):
        tools.add_tag(spr, "walk", 1, 5)
    tools.add_tag(spr, "walk", 1, 1)
    with pytest.raises(AsepriteError, match="already exists"):
        tools.add_tag(spr, "walk", 1, 1)


def test_delete_tag_removes_only_the_tag(tmp_path):
    spr = str(tmp_path / "deltag.ase")
    tools.create_canvas(spr, 4, 4)
    tools.add_frame(spr)
    tools.add_tag(spr, "walk", 1, 2)
    tools.delete_tag(spr, "walk")
    info = tools.get_canvas_info(spr)
    assert info["tags"] == []
    assert len(info["frames"]) == 2  # frames untouched
    with pytest.raises(AsepriteError, match="tag not found"):
        tools.delete_tag(spr, "walk")


def test_delete_layer_and_last_layer_guard(tmp_path):
    spr = str(tmp_path / "dellayer.ase")
    tools.create_canvas(spr, 4, 4)
    tools.add_layer(spr, "fx")
    tools.draw_pixels(spr, [{"x": 0, "y": 0, "color": RED}], layer="fx")
    tools.delete_layer(spr, "fx")
    assert [l["name"] for l in tools.get_canvas_info(spr)["layers"]] == ["Layer 1"]
    assert tools.read_pixels(spr)["rows"] == ["....", "....", "....", "...."]
    with pytest.raises(AsepriteError, match="only layer"):
        tools.delete_layer(spr, "Layer 1")


def test_rename_layer_including_case_change(tmp_path):
    spr = str(tmp_path / "renlayer.ase")
    tools.create_canvas(spr, 4, 4)
    tools.add_layer(spr, "fx")
    tools.rename_layer(spr, "fx", "sparkles")
    names = [l["name"] for l in tools.get_canvas_info(spr)["layers"]]
    assert "sparkles" in names and "fx" not in names
    tools.rename_layer(spr, "sparkles", "Sparkles")  # case-only rename is fine
    assert "Sparkles" in [l["name"] for l in tools.get_canvas_info(spr)["layers"]]
    with pytest.raises(AsepriteError, match="already exists"):
        tools.rename_layer(spr, "Sparkles", "LAYER 1")


def test_pixels_survive_shape_then_pixel_edits(tmp_path):
    # regression guard for the cropped-cel gotcha: a shape creates a small cel,
    # later putPixels outside its bounds must still land
    spr = str(tmp_path / "crop.ase")
    out = tmp_path / "crop.png"
    tools.create_canvas(spr, 8, 8)
    tools.draw_shape(spr, "rectangle", [[3, 3], [4, 4]], GREEN, filled=True)
    tools.draw_pixels(spr, [{"x": 0, "y": 0, "color": RED}, {"x": 7, "y": 7, "color": BLUE}])
    tools.export(spr, str(out), format="png")
    img = _rgba(out)
    assert img.getpixel((0, 0)) == (255, 0, 0, 255)
    assert img.getpixel((7, 7)) == (0, 0, 255, 255)
    assert img.getpixel((3, 3)) == (0, 255, 0, 255)


def test_delete_frame_shifts_later_frames_down(tmp_path):
    spr = str(tmp_path / "del.ase")
    tools.create_canvas(spr, 4, 4)
    tools.draw_pixels(spr, [{"x": 0, "y": 0, "color": RED}])
    tools.add_frame(spr, duration_ms=80, mode="empty")
    tools.draw_pixels(spr, [{"x": 1, "y": 1, "color": BLUE}], frame=2)
    result = tools.delete_frame(spr, frame=1)
    assert result["total_frames"] == 1
    info = tools.get_canvas_info(spr)
    assert [f["duration_ms"] for f in info["frames"]] == [80]
    px = tools.read_pixels(spr)  # old frame 2 is now frame 1
    assert px["rows"] == ["....", ".a..", "....", "...."]
    assert px["legend"]["a"] == BLUE
    with pytest.raises(AsepriteError, match="only frame"):
        tools.delete_frame(spr, frame=1)


def test_delete_frame_out_of_range_fails(tmp_path):
    spr = str(tmp_path / "deloob.ase")
    tools.create_canvas(spr, 4, 4)
    tools.add_frame(spr)
    with pytest.raises(AsepriteError, match="out of range"):
        tools.delete_frame(spr, frame=5)


def test_copy_cel_copies_content_independently(tmp_path):
    spr = str(tmp_path / "copy.ase")
    tools.create_canvas(spr, 4, 4)
    tools.draw_pixels(spr, [{"x": 0, "y": 0, "color": RED}, {"x": 1, "y": 0, "color": GREEN}])
    tools.add_frame(spr, mode="empty")
    tools.copy_cel(spr, from_frame=1, to_frame=2)
    assert tools.read_pixels(spr, frame=2)["rows"][0] == "ab.."
    # deep copy: editing the target frame must not touch the source frame
    tools.draw_pixels(spr, [{"x": 3, "y": 3, "color": BLUE}], frame=2)
    assert tools.read_pixels(spr, frame=1)["rows"][3] == "...."


def test_copy_cel_overwrites_target_and_empty_source_fails(tmp_path):
    spr = str(tmp_path / "copyover.ase")
    tools.create_canvas(spr, 4, 4)
    tools.draw_pixels(spr, [{"x": 0, "y": 0, "color": RED}])
    tools.add_frame(spr)
    tools.draw_pixels(spr, [{"x": 2, "y": 2, "color": GREEN}], frame=2)
    tools.copy_cel(spr, from_frame=1, to_frame=2)  # replaces, not merges
    assert tools.read_pixels(spr, frame=2)["rows"] == ["a...", "....", "....", "...."]
    tools.add_layer(spr, "fx")
    with pytest.raises(AsepriteError, match="nothing to copy"):
        tools.copy_cel(spr, from_frame=1, to_frame=2, layer="fx")


def test_clear_region_erases_to_transparent(tmp_path):
    spr = str(tmp_path / "clear.ase")
    out = tmp_path / "clear.png"
    tools.create_canvas(spr, 8, 8)
    tools.draw_shape(spr, "rectangle", [[0, 0], [7, 7]], GREEN, filled=True)
    tools.clear_region(spr, x=2, y=2, width=3, height=3)
    tools.export(spr, str(out), format="png")
    img = _rgba(out)
    assert img.getpixel((2, 2))[3] == 0
    assert img.getpixel((4, 4))[3] == 0
    assert img.getpixel((1, 1)) == (0, 255, 0, 255)  # outside the region untouched
    assert img.getpixel((5, 5)) == (0, 255, 0, 255)


def test_clear_region_indexed_mode_restores_transparency(tmp_path):
    spr = str(tmp_path / "clearix.ase")
    out = tmp_path / "clearix.png"
    tools.create_canvas(spr, 4, 4, color_mode="indexed", palette="gameboy")
    tools.draw_shape(spr, "rectangle", [[0, 0], [3, 3]], "#8bac0f", filled=True)
    tools.clear_region(spr, x=0, y=0, width=2, height=2)
    tools.export(spr, str(out), format="png")
    img = _rgba(out)
    assert img.getpixel((0, 0))[3] == 0  # cleared back to the transparent index
    assert img.getpixel((3, 3)) == (0x8B, 0xAC, 0x0F, 255)


def test_clear_region_empty_layer_fails(tmp_path):
    spr = str(tmp_path / "clearempty.ase")
    tools.create_canvas(spr, 4, 4)
    tools.add_layer(spr, "fx")
    with pytest.raises(AsepriteError, match="nothing to clear"):
        tools.clear_region(spr, layer="fx")


def test_clear_region_past_canvas_fails(tmp_path):
    spr = str(tmp_path / "clearoob.ase")
    tools.create_canvas(spr, 4, 4)
    tools.draw_pixels(spr, [{"x": 0, "y": 0, "color": RED}])
    with pytest.raises(AsepriteError, match="canvas"):
        tools.clear_region(spr, x=2, y=0, width=4, height=1)


def test_spritesheet_export_with_godot_metadata(tmp_path):
    spr = str(tmp_path / "sheet.ase")
    out = tmp_path / "sheet.png"
    tools.create_canvas(spr, 8, 8)
    tools.draw_pixels(spr, [{"x": 0, "y": 0, "color": RED}])
    tools.add_frame(spr, duration_ms=120)
    tools.add_frame(spr, duration_ms=120)
    result = tools.export(spr, str(out), format="spritesheet", sheet_type="rows", columns=3)
    assert _rgba(out).size == (24, 8)
    meta = result["godot_metadata"]
    assert meta["frame_count"] == 3
    assert (meta["columns"], meta["rows"]) == (3, 1)
    assert [f["x"] for f in meta["frames"]] == [0, 8, 16]
    assert meta["animations"][0]["durations_ms"] == [100, 120, 120]
    assert Path(result["metadata_path"]).is_file()


def test_export_png_scaled_nearest_neighbor(tmp_path):
    spr = str(tmp_path / "scaled.ase")
    out = tmp_path / "scaled.png"
    tools.create_canvas(spr, 4, 4)
    tools.draw_pixels(spr, [{"x": 0, "y": 0, "color": RED}])
    result = tools.export(spr, str(out), format="png", scale=8)
    img = _rgba(out)
    assert img.size == (32, 32)
    for xy in [(0, 0), (7, 7)]:
        assert img.getpixel(xy) == (255, 0, 0, 255), xy  # crisp 8x8 block
    assert img.getpixel((8, 8))[3] == 0
    assert result["scale"] == 8
    assert tools.get_canvas_info(spr)["width"] == 4  # sprite file untouched


def test_export_spritesheet_scaled(tmp_path):
    spr = str(tmp_path / "scaledsheet.ase")
    out = tmp_path / "scaledsheet.png"
    tools.create_canvas(spr, 4, 4)
    tools.draw_pixels(spr, [{"x": 0, "y": 0, "color": RED}])
    tools.add_frame(spr)
    result = tools.export(spr, str(out), format="spritesheet", scale=2)
    assert _rgba(out).size == (16, 8)
    assert result["godot_metadata"]["frame_width"] == 8


def test_preview_is_nearest_neighbor_scaled(tmp_path):
    spr = str(tmp_path / "prev.ase")
    tools.create_canvas(spr, 4, 4)
    tools.draw_pixels(spr, [{"x": 0, "y": 0, "color": RED}])
    img_content = tools.preview(spr, scale=8)
    img = PILImage.open(io.BytesIO(img_content.data)).convert("RGBA")
    assert img.size == (32, 32)
    # the single red pixel becomes a crisp 8x8 block — no interpolation
    for xy in [(0, 0), (7, 7), (3, 4)]:
        assert img.getpixel(xy) == (255, 0, 0, 255), xy
    assert img.getpixel((8, 0))[3] == 0
    assert img.getpixel((0, 8))[3] == 0


def test_preview_contact_sheet_lays_frames_horizontally(tmp_path):
    spr = str(tmp_path / "sheetprev.ase")
    tools.create_canvas(spr, 4, 4)
    tools.draw_pixels(spr, [{"x": 0, "y": 0, "color": RED}])
    tools.add_frame(spr, mode="empty")
    tools.draw_pixels(spr, [{"x": 0, "y": 0, "color": BLUE}], frame=2)
    img = PILImage.open(
        io.BytesIO(tools.preview(spr, scale=2, all_frames=True).data)
    ).convert("RGBA")
    # 2 frames of 4px + a 1px gap, all at scale 2 -> (4+1+4)*2 x 4*2
    assert img.size == (18, 8)
    assert img.getpixel((0, 0)) == (255, 0, 0, 255)  # frame 1 tile
    assert img.getpixel((10, 0)) == (0, 0, 255, 255)  # frame 2 tile after the gap
    assert img.getpixel((8, 0))[3] == 0  # gap column stays transparent


def test_preview_all_frames_rejects_grid(tmp_path):
    spr = str(tmp_path / "sheetgrid.ase")
    tools.create_canvas(spr, 4, 4)
    tools.draw_pixels(spr, [{"x": 0, "y": 0, "color": RED}])
    with pytest.raises(ValueError, match="grid"):
        tools.preview(spr, grid=2, all_frames=True)


def test_corrupt_sprite_fails_loudly(tmp_path):
    bad = tmp_path / "corrupt.ase"
    bad.write_bytes(b"this is not an aseprite file")
    with pytest.raises(AsepriteError, match="could not open sprite"):
        tools.get_canvas_info(str(bad))


def test_out_of_bounds_pixel_fails(tmp_path):
    spr = str(tmp_path / "oob.ase")
    tools.create_canvas(spr, 4, 4)
    with pytest.raises(AsepriteError, match="out of bounds"):
        tools.draw_pixels(spr, [{"x": 10, "y": 0, "color": RED}])


def test_read_pixels_legend_grid(tmp_path):
    spr = str(tmp_path / "read.ase")
    tools.create_canvas(spr, 4, 4)
    tools.draw_pixels(
        spr,
        [
            {"x": 0, "y": 0, "color": RED},
            {"x": 1, "y": 0, "color": RED},
            {"x": 3, "y": 3, "color": "#0000ff80"},
        ],
    )
    result = tools.read_pixels(spr)
    assert (result["x"], result["y"]) == (0, 0)
    assert (result["width"], result["height"]) == (4, 4)
    assert result["legend"]["."] == "transparent"
    assert result["legend"]["a"] == "#ff0000"  # scan order: 'a' is first color seen
    assert result["legend"]["b"] == "#0000ff80"  # alpha preserved in legend hex
    assert result["rows"] == ["aa..", "....", "....", "...b"]


def test_read_pixels_subregion_and_indexed_palette(tmp_path):
    spr = str(tmp_path / "readix.ase")
    tools.create_canvas(spr, 4, 4, color_mode="indexed", palette="gameboy")
    tools.draw_pixels(spr, [{"x": 1, "y": 1, "color": "#8bac0f"}])
    result = tools.read_pixels(spr, x=1, y=1, width=2, height=1)
    assert result["rows"] == ["a."]
    assert result["legend"]["a"] == "#8bac0f"


def test_read_pixels_isolates_a_layer(tmp_path):
    spr = str(tmp_path / "iso.ase")
    tools.create_canvas(spr, 2, 1)
    tools.draw_pixels(spr, [{"x": 0, "y": 0, "color": RED}])
    tools.add_layer(spr, "fx")
    tools.draw_pixels(spr, [{"x": 1, "y": 0, "color": BLUE}], layer="fx")
    assert tools.read_pixels(spr)["rows"] == ["ab"]  # composite by default
    fx = tools.read_pixels(spr, layer="fx")
    assert fx["rows"] == [".a"]
    assert fx["legend"]["a"] == BLUE
    assert fx["layer"] == "fx"


def test_read_pixels_empty_layer_reads_transparent(tmp_path):
    spr = str(tmp_path / "isoempty.ase")
    tools.create_canvas(spr, 2, 1)
    tools.draw_pixels(spr, [{"x": 0, "y": 0, "color": RED}])
    tools.add_layer(spr, "fx")
    assert tools.read_pixels(spr, layer="fx")["rows"] == [".."]


def test_read_pixels_oversize_region_fails(tmp_path):
    spr = str(tmp_path / "big.ase")
    tools.create_canvas(spr, 65, 65)
    with pytest.raises(AsepriteError, match="4096"):
        tools.read_pixels(spr)


def test_read_pixels_rect_past_canvas_fails(tmp_path):
    spr = str(tmp_path / "oobr.ase")
    tools.create_canvas(spr, 4, 4)
    with pytest.raises(AsepriteError, match="canvas"):
        tools.read_pixels(spr, x=2, y=0, width=4, height=1)


def test_preview_grid_overlay_lines(tmp_path):
    spr = str(tmp_path / "grid.ase")
    tools.create_canvas(spr, 4, 4)
    tools.draw_pixels(spr, [{"x": 0, "y": 0, "color": RED}])
    img = PILImage.open(io.BytesIO(tools.preview(spr, scale=8, grid=2).data)).convert("RGBA")
    assert img.size == (32, 32)
    magenta = (255, 0, 255, 255)
    assert img.getpixel((16, 3)) == magenta  # vertical line every grid*scale px
    assert img.getpixel((3, 16)) == magenta  # horizontal line
    assert img.getpixel((8, 3)) != magenta  # grid=2: no line between boundaries
    assert img.getpixel((0, 0)) == (255, 0, 0, 255)  # art preserved off the lines
    assert img.getpixel((0, 20))[3] == 0  # no line drawn along the x=0 edge


def test_preview_grid_on_indexed_sprite(tmp_path):
    # magenta lines must appear even when the palette has no magenta
    spr = str(tmp_path / "gridix.ase")
    tools.create_canvas(spr, 4, 4, color_mode="indexed", palette="gameboy")
    tools.draw_pixels(spr, [{"x": 0, "y": 0, "color": "#8bac0f"}])
    img = PILImage.open(io.BytesIO(tools.preview(spr, scale=8, grid=1).data)).convert("RGBA")
    assert img.getpixel((8, 2)) == (255, 0, 255, 255)
    assert img.getpixel((2, 2)) == (0x8B, 0xAC, 0x0F, 255)  # art color untouched
