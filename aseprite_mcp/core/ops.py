"""Fail-loudly validation of drawing ops before any Lua is generated.

Every validator raises ValueError with a message an LLM agent can act on:
it names the bad value and lists the valid options.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .palettes import PRESETS

SPRITE_SUFFIXES = (".ase", ".aseprite")
COLOR_MODES = {
    "rgb": "ColorMode.RGB",
    "grayscale": "ColorMode.GRAYSCALE",
    "indexed": "ColorMode.INDEXED",
}
SHAPES = ("line", "rectangle", "ellipse", "fill")
EXPORT_FORMATS = ("png", "gif", "spritesheet")
SHEET_TYPES = ("rows", "columns", "horizontal", "vertical", "packed")
MAX_CANVAS = 65535
MAX_DURATION_MS = 65535
MAX_SCALE = 64
MAX_PADDING = 64


@dataclass(frozen=True)
class RGBA:
    r: int
    g: int
    b: int
    a: int = 255

    def hex(self) -> str:
        base = f"#{self.r:02x}{self.g:02x}{self.b:02x}"
        return base if self.a == 255 else base + f"{self.a:02x}"


@dataclass(frozen=True)
class Pixel:
    x: int
    y: int
    color: RGBA


@dataclass(frozen=True)
class ShapeOp:
    tool: str
    points: list[tuple[int, int]]
    color: RGBA
    tolerance: int = 0


def _int(value, what: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{what} must be an integer, got {value!r}")
    if not minimum <= value <= maximum:
        raise ValueError(f"{what} must be in {minimum}..{maximum}, got {value}")
    return value


def parse_color(value) -> RGBA:
    if not isinstance(value, str) or not value.startswith("#"):
        raise ValueError(
            f"invalid color {value!r}: expected a hex string '#RGB', '#RRGGBB' or '#RRGGBBAA'"
        )
    digits = value[1:]
    if len(digits) == 3:
        digits = "".join(c * 2 for c in digits)
    if len(digits) not in (6, 8):
        raise ValueError(
            f"invalid color {value!r}: expected a hex string '#RGB', '#RRGGBB' or '#RRGGBBAA'"
        )
    try:
        raw = bytes.fromhex(digits)
    except ValueError:
        raise ValueError(f"invalid color {value!r}: non-hex digits") from None
    r, g, b = raw[0], raw[1], raw[2]
    a = raw[3] if len(raw) == 4 else 255
    return RGBA(r, g, b, a)


def validate_sprite_path(path, *, must_exist: bool) -> Path:
    if not isinstance(path, str) or not path:
        raise ValueError(f"path must be a non-empty string, got {path!r}")
    p = Path(path).expanduser()
    if p.suffix.lower() not in SPRITE_SUFFIXES:
        raise ValueError(
            f"sprite path {path!r} must end with .ase or .aseprite "
            "(this server only edits Aseprite files)"
        )
    if must_exist:
        if not p.is_file():
            raise ValueError(f"sprite file does not exist: {p}")
    elif not p.parent.is_dir():
        raise ValueError(f"directory does not exist for new sprite: {p.parent}")
    return p


def validate_out_path(path, format: str) -> Path:
    if not isinstance(path, str) or not path:
        raise ValueError(f"out path must be a non-empty string, got {path!r}")
    p = Path(path).expanduser()
    expected = ".png" if format in ("png", "spritesheet") else ".gif"
    if p.suffix.lower() != expected:
        raise ValueError(
            f"out path {path!r} must end with {expected} for format={format!r}"
        )
    if not p.parent.is_dir():
        raise ValueError(f"directory does not exist for export: {p.parent}")
    return p


def validate_canvas_size(width, height) -> tuple[int, int]:
    return (
        _int(width, "canvas width", 1, MAX_CANVAS),
        _int(height, "canvas height", 1, MAX_CANVAS),
    )


def validate_color_mode(mode) -> str:
    if mode not in COLOR_MODES:
        raise ValueError(
            f"unknown color_mode {mode!r}: expected one of 'rgb', 'grayscale', 'indexed'"
        )
    return COLOR_MODES[mode]


def _point(value, what: str) -> tuple[int, int]:
    if isinstance(value, dict) and set(value) >= {"x", "y"}:
        x, y = value["x"], value["y"]
    elif isinstance(value, (list, tuple)) and len(value) == 2:
        x, y = value
    else:
        raise ValueError(f"{what} must be {{'x': int, 'y': int}} or [x, y], got {value!r}")
    return (_int(x, f"{what}.x", 0, MAX_CANVAS), _int(y, f"{what}.y", 0, MAX_CANVAS))


def validate_pixels(pixels) -> list[Pixel]:
    if not isinstance(pixels, list) or not pixels:
        raise ValueError(
            "pixels must be a list with at least one {'x': int, 'y': int, 'color': '#hex'} entry"
        )
    out: list[Pixel] = []
    for i, item in enumerate(pixels):
        what = f"pixels[{i}]"
        if not isinstance(item, dict):
            raise ValueError(f"{what} must be a dict with x, y, color; got {item!r}")
        missing = {"x", "y", "color"} - set(item)
        if missing:
            raise ValueError(f"{what} is missing keys: {sorted(missing)}")
        try:
            x, y = _point(item, what)
            color = parse_color(item["color"])
        except ValueError as e:
            raise ValueError(f"{what}: {e}") from None
        out.append(Pixel(x, y, color))
    return out


def validate_shape(shape, points, color, *, filled: bool, tolerance: int) -> ShapeOp:
    if shape not in SHAPES:
        raise ValueError(
            f"unknown shape {shape!r}: expected one of 'line', 'rectangle', 'ellipse', 'fill'"
        )
    rgba = parse_color(color)
    expected_points = 1 if shape == "fill" else 2
    if not isinstance(points, list) or len(points) != expected_points:
        raise ValueError(
            f"shape {shape!r} needs exactly {expected_points} "
            f"point{'s' if expected_points > 1 else ''}, got {points!r}"
        )
    pts = [_point(p, f"points[{i}]") for i, p in enumerate(points)]
    if filled and shape not in ("rectangle", "ellipse"):
        raise ValueError(f"filled=True is only valid for 'rectangle' and 'ellipse', not {shape!r}")
    if shape == "fill":
        tolerance = _int(tolerance, "tolerance", 0, 255)
    elif tolerance != 0:
        raise ValueError(f"tolerance is only valid for shape='fill', not {shape!r}")
    tools = {
        "line": "line",
        "rectangle": "filled_rectangle" if filled else "rectangle",
        "ellipse": "filled_ellipse" if filled else "ellipse",
        "fill": "paint_bucket",
    }
    return ShapeOp(tool=tools[shape], points=pts, color=rgba, tolerance=tolerance)


def validate_layer_name(name) -> str:
    if not isinstance(name, str) or not name.strip() or any(c in name for c in "\r\n"):
        raise ValueError(
            f"layer name must be a non-empty single-line string, got {name!r}"
        )
    return name.strip()


def validate_frame(frame) -> int:
    return _int(frame, "frame (1-based)", 1, 65535)


def validate_duration_ms(ms) -> int:
    return _int(ms, "duration_ms", 1, MAX_DURATION_MS)


def validate_scale(scale) -> int:
    return _int(scale, "scale", 1, MAX_SCALE)


def resolve_palette(palette) -> list[RGBA] | None:
    if palette is None:
        return None
    if isinstance(palette, str):
        if palette not in PRESETS:
            raise ValueError(
                f"unknown palette preset {palette!r}: available presets are "
                + ", ".join(sorted(PRESETS))
                + " — or pass an explicit list of hex colors"
            )
        palette = PRESETS[palette]
    if not isinstance(palette, list):
        raise ValueError(
            f"palette must be a preset name or a list of hex colors, got {palette!r}"
        )
    if not 1 <= len(palette) <= 256:
        raise ValueError(f"palette must have 1..256 colors, got {len(palette)}")
    return [parse_color(c) for c in palette]


def validate_export_format(format) -> str:
    if format not in EXPORT_FORMATS:
        raise ValueError(
            f"unknown export format {format!r}: expected 'png', 'gif' or 'spritesheet'"
        )
    return format


def validate_sheet_type(sheet_type) -> str:
    if sheet_type not in SHEET_TYPES:
        raise ValueError(
            f"unknown sheet_type {sheet_type!r}: expected one of "
            "'rows', 'columns', 'horizontal', 'vertical', 'packed'"
        )
    return sheet_type


def validate_columns(columns) -> int:
    return _int(columns, "columns (0 = auto)", 0, 1024)


def validate_padding(padding) -> int:
    return _int(padding, "padding", 0, MAX_PADDING)
