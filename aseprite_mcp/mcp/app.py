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
        "  2. draw_pixels() / draw_shape() — batched pixels, lines, rects, ellipses, flood fills\n"
        "  3. preview() — LOOK AT YOUR WORK. Returns a scaled PNG image; call it "
        "after every few edits and correct course\n"
        "  4. add_layer() / add_frame() — organize and animate\n"
        "  5. export() — png, animated gif, or spritesheet + Godot-ready JSON metadata\n\n"
        "Colors are hex strings ('#RRGGBB' or '#RRGGBBAA'). Coordinates are "
        "0-based with (0,0) at the top-left; frames are 1-based. In indexed "
        "color mode, palette index 0 is the transparent color on transparent "
        "layers — keep it for transparency rather than drawing with it."
    ),
)
