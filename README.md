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

`ASEPRITE_BIN` points at the Aseprite executable; when unset, `aseprite` is
looked up on PATH before falling back to a local dev build path. The server
verifies the binary launches at startup and exits loudly if it doesn't.

## 2. Tools

| Tool | Purpose |
|---|---|
| `create_canvas` | New sprite: size, color mode (rgb/grayscale/indexed), palette preset (`gameboy`, `pico8`, `sweetie16`) or hex list |
| `import_image` | New sprite from an existing PNG (≤1024px per side; PNG only) — optional conversion to grayscale or indexed (quantized against a required palette preset/hex list) |
| `get_canvas_info` | Size, color mode, layers, frames + durations, palette, tags |
| `set_palette` | Replace the palette with 1–256 hex colors |
| `draw_grid` | Character-grid drawing: `legend` (char → hex color) + `rows` (strings), the write-side twin of `read_pixels` — the compact way to draw sprite-sized art |
| `draw_pixels` | Batched pixels `[{x, y, color}]` on a layer/frame |
| `draw_shape` | Line, rectangle, ellipse (optionally filled), flood fill |
| `replace_color` | Swap every exact-match pixel of one color for another (raw, no blending) within an optional rect — reports how many pixels changed |
| `flip` | Flip a region (or the whole layer/frame) in place, horizontally or vertically |
| `mirror` | Complete a symmetric sprite: copy one half flipped onto the other (`source='left'` finishes a half-drawn sprite) |
| `shift` | Translate a layer/frame by (dx, dy); off-canvas pixels drop, or wrap with `wrap=True` |
| `rotate` | Rotate a layer/frame clockwise 90/180/270° (quarter turns need a square canvas) |
| `clear_region` | Erase a rectangle back to transparency (raw image clear — the eraser; `draw_shape` rejects transparent colors) |
| `add_layer` | New named layer (duplicate names rejected) |
| `delete_layer` / `rename_layer` | Layer lifecycle (the last layer is protected; renames collision-checked case-insensitively) |
| `add_frame` | Append a frame (duplicate of last, or empty) with duration |
| `set_frame_duration` | Change how long an existing frame plays |
| `delete_frame` | Remove a frame (later frames shift down; the last frame is protected) |
| `copy_cel` | Copy a layer's pixels from one frame onto another (re-posing without redrawing) |
| `add_tag` / `delete_tag` | Name a frame range as an animation (`walk`, frames 2–4, forward/reverse/pingpong) — becomes a named animation in spritesheet metadata |
| `preview` | Nearest-neighbor-scaled PNG of a frame, **returned as an image** so the agent sees its work; `grid=N` overlays magenta coordinate lines; `all_frames=True` renders a contact sheet of the whole animation |
| `read_pixels` | Exact pixel values for a region as a color legend + character grid — ground truth when placement matters (capped at 4096 px per read); `layer=` inspects one layer's cel instead of the composite |
| `export` | `png`, animated `gif`, or `spritesheet` (PNG atlas + Godot-oriented JSON: frame rects, durations, animations from tags); `scale=` upsamples nearest-neighbor on the way out |

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
palette in Lua (batch mode's "current palette" is not the sprite's, and
inexact matches are reported back as snapped colors), and `newFrame(n)`
returns the frame at position `n` rather than the new copy. Erasing:
`draw_pixels`/`draw_grid` set pixels raw, so `'#00000000'` erases, and
`clear_region` clears rectangles at the image level; `draw_shape` rejects
fully transparent colors (batch-mode tool strokes erase with them, but that
behavior is undocumented upstream, so it isn't relied on). `Sprite:newTag`
does no bounds checking, so tag ranges are validated in Lua before the tag is
created. `setPalette` refuses to shrink below an in-use palette index — the
pixels would silently render blank. GIF export reports tags whose
pingpong/reverse direction the format drops. Failed scripts raise with
Aseprite's output; set `ASEPRITE_MCP_DEBUG=1` to also include the generated
Lua source.

Some of these guarded behaviors are build-specific (e.g. `draw_shape`'s
alpha-0 erase quirk in batch mode), so the server logs the exact binary it
drives at startup — `aseprite-mcp: driving Aseprite <version>` on stderr.
The behaviors above were verified against Aseprite v1.3.17 (built from
source at commit d1624d9d0).

## Development

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

Unit tests (validation, codegen, runner plumbing) need no binary. Integration
tests run the real Aseprite and assert on exported PNG pixels with Pillow;
they skip cleanly when `ASEPRITE_BIN` is missing.

Per-push CI runs only the unit layers. The `integration` workflow builds a
headless CLI-only Aseprite (no Skia) pinned to v1.3.17, caches the binary,
and runs the full suite — trigger it manually from the Actions tab, or let
the twice-weekly schedule keep it (and the cache) fresh.

## License

MIT
