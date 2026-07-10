"""Unit tests for op validation — no Aseprite binary needed."""

from __future__ import annotations

import pytest

from aseprite_mcp.core import ops
from aseprite_mcp.core.palettes import PRESETS


# --- parse_color ---


def test_parse_color_rrggbb():
    assert ops.parse_color("#22C55E") == ops.RGBA(0x22, 0xC5, 0x5E, 255)


def test_parse_color_rrggbbaa():
    assert ops.parse_color("#ff000080") == ops.RGBA(255, 0, 0, 0x80)


def test_parse_color_short_rgb():
    assert ops.parse_color("#f0a") == ops.RGBA(0xFF, 0x00, 0xAA, 255)


@pytest.mark.parametrize("bad", ["ff0000", "#ff00", "#gggggg", "", "#ff00001", "red", 123, None])
def test_parse_color_invalid_fails_loudly(bad):
    with pytest.raises(ValueError, match="color"):
        ops.parse_color(bad)


def test_rgba_hex_roundtrip():
    assert ops.parse_color("#1a2b3c").hex() == "#1a2b3c"
    assert ops.parse_color("#1a2b3c80").hex() == "#1a2b3c80"


# --- sprite paths ---


def test_sprite_path_requires_ase_suffix(tmp_path):
    with pytest.raises(ValueError, match=r"\.ase"):
        ops.validate_sprite_path(str(tmp_path / "sprite.png"), must_exist=False)


def test_sprite_path_missing_file_fails(tmp_path):
    with pytest.raises(ValueError, match="does not exist"):
        ops.validate_sprite_path(str(tmp_path / "nope.ase"), must_exist=True)


def test_sprite_path_ok(tmp_path):
    p = tmp_path / "s.aseprite"
    p.touch()
    assert ops.validate_sprite_path(str(p), must_exist=True) == p


def test_new_sprite_path_parent_must_exist(tmp_path):
    with pytest.raises(ValueError, match="directory"):
        ops.validate_sprite_path(str(tmp_path / "missing" / "s.ase"), must_exist=False)


# --- canvas ---


@pytest.mark.parametrize("w,h", [(0, 16), (16, 0), (-1, 5), (16, 70000)])
def test_canvas_size_out_of_range(w, h):
    with pytest.raises(ValueError, match="[Cc]anvas"):
        ops.validate_canvas_size(w, h)


def test_canvas_size_ok():
    assert ops.validate_canvas_size(16, 32) == (16, 32)


def test_color_mode_maps_to_lua_enum():
    assert ops.validate_color_mode("rgb") == "ColorMode.RGB"
    assert ops.validate_color_mode("indexed") == "ColorMode.INDEXED"
    assert ops.validate_color_mode("grayscale") == "ColorMode.GRAYSCALE"


def test_color_mode_invalid_lists_options():
    with pytest.raises(ValueError, match="rgb.*grayscale.*indexed"):
        ops.validate_color_mode("cmyk")


# --- pixels ---


def test_validate_pixels_ok():
    px = ops.validate_pixels([{"x": 0, "y": 1, "color": "#fff"}])
    assert px == [ops.Pixel(0, 1, ops.RGBA(255, 255, 255, 255))]


def test_validate_pixels_empty_fails():
    with pytest.raises(ValueError, match="at least one"):
        ops.validate_pixels([])


@pytest.mark.parametrize(
    "bad",
    [
        [{"x": -1, "y": 0, "color": "#fff"}],
        [{"x": 0, "y": "2", "color": "#fff"}],
        [{"y": 0, "color": "#fff"}],
        [{"x": 0, "y": 0}],
        ["not-a-dict"],
    ],
)
def test_validate_pixels_bad_entries_name_the_index(bad):
    with pytest.raises(ValueError, match=r"pixels\[0\]"):
        ops.validate_pixels(bad)


# --- shapes ---


def test_line_shape():
    op = ops.validate_shape("line", [{"x": 0, "y": 0}, [3, 4]], "#f00", filled=False, tolerance=0)
    assert op.tool == "line"
    assert op.points == [(0, 0), (3, 4)]


def test_filled_rectangle_and_ellipse_tools():
    r = ops.validate_shape("rectangle", [[0, 0], [5, 5]], "#f00", filled=True, tolerance=0)
    e = ops.validate_shape("ellipse", [[0, 0], [5, 5]], "#f00", filled=False, tolerance=0)
    assert r.tool == "filled_rectangle"
    assert e.tool == "ellipse"


def test_fill_shape_takes_one_point_and_tolerance():
    op = ops.validate_shape("fill", [[2, 3]], "#0f0", filled=False, tolerance=30)
    assert op.tool == "paint_bucket"
    assert op.tolerance == 30


def test_shape_wrong_point_count():
    with pytest.raises(ValueError, match="exactly 2 points"):
        ops.validate_shape("line", [[0, 0]], "#f00", filled=False, tolerance=0)
    with pytest.raises(ValueError, match="exactly 1 point"):
        ops.validate_shape("fill", [[0, 0], [1, 1]], "#f00", filled=False, tolerance=0)


