"""MCP tools: thin argument-shaping over the deterministic core.

Each tool validates its op (ops), generates Lua (lua), runs Aseprite (runner),
and reports plainly. Errors are raised, never returned as success strings.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from mcp.server.fastmcp import Image as MCPImage

from ..core import lua, ops, runner
from ..core.godot import build_godot_metadata
from .app import server


@server.tool()
def create_canvas(
    path: str,
    width: int,
    height: int,
    color_mode: str = "rgb",
    palette: str | list[str] | None = None,
    overwrite: bool = False,
) -> str:
    """Create a new Aseprite sprite file (.ase/.aseprite).

    color_mode: 'rgb', 'grayscale' or 'indexed'. palette: a preset name
    ('gameboy', 'pico8', 'sweetie16') or a list of hex colors like '#22c55e';
    omit to keep Aseprite's default palette. Refuses to replace an existing
    file unless overwrite=True.
    """
    p = ops.validate_sprite_path(path, must_exist=False)
    if p.exists() and not overwrite:
        raise ValueError(
            f"{p} already exists — pass overwrite=True to replace it, or pick another path"
        )
    w, h = ops.validate_canvas_size(width, height)
    mode_lua = ops.validate_color_mode(color_mode)
    colors = ops.resolve_palette(palette)
    script = lua.script_create_canvas(p, w, h, mode_lua, colors)
    result = runner.extract_result(runner.run_script(script))
    palette_note = f", palette: {len(colors)} colors" if colors else ""
    return (
        f"Created {w}x{h} {color_mode} canvas at {p} "
        f"(layer {result['layer']!r}, 1 frame{palette_note})."
    )


@server.tool()
def get_canvas_info(path: str) -> dict:
    """Inspect a sprite: size, color mode, layers, frames with durations, and palette."""
    p = ops.validate_sprite_path(path, must_exist=True)
    return runner.extract_result(runner.run_script(lua.script_get_canvas_info(p)))


@server.tool()
def set_palette(path: str, colors: list[str]) -> str:
    """Replace the sprite's palette with 1-256 hex colors (index order preserved)."""
    p = ops.validate_sprite_path(path, must_exist=True)
    rgba = ops.resolve_palette(colors)
    runner.run_script(lua.script_set_palette(p, rgba))
    return f"Set palette of {p.name} to {len(rgba)} colors."


@server.tool()
def draw_pixels(
    path: str,
    pixels: list[dict],
    layer: str | None = None,
    frame: int = 1,
) -> str:
    """Draw a batch of individual pixels: [{'x': 0, 'y': 0, 'color': '#ff0000'}, ...].

    Coordinates are 0-based from the top-left. layer defaults to the bottom
    layer; frame is 1-based. Out-of-bounds pixels fail the whole batch.
    """
    p = ops.validate_sprite_path(path, must_exist=True)
    px = ops.validate_pixels(pixels)
    layer_name = ops.validate_layer_name(layer) if layer is not None else None
    fr = ops.validate_frame(frame)
    runner.run_script(lua.script_draw_pixels(p, px, layer_name, fr))
    target = f"layer {layer_name!r}" if layer_name else "the bottom layer"
    return f"Drew {len(px)} pixel(s) on {target}, frame {fr} of {p.name}."


@server.tool()
def draw_shape(
    path: str,
    shape: str,
    points: list[dict],
    color: str,
    filled: bool = False,
    layer: str | None = None,
    frame: int = 1,
    tolerance: int = 0,
) -> str:
    """Draw a shape: 'line' (2 points), 'rectangle'/'ellipse' (2 corner points,
    filled=True for solid), or 'fill' (1 seed point, flood fill with optional
    tolerance 0-255). Points are {'x': int, 'y': int} or [x, y].
    """
    p = ops.validate_sprite_path(path, must_exist=True)
    op = ops.validate_shape(shape, points, color, filled=filled, tolerance=tolerance)
    layer_name = ops.validate_layer_name(layer) if layer is not None else None
    fr = ops.validate_frame(frame)
    runner.run_script(lua.script_draw_shape(p, op, layer_name, fr))
    target = f"layer {layer_name!r}" if layer_name else "the bottom layer"
    return f"Drew {shape} ({op.tool}) on {target}, frame {fr} of {p.name}."


