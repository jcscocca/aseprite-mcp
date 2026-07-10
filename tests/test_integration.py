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


def test_add_empty_frame_and_frame_targeted_drawing(tmp_path):
    spr = str(tmp_path / "empty.ase")
    tools.create_canvas(spr, 4, 4)
    tools.draw_pixels(spr, [{"x": 0, "y": 0, "color": RED}])
    tools.add_frame(spr, duration_ms=100, mode="empty")
    tools.draw_pixels(spr, [{"x": 1, "y": 1, "color": BLUE}], frame=2)
    img2 = PILImage.open(io.BytesIO(tools.preview(spr, scale=1, frame=2).data)).convert("RGBA")
    assert img2.getpixel((1, 1)) == (0, 0, 255, 255)
    assert img2.getpixel((0, 0))[3] == 0  # frame 2 started empty — no red from frame 1


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