def test_shape_invalid_kind_lists_options():
    with pytest.raises(ValueError, match="line.*rectangle.*ellipse.*fill"):
        ops.validate_shape("triangle", [[0, 0]], "#f00", filled=False, tolerance=0)


def test_tolerance_only_for_fill():
    with pytest.raises(ValueError, match="tolerance"):
        ops.validate_shape("line", [[0, 0], [1, 1]], "#f00", filled=False, tolerance=5)
    with pytest.raises(ValueError, match="tolerance"):
        ops.validate_shape("fill", [[0, 0]], "#f00", filled=False, tolerance=300)


def test_filled_only_for_rect_ellipse():
    with pytest.raises(ValueError, match="filled"):
        ops.validate_shape("line", [[0, 0], [1, 1]], "#f00", filled=True, tolerance=0)


def test_shape_rejects_fully_transparent_color():
    with pytest.raises(ValueError, match="clear_region"):
        ops.validate_shape("rectangle", [[0, 0], [3, 3]], "#00000000", filled=True, tolerance=0)


def test_shape_allows_partial_alpha():
    op = ops.validate_shape("line", [[0, 0], [1, 1]], "#ff000080", filled=False, tolerance=0)
    assert op.color.a == 0x80


# --- draw grid ---


def test_grid_pixels_maps_legend_chars_with_offset():
    px = ops.validate_grid_pixels(["r.", ".b"], {"r": "#f00", "b": "#00f"}, 1, 2)
    assert px == [
        ops.Pixel(1, 2, ops.RGBA(255, 0, 0, 255)),
        ops.Pixel(2, 3, ops.RGBA(0, 0, 255, 255)),
    ]


def test_grid_pixels_space_and_dot_are_skipped():
    px = ops.validate_grid_pixels(["r r", "..."], {"r": "#f00"}, 0, 0)
    assert [(p.x, p.y) for p in px] == [(0, 0), (2, 0)]


def test_grid_pixels_ragged_rows_fail():
    with pytest.raises(ValueError, match=r"rows\[1\]"):
        ops.validate_grid_pixels(["ab", "a"], {"a": "#000", "b": "#fff"}, 0, 0)


def test_grid_pixels_unknown_char_names_cell():
    with pytest.raises(ValueError, match=r"rows\[0\]\[1\]"):
        ops.validate_grid_pixels(["ax"], {"a": "#000"}, 0, 0)


def test_grid_pixels_legend_keys_must_be_single_paintable_chars():
    with pytest.raises(ValueError, match="legend"):
        ops.validate_grid_pixels(["a"], {"aa": "#000"}, 0, 0)
    with pytest.raises(ValueError, match="legend"):
        ops.validate_grid_pixels(["a"], {".": "#000", "a": "#fff"}, 0, 0)


def test_grid_pixels_legend_color_errors_name_the_key():
    with pytest.raises(ValueError, match=r"legend\['a'\]"):
        ops.validate_grid_pixels(["a"], {"a": "nope"}, 0, 0)


def test_grid_pixels_all_blank_fails():
    with pytest.raises(ValueError, match="no painted cells"):
        ops.validate_grid_pixels(["..", "  "], {"a": "#000"}, 0, 0)


def test_grid_pixels_empty_rows_fail():
    with pytest.raises(ValueError, match="rows"):
        ops.validate_grid_pixels([], {"a": "#000"}, 0, 0)
    with pytest.raises(ValueError, match="rows"):
        ops.validate_grid_pixels([""], {"a": "#000"}, 0, 0)


# --- replace color ---


def test_replace_colors_parse_and_differ():
    f, t = ops.validate_replace_colors("#ff0000", "#00ff00")
    assert (f, t) == (ops.RGBA(255, 0, 0, 255), ops.RGBA(0, 255, 0, 255))
    with pytest.raises(ValueError, match="differ"):
        ops.validate_replace_colors("#ff0000", "#f00")


# --- layers / frames / durations / scale ---


def test_layer_name_rules():
    assert ops.validate_layer_name("  body ") == "body"
    with pytest.raises(ValueError, match="layer name"):
        ops.validate_layer_name("")
    with pytest.raises(ValueError, match="layer name"):
        ops.validate_layer_name("a\nb")


def test_frame_must_be_positive_int():
    assert ops.validate_frame(3) == 3
    with pytest.raises(ValueError, match="frame"):
        ops.validate_frame(0)
    with pytest.raises(ValueError, match="frame"):
        ops.validate_frame("2")


def test_duration_range():
    assert ops.validate_duration_ms(100) == 100
    for bad in (0, -5, 70000, 12.5):
        with pytest.raises(ValueError, match="duration"):
            ops.validate_duration_ms(bad)


def test_scale_range():
    assert ops.validate_scale(8) == 8
    for bad in (0, 65, "8"):
        with pytest.raises(ValueError, match="scale"):
            ops.validate_scale(bad)


# --- tags ---


def test_tag_name_rules():
    assert ops.validate_tag_name("  walk ") == "walk"
    with pytest.raises(ValueError, match="tag name"):
        ops.validate_tag_name("")
    with pytest.raises(ValueError, match="tag name"):
        ops.validate_tag_name("a\nb")