@server.tool()
def clear_region(
    path: str,
    x: int = 0,
    y: int = 0,
    width: int = 0,
    height: int = 0,
    layer: str | None = None,
    frame: int = 1,
) -> str:
    """Erase a rectangular region back to transparency (raw image clear).

    This is the eraser — draw_shape cannot erase because tool strokes
    alpha-blend. width/height of 0 extend to the canvas edge (omit all four to
    wipe the whole layer/frame). Clearing a layer/frame that has no content is
    an error, not a silent no-op.
    """
    p = ops.validate_sprite_path(path, must_exist=True)
    rect = ops.validate_clear_rect(x, y, width, height)
    layer_name = ops.validate_layer_name(layer) if layer is not None else None
    fr = ops.validate_frame(frame)
    runner.run_script(lua.script_clear_region(p, rect, layer_name, fr))
    target = f"layer {layer_name!r}" if layer_name else "the bottom layer"
    return f"Cleared region on {target}, frame {fr} of {p.name}."


@server.tool()
def add_layer(path: str, name: str) -> str:
    """Add a new transparent layer on top of the stack. Fails if the name is already taken."""
    p = ops.validate_sprite_path(path, must_exist=True)
    layer_name = ops.validate_layer_name(name)
    runner.run_script(lua.script_add_layer(p, layer_name))
    return f"Added layer {layer_name!r} on top of the stack in {p.name}."


@server.tool()
def add_frame(path: str, duration_ms: int = 100, mode: str = "duplicate") -> dict:
    """Append a frame. mode='duplicate' copies the last frame's content (good for
    tweaking animation frames); mode='empty' appends a blank frame.
    """
    p = ops.validate_sprite_path(path, must_exist=True)
    ms = ops.validate_duration_ms(duration_ms)
    if mode not in ("duplicate", "empty"):
        raise ValueError(f"mode must be 'duplicate' or 'empty', got {mode!r}")
    result = runner.extract_result(runner.run_script(lua.script_add_frame(p, ms, mode)))
    result["duration_ms"] = ms
    return result


@server.tool()
def delete_frame(path: str, frame: int) -> dict:
    """Delete a 1-based frame; later frames shift down (tags adjust automatically).

    Cannot delete a sprite's only frame.
    """
    p = ops.validate_sprite_path(path, must_exist=True)
    fr = ops.validate_frame(frame)
    return runner.extract_result(runner.run_script(lua.script_delete_frame(p, fr)))


@server.tool()
def copy_cel(path: str, from_frame: int, to_frame: int, layer: str | None = None) -> str:
    """Copy a layer's pixels from one frame onto another, replacing what was there.

    The re-posing workflow: add_frame(mode='empty'), copy_cel from the previous
    frame, then edit the copy — the two frames stay independent. Copies within
    one layer; layer defaults to the bottom layer.
    """
    p = ops.validate_sprite_path(path, must_exist=True)
    f, t = ops.validate_copy_frames(from_frame, to_frame)
    layer_name = ops.validate_layer_name(layer) if layer is not None else None
    runner.run_script(lua.script_copy_cel(p, f, t, layer_name))
    target = f"layer {layer_name!r}" if layer_name else "the bottom layer"
    return f"Copied {target} content from frame {f} to frame {t} of {p.name}."


@server.tool()
def add_tag(
    path: str,
    name: str,
    from_frame: int,
    to_frame: int,
    direction: str = "forward",
) -> str:
    """Tag a 1-based frame range as a named animation (e.g. 'walk' over frames 2-4).

    Tags become named animations in spritesheet export metadata; without tags
    every export collapses into one 'default' animation. direction: 'forward',
    'reverse', 'pingpong' or 'pingpong_reverse'.
    """
    p = ops.validate_sprite_path(path, must_exist=True)
    tag_name = ops.validate_tag_name(name)
    f, t = ops.validate_tag_range(from_frame, to_frame)
    anidir = ops.validate_tag_direction(direction)
    runner.run_script(lua.script_add_tag(p, tag_name, f, t, anidir))
    return f"Tagged frames {f}-{t} of {p.name} as {tag_name!r} ({direction})."


