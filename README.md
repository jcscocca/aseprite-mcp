# aseprite-mcp

Pixel-art MCP server: lets an LLM agent create and edit pixel art by driving
[Aseprite](https://www.aseprite.org/) headlessly. "vizforge for pixel art."

Every mutation goes: validated op → generated Lua script →
`aseprite -b --script gen.lua` → result. The server never hand-writes
`.ase`/`.aseprite` binaries, and there is no hidden session state — every tool
takes the sprite file path it operates on.

## 1. MCP server (primary — for Claude)

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

Copy `.mcp.json.example` to your MCP client config and fix the paths:

```json
{
  "mcpServers": {
    "aseprite": {
      "command": "/absolute/path/to/aseprite-mcp/.venv/bin/python",
      "args": ["-m", "aseprite_mcp"],
      "env": { "ASEPRITE_BIN": "/path/to/aseprite" }
    }
  }
}
```

`ASEPRITE_BIN` points at the Aseprite executable (default:
`/Users/jscocca/Repos/aseprite/build/bin/aseprite`). The server verifies it
launches at startup and exits loudly if it doesn't.

## 2. Tools

| Tool | Purpose |
|---|---|
| `create_canvas` | New sprite: size, color mode (rgb/grayscale/indexed), palette preset (`gameboy`, `pico8`, `sweetie16`) or hex list |
| `get_canvas_info` | Size, color mode, layers, frames + durations, palette, tags |
| `set_palette` | Replace the palette with 1–256 hex colors |
| `draw_pixels` | Batched pixels `[{x, y, color}]` on a layer/frame |
| `draw_shape` | Line, rectangle, ellipse (optionally filled), flood fill |
| `clear_region` | Erase a rectangle back to transparency (raw image clear — the eraser `draw_shape` can't be) |
| `add_layer` | New named layer (duplicate names rejected) |
| `add_frame` | Append a frame (duplicate of last, or empty) with duration |
| `set_frame_duration` | Change how long an existing frame plays |
| `delete_frame` | Remove a frame (later frames shift down; the last frame is protected) |
| `copy_cel` | Copy a layer's pixels from one frame onto another (re-posing without redrawing) |
| `add_tag` | Name a frame range as an animation (`walk`, frames 2–4, forward/reverse/pingpong) — becomes a named animation in spritesheet metadata |
| `preview` | Nearest-neighbor-scaled PNG of a frame, **returned as an image** so the agent sees its work; `grid=N` overlays magenta coordinate lines every N pixels |
| `read_pixels` | Exact pixel values for a region as a color legend + character grid — ground truth when placement matters (capped at 4096 px per read) |
| `export` | `png`, animated `gif`, or `spritesheet` (PNG atlas + Godot-oriented JSON: frame rects, durations, animations from tags) |

The intended loop: draw a few things, `preview`, correct course, repeat, then
`export`. A 16x16 slime with a 3-frame idle animation, drawn entirely through
these tools:

`preview(frame=1)` → 128x128 PNG of the slime · `export(format="spritesheet")`
→ 48x16 atlas + `slime_sheet.json` with per-frame rects and durations ready
for a Godot importer (AtlasTexture regions / SpriteFrames).

## 3. How it works

- `aseprite_mcp/core/` is deterministic and MCP-free: `ops.py` validates every
  op and fails loudly with agent-actionable messages, `lua.py` generates batch
  scripts against Lua API names verified in the Aseprite source, `runner.py`
  runs `$ASEPRITE_BIN -b --script` and turns nonzero exits into errors carrying
  the script and Aseprite's output (which lands on stdout in batch mode).
- `aseprite_mcp/mcp/` is the thin FastMCP layer: argument shaping only.
- Structured results come back on an `AMCP_RESULT <json>` stdout line.

Notable Aseprite batch-mode traps handled here: cel images are cropped to
their bounds (pixels are drawn onto full-canvas cels so `putPixel` can't
silently no-op), indexed-mode colors are resolved against the sprite's own
palette in Lua (batch mode's "current palette" is not the sprite's), and
`newFrame(n)` returns the frame at position `n` rather than the new copy.
Erasing: `draw_pixels` sets pixels raw, so `'#00000000'` erases, and
`clear_region` clears rectangles at the image level; `draw_shape` strokes
alpha-blend and cannot erase. `Sprite:newTag` does no bounds checking, so tag
ranges are validated in Lua before the tag is created.

## Development

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

Unit tests (validation, codegen, runner plumbing) need no binary. Integration
tests run the real Aseprite and assert on exported PNG pixels with Pillow;
they skip cleanly when `ASEPRITE_BIN` is missing.

## License

MIT