def test_tag_direction_maps_to_anidir():
    assert ops.validate_tag_direction("forward") == "AniDir.FORWARD"
    assert ops.validate_tag_direction("reverse") == "AniDir.REVERSE"
    assert ops.validate_tag_direction("pingpong") == "AniDir.PING_PONG"
    assert ops.validate_tag_direction("pingpong_reverse") == "AniDir.PING_PONG_REVERSE"


def test_tag_direction_invalid_lists_options():
    with pytest.raises(ValueError, match="forward.*reverse.*pingpong"):
        ops.validate_tag_direction("bounce")


def test_tag_range():
    assert ops.validate_tag_range(1, 4) == (1, 4)
    assert ops.validate_tag_range(2, 2) == (2, 2)
    with pytest.raises(ValueError, match="from_frame"):
        ops.validate_tag_range(4, 1)
    with pytest.raises(ValueError, match="1-based"):
        ops.validate_tag_range(0, 2)


def test_copy_frames_must_differ():
    assert ops.validate_copy_frames(1, 3) == (1, 3)
    assert ops.validate_copy_frames(3, 1) == (3, 1)  # copying backward is fine
    with pytest.raises(ValueError, match="differ"):
        ops.validate_copy_frames(2, 2)
    with pytest.raises(ValueError, match="1-based"):
        ops.validate_copy_frames(0, 1)


# --- palettes ---


def test_resolve_palette_preset():
    colors = ops.resolve_palette("gameboy")
    assert len(colors) == 4
    assert all(isinstance(c, ops.RGBA) for c in colors)


def test_resolve_palette_hex_list():
    assert ops.resolve_palette(["#000", "#fff"]) == [ops.RGBA(0, 0, 0, 255), ops.RGBA(255, 255, 255, 255)]


def test_resolve_palette_none():
    assert ops.resolve_palette(None) is None


def test_resolve_palette_unknown_preset_lists_presets():
    with pytest.raises(ValueError, match="gameboy"):
        ops.resolve_palette("vga")


def test_palette_size_limits():
    with pytest.raises(ValueError, match="1..256"):
        ops.resolve_palette([])
    with pytest.raises(ValueError, match="1..256"):
        ops.resolve_palette(["#000"] * 257)


def test_presets_are_valid_hex():
    for name, colors in PRESETS.items():
        resolved = ops.resolve_palette(name)
        assert 1 <= len(resolved) <= 256, name


# --- export options ---


def test_export_format_set():
    assert ops.validate_export_format("gif") == "gif"
    with pytest.raises(ValueError, match="png.*gif.*spritesheet"):
        ops.validate_export_format("bmp")


def test_sheet_type_set():
    assert ops.validate_sheet_type("rows") == "rows"
    with pytest.raises(ValueError, match="horizontal"):
        ops.validate_sheet_type("grid")


def test_out_path_suffix_must_match_format(tmp_path):
    with pytest.raises(ValueError, match=r"\.png"):
        ops.validate_out_path(str(tmp_path / "x.gif"), "spritesheet")
    with pytest.raises(ValueError, match=r"\.gif"):
        ops.validate_out_path(str(tmp_path / "x.png"), "gif")
    p = ops.validate_out_path(str(tmp_path / "x.png"), "png")
    assert p.suffix == ".png"


def test_columns_and_padding_ranges():
    assert ops.validate_columns(0) == 0
    assert ops.validate_padding(4) == 4
    with pytest.raises(ValueError, match="columns"):
        ops.validate_columns(-1)
    with pytest.raises(ValueError, match="padding"):
        ops.validate_padding(65)


# --- read_pixels rect ---


def test_read_rect_zero_means_full_canvas():
    assert ops.validate_read_rect(0, 0, 0, 0) == (0, 0, 0, 0)


def test_read_rect_explicit():
    assert ops.validate_read_rect(2, 3, 10, 4) == (2, 3, 10, 4)


def test_read_rect_negative_origin_fails():
    with pytest.raises(ValueError, match="x"):
        ops.validate_read_rect(-1, 0, 4, 4)


def test_read_rect_area_cap():
    with pytest.raises(ValueError, match="4096"):
        ops.validate_read_rect(0, 0, 65, 64)


def test_clear_rect_explicit_and_zero_to_edge():
    assert ops.validate_clear_rect(2, 3, 10, 4) == (2, 3, 10, 4)
    assert ops.validate_clear_rect(0, 0, 0, 0) == (0, 0, 0, 0)


def test_clear_rect_has_no_area_cap():
    assert ops.validate_clear_rect(0, 0, 500, 500) == (0, 0, 500, 500)


def test_clear_rect_negative_origin_fails():
    with pytest.raises(ValueError, match="x"):
        ops.validate_clear_rect(-1, 0, 4, 4)


def test_grid_zero_is_off_and_range_enforced():
    assert ops.validate_grid(0) == 0
    assert ops.validate_grid(8) == 8
    with pytest.raises(ValueError, match="grid"):
        ops.validate_grid(-1)