@server.tool()
def set_frame_duration(path: str, frame: int, duration_ms: int) -> str:
    """Set how long a frame is shown during animation playback (frame is 1-based)."""
    p = ops.validate_sprite_path(path, must_exist=True)
    fr = ops.validate_frame(frame)
    ms = ops.validate_duration_ms(duration_ms)
    runner.run_script(lua.script_set_frame_duration(p, fr, ms))
    return f"Set frame {fr} of {p.name} to {ms}ms."


@server.tool()
def preview(path: str, scale: int = 8, frame: int = 1, grid: int = 0) -> MCPImage:
    """Render a frame as a nearest-neighbor-scaled PNG and return it as an image.

    Call this after every few edits to see the current state of the art and
    correct course. scale=8 turns a 16x16 sprite into a readable 128x128 image.
    grid=N overlays magenta lines every N source pixels (grid=1 outlines every
    pixel) so you can count exact coordinates; 0 = off.
    """
    p = ops.validate_sprite_path(path, must_exist=True)
    s = ops.validate_scale(scale)
    fr = ops.validate_frame(frame)
    g = ops.validate_grid(grid)
    fd, out_png = tempfile.mkstemp(suffix=".png", prefix="aseprite_mcp_preview_")
    os.close(fd)
    try:
        runner.run_script(lua.script_preview(p, Path(out_png), s, fr, grid=g))
        data = Path(out_png).read_bytes()
    finally:
        os.unlink(out_png)
    if not data:
        raise runner.AsepriteError(f"preview of {p} produced an empty PNG")
    return MCPImage(data=data, format="png")


@server.tool()
def read_pixels(
    path: str,
    x: int = 0,
    y: int = 0,
    width: int = 0,
    height: int = 0,
    frame: int = 1,
) -> dict:
    """Read back rendered pixels as a color legend + character grid — exact ground
    truth for what a region looks like (use it to verify placement or debug a
    draw that didn't land where expected).

    Returns {'legend': {'.': 'transparent', 'a': '#rrggbb', ...}, 'rows': [...]},
    one string per pixel row. width/height of 0 extend to the canvas edge; regions
    are capped at 4096 pixels (e.g. 64x64) — read larger sprites in chunks.
    """
    p = ops.validate_sprite_path(path, must_exist=True)
    rect = ops.validate_read_rect(x, y, width, height)
    fr = ops.validate_frame(frame)
    return runner.extract_result(runner.run_script(lua.script_read_pixels(p, rect, fr)))


@server.tool()
def export(
    path: str,
    out: str,
    format: str = "png",
    sheet_type: str = "rows",
    columns: int = 0,
    padding: int = 0,
) -> dict:
    """Export the sprite for use in a game engine.

    format='png' (first frame), 'gif' (animated, uses frame durations), or
    'spritesheet' (PNG atlas + <out>.json Godot-oriented metadata: frame rects,
    durations in ms, animations from tags). sheet_type: rows|columns|horizontal|
    vertical|packed; columns=0 means auto; padding adds border+spacing pixels.
    """
    p = ops.validate_sprite_path(path, must_exist=True)
    fmt = ops.validate_export_format(format)
    out_path = ops.validate_out_path(out, fmt)

    if fmt in ("png", "gif"):
        result = runner.extract_result(runner.run_script(lua.script_export_flat(p, out_path)))
        info: dict = {"out": str(out_path), "format": fmt, "frames": result["frames"]}
        if fmt == "png" and result["frames"] > 1:
            info["note"] = (
                f"sprite has {result['frames']} frames but PNG holds one image — "
                "exported frame 1 only; use format='gif' or 'spritesheet' for animation"
            )
        return info

    st = ops.validate_sheet_type(sheet_type)
    cols = ops.validate_columns(columns)
    pad = ops.validate_padding(padding)
    fd, raw_json = tempfile.mkstemp(suffix=".json", prefix="aseprite_mcp_sheet_")
    os.close(fd)
    try:
        script = lua.script_export_spritesheet(p, out_path, Path(raw_json), st, cols, pad)
        runner.run_script(script)
        ase_data = json.loads(Path(raw_json).read_text())
    finally:
        os.unlink(raw_json)
    metadata = build_godot_metadata(ase_data, out_path.name)
    meta_path = out_path.with_suffix(".json")
    meta_path.write_text(json.dumps(metadata, indent=2) + "\n")
    return {
        "out": str(out_path),
        "metadata_path": str(meta_path),
        "format": "spritesheet",
        "godot_metadata": metadata,
    }
