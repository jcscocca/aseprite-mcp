"""FastMCP server singleton.

Import order matters: this module must be imported before tools.py so that
`server` exists when the @server.tool() decorators run.
"""

from mcp.server.fastmcp import FastMCP

server = FastMCP(
    "aseprite-mcp",
    instructions=(
        "Pixel-art creation MCP server driving Aseprite headlessly.\n\n"
        "CRITICAL: Never write .ase/.aseprite files yourself — every edit must "
        "go through these tools, which generate Lua and run Aseprite in batch "
        "mode. All tools take the sprite file path; there is no hidden session.\n\n"
        "Typical workflow:\n"
        "  1. create_canvas() — new sprite file (pick a palette preset or pass hex colors)\n"
        "  2. draw_grid() / draw_pixels() / draw_shape() — character-grid art "
        "(legend + rows, the compact way to draw sprites), batched pixels, "
        "lines, rects, ellipses, flood fills\n"
        "  3. preview() — LOOK AT YOUR WORK. Returns a scaled PNG image; call it "
        "after every few edits and correct course (grid=N overlays coordinate "
        "lines every N pixels; all_frames=True renders the whole animation as "
        "a contact sheet)\n"
        "  4. read_pixels() — exact pixel values as a legend + character grid; "
        "use it when placement matters or a draw didn't land where expected "
        "(layer= inspects one layer instead of the composite)\n"
        "  5. Fix up: replace_color() swaps one color for another; "
        "clear_region() erases; delete_layer()/rename_layer()/delete_tag() "
        "undo organizational mistakes\n"
        "  5b. Transform: mirror() completes a symmetric sprite from one "
        "half (draw the left side, mirror(source='left'), done); flip() "
        "flips a region in place; shift() nudges pixels (wrap=true for "
        "scrolling); rotate() turns 90/180/270\n"
        "  6. add_layer() / add_frame() — organize and animate (drawing moving "
        "parts on their own layer keeps edits from disturbing the rest)\n"
        "  7. Animate: set_frame_duration() for timing, copy_cel() to re-pose "
        "(copy a frame's pixels, then edit the copy), delete_frame() to drop "
        "one, add_tag() to name frame ranges as animations\n"
        "  8. export() — png, animated gif, or spritesheet + Godot-ready JSON "
        "metadata (tags become named animations); scale=N upsamples "
        "nearest-neighbor for shareable output\n\n"
        "Colors are hex strings ('#RRGGBB' or '#RRGGBBAA'). Coordinates are "
        "0-based with (0,0) at the top-left; frames are 1-based. In indexed "
        "color mode, palette index 0 is the transparent color on transparent "
        "layers — keep it for transparency rather than drawing with it — and "
        "off-palette colors snap to the nearest entry (reported in the tool "
        "result). Erasing: clear_region() erases rectangles; draw_pixels/"
        "draw_grid with '#00000000' erase single pixels (raw pixel set); "
        "draw_shape rejects transparent colors."
    ),
)
