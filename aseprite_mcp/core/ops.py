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
MAX_READ_AREA = 4096


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


MAX_IMPORT_SIDE = 1024
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def validate_import_source(source) -> tuple[Path, int, int]:
    """Validate a PNG to import; return (path, width, height) from its header."""
    if not isinstance(source, str) or not source:
        raise ValueError(f"source must be a non-empty string, got {source!r}")
    p = Path(source).expanduser()
    if p.suffix.lower() != ".png":
        raise ValueError(
            f"source {source!r} must be a .png file — only PNG import is "
            "supported (convert other formats to PNG first)"
        )
    if not p.is_file():
        raise ValueError(f"source image does not exist: {p}")
    with p.open("rb") as f:
        header = f.read(24)
    if len(header) < 24 or not header.startswith(_PNG_SIGNATURE) or header[12:16] != b"IHDR":
        raise ValueError(f"{p} is not a valid PNG file (bad PNG signature)")
    width = int.from_bytes(header[16:20], "big")
    height = int.from_bytes(header[20:24], "big")
    if width > MAX_IMPORT_SIDE or height > MAX_IMPORT_SIDE:
        raise ValueError(
            f"source PNG is {width}x{height} — this server is for pixel art, "
            f"so each side must be at or under {MAX_IMPORT_SIDE}px; downscale "
            "the image first"
        )
    return (p, width, height)


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
    if rgba.a == 0:
        raise ValueError(
            f"color {color!r} is fully transparent — draw_shape cannot erase: "
            "use clear_region for rectangles, or draw_pixels with '#00000000' "
            "for individual pixels"
        )
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


FLIP_DIRECTIONS = {
    "horizontal": "FlipType.HORIZONTAL",
    "vertical": "FlipType.VERTICAL",
}
MIRROR_SOURCES = ("left", "right", "top", "bottom")
ROTATIONS = (90, 180, 270)


def validate_flip_direction(direction) -> str:
    if direction not in FLIP_DIRECTIONS:
        raise ValueError(
            f"unknown direction {direction!r}: expected 'horizontal' or 'vertical'"
        )
    return FLIP_DIRECTIONS[direction]


def validate_mirror_source(source) -> str:
    if source not in MIRROR_SOURCES:
        raise ValueError(
            f"unknown source {source!r}: expected one of 'left', 'right', 'top', 'bottom'"
        )
    return source


def validate_shift(dx, dy) -> tuple[int, int]:
    x = _int(dx, "dx", -MAX_CANVAS, MAX_CANVAS)
    y = _int(dy, "dy", -MAX_CANVAS, MAX_CANVAS)
    if x == 0 and y == 0:
        raise ValueError("dx and dy are both 0 — nothing to shift")
    return (x, y)


def validate_rotation(degrees) -> int:
    if isinstance(degrees, bool) or degrees not in ROTATIONS:
        raise ValueError(f"rotation must be 90, 180 or 270 degrees, got {degrees!r}")
    return degrees


def validate_replace_colors(from_color, to_color) -> tuple[RGBA, RGBA]:
    f = parse_color(from_color)
    t = parse_color(to_color)
    if f == t:
        raise ValueError(
            f"from_color and to_color are both {f.hex()!r} — they must differ"
        )
    return (f, t)


GRID_SKIP_CHARS = ". "


def validate_grid_pixels(rows, legend, x, y) -> list[Pixel]:
    ox = _int(x, "x", 0, MAX_CANVAS)
    oy = _int(y, "y", 0, MAX_CANVAS)
    if not isinstance(rows, list) or not rows or not all(isinstance(r, str) for r in rows):
        raise ValueError("rows must be a non-empty list of strings, one string per pixel row")
    width = len(rows[0])
    if width < 1:
        raise ValueError("rows must be non-empty strings, one character per pixel")
    for i, row in enumerate(rows):
        if len(row) != width:
            raise ValueError(
                f"rows[{i}] is {len(row)} character(s) wide, expected {width} — "
                "all rows must have equal width"
            )
    if not isinstance(legend, dict) or not legend:
        raise ValueError(
            "legend must be a dict mapping single characters to hex colors, "
            "e.g. {'r': '#ff0000'}"
        )
    colors: dict[str, RGBA] = {}
    for key, value in legend.items():
        if not isinstance(key, str) or len(key) != 1 or key in GRID_SKIP_CHARS:
            raise ValueError(
                f"legend key {key!r} must be a single character other than "
                "'.' and ' ' (those mean skip)"
            )
        try:
            colors[key] = parse_color(value)
        except ValueError as e:
            raise ValueError(f"legend[{key!r}]: {e}") from None
    out: list[Pixel] = []
    for gy, row in enumerate(rows):
        for gx, ch in enumerate(row):
            if ch in GRID_SKIP_CHARS:
                continue
            color = colors.get(ch)
            if color is None:
                keys = ", ".join(sorted(colors))
                raise ValueError(
                    f"rows[{gy}][{gx}] is {ch!r}, which is not in the legend "
                    f"(legend keys: {keys}; use '.' or ' ' to skip a cell)"
                )
            out.append(Pixel(ox + gx, oy + gy, color))
    if not out:
        raise ValueError("grid has no painted cells — every character is '.' or ' '")
    return out


def validate_layer_name(name) -> str:
    if not isinstance(name, str) or not name.strip() or any(c in name for c in "\r\n"):
        raise ValueError(
            f"layer name must be a non-empty single-line string, got {name!r}"
        )
    return name.strip()


def validate_frame(frame) -> int:
    return _int(frame, "frame (1-based)", 1, 65535)


def validate_copy_frames(from_frame, to_frame) -> tuple[int, int]:
    f = _int(from_frame, "from_frame (1-based)", 1, 65535)
    t = _int(to_frame, "to_frame (1-based)", 1, 65535)
    if f == t:
        raise ValueError(f"from_frame and to_frame are both {f} — they must differ")
    return (f, t)


TAG_DIRECTIONS = {
    "forward": "AniDir.FORWARD",
    "reverse": "AniDir.REVERSE",
    "pingpong": "AniDir.PING_PONG",
    "pingpong_reverse": "AniDir.PING_PONG_REVERSE",
}


def validate_tag_name(name) -> str:
    if not isinstance(name, str) or not name.strip() or any(c in name for c in "\r\n"):
        raise ValueError(
            f"tag name must be a non-empty single-line string, got {name!r}"
        )
    return name.strip()


def validate_tag_direction(direction) -> str:
    if direction not in TAG_DIRECTIONS:
        raise ValueError(
            f"unknown direction {direction!r}: expected one of "
            "'forward', 'reverse', 'pingpong', 'pingpong_reverse'"
        )
    return TAG_DIRECTIONS[direction]


def validate_tag_range(from_frame, to_frame) -> tuple[int, int]:
    f = _int(from_frame, "from_frame (1-based)", 1, 65535)
    t = _int(to_frame, "to_frame (1-based)", 1, 65535)
    if f > t:
        raise ValueError(f"from_frame ({f}) must be <= to_frame ({t})")
    return (f, t)


def validate_duration_ms(ms) -> int:
    return _int(ms, "duration_ms", 1, MAX_DURATION_MS)


def validate_scale(scale) -> int:
    return _int(scale, "scale", 1, MAX_SCALE)


def validate_grid(grid) -> int:
    return _int(grid, "grid (source pixels between lines, 0 = off)", 0, MAX_CANVAS)


def validate_read_rect(x, y, width, height) -> tuple[int, int, int, int]:
    rx = _int(x, "x", 0, MAX_CANVAS)
    ry = _int(y, "y", 0, MAX_CANVAS)
    rw = _int(width, "width (0 = to canvas edge)", 0, MAX_CANVAS)
    rh = _int(height, "height (0 = to canvas edge)", 0, MAX_CANVAS)
    if rw and rh and rw * rh > MAX_READ_AREA:
        raise ValueError(
            f"read region {rw}x{rh} is {rw * rh} pixels; keep it at or under "
            f"{MAX_READ_AREA} (e.g. 64x64) and read in chunks"
        )
    return (rx, ry, rw, rh)


def validate_clear_rect(x, y, width, height) -> tuple[int, int, int, int]:
    return (
        _int(x, "x", 0, MAX_CANVAS),
        _int(y, "y", 0, MAX_CANVAS),
        _int(width, "width (0 = to canvas edge)", 0, MAX_CANVAS),
        _int(height, "height (0 = to canvas edge)", 0, MAX_CANVAS),
    )


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
