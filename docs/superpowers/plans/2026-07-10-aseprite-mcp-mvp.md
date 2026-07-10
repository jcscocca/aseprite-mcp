# aseprite-mcp MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. (This plan is being executed inline in the authoring session; code-level detail lives in the tasks' test lists and the API reference below rather than duplicated full listings.)

**Goal:** An MCP server that lets an LLM agent create and edit pixel art by driving Aseprite headlessly — "vizforge for pixel art".

**Architecture:** Deterministic core, thin MCP layer (vizforge convention). Every mutation flows: validated op (pure Python) → generated Lua script (pure codegen) → `$ASEPRITE_BIN -b --script gen.lua` subprocess → parsed result. No hidden session state: every tool takes the sprite file path. Never hand-write .ase binaries.

**Tech Stack:** Python 3.11+, `mcp` (FastMCP), setuptools, pytest (+ Pillow for integration pixel asserts).

---

## File structure

```
aseprite-mcp/
├── .gitignore
├── .mcp.json.example          # vizforge-style: command = venv python, args = ["-m","aseprite_mcp"], env ASEPRITE_BIN
├── LICENSE                    # MIT
├── README.md
├── pyproject.toml             # name aseprite-mcp, requires-python >=3.11, deps: mcp; dev extra: pytest, pillow
├── docs/superpowers/plans/    # this plan
├── aseprite_mcp/
│   ├── __init__.py
│   ├── __main__.py            # from .server import main; main()
│   ├── server.py              # main(): verify binary at startup (fail loudly), run stdio
│   ├── core/
│   │   ├── __init__.py
│   │   ├── ops.py             # fail-loudly validators: paths, hex colors, pixels, shapes, palettes, frames, export opts
│   │   ├── palettes.py        # presets: gameboy, pico8, sweetie16
│   │   ├── lua.py             # pure Lua codegen — one function per op, returns script text
│   │   └── runner.py          # ASEPRITE_BIN resolution, --version verify, run_script(), AMCP_RESULT json parsing
│   └── mcp/
│       ├── __init__.py
│       ├── app.py             # FastMCP("aseprite-mcp", instructions=...) singleton
│       └── tools.py           # @server.tool() functions; thin: ops → lua → runner → message
└── tests/
    ├── __init__.py
    ├── test_ops.py            # unit: validation (no binary)
    ├── test_lua.py            # unit: codegen (no binary)
    ├── test_runner.py         # unit: env resolution, result parsing (no binary)
    └── test_integration.py    # real binary; module-level skipif when ASEPRITE_BIN missing; Pillow pixel asserts
```

## MCP tool surface

| Tool | Signature | Notes |
|---|---|---|
| create_canvas | `(path, width, height, color_mode="rgb", palette=None)` | palette = preset name or hex list; saveAs |
| get_canvas_info | `(path) -> dict` | size, color_mode, layers, frames+durations, palette hex |
| set_palette | `(path, colors)` | 1–256 hex colors |
| draw_pixels | `(path, pixels, layer=None, frame=1)` | pixels: `[{x,y,color}]`, batched, bounds-checked in Lua |
| draw_shape | `(path, shape, points, color, filled=False, layer=None, frame=1, tolerance=0)` | line / rectangle / ellipse / fill via app.useTool |
| add_layer | `(path, name)` | errors on duplicate name |
| add_frame | `(path, duration_ms=100, mode="duplicate") -> dict` | mode duplicate\|empty; returns frame numbers |
| preview | `(path, scale=8, frame=1) -> Image` | drawSprite → resize (nearest) → PNG → returned as MCP image content — the killer feature |
| export | `(path, out, format="png", sheet_type="rows", columns=0, padding=0) -> dict` | png / gif (animated) / spritesheet + Godot-oriented JSON metadata |

## Aseprite Lua API reference (verified against src/app/script/*.cpp — do not guess beyond this)

- `Sprite(w, h, ColorMode.RGB|GRAYSCALE|INDEXED)`; `app.open(path)` returns Sprite or nil.
- `spr:saveAs(p)` rebinds filename + marks saved; `spr:saveCopyAs(p)` exports without rebinding. Both return bool.
- Frames 1-based; `frame.duration` in **seconds**; `spr:newFrame(n)` copies frame n inserting after; `spr:newEmptyFrame(n)` inserts blank.
- Layers: `spr:newLayer()` (top of stack, set `.name` after); `spr.layers["name"]` case-insensitive lookup, `spr.layers[i]` 1-based.
- Cels: `layer:cel(frame)` → nil if absent. `cel.image` is **cropped to cel bounds** at `cel.position` — naive putPixel outside bounds silently no-ops. Fix: normalize to a full-canvas cel first: `full = Image(spr.spec); full:drawImage(cel.image, cel.position); spr:newCel(layer, f, full, Point(0,0))`.
- Pixels: `img:drawPixel(x,y,color)` (= putPixel). Integer args are raw pixel values (**palette index** in indexed mode!) — always pass `Color{r,g,b,a}` so `color_for_image` converts per color mode.
- Shapes: `app.useTool{tool=, color=, layer=, frame=, points={Point(x,y),...}, contiguous=, tolerance=}`. Tool ids: `line`, `rectangle`, `filled_rectangle`, `ellipse`, `filled_ellipse`, `paint_bucket`, `pencil`. Headless default brush = 1px circle.
- Palette: `Palette(n)`, `pal:setColor(i, Color{...})` (**0-based** index), `spr:setPalette(pal)`, `#pal`, `pal:getColor(i)` → Color.
- Preview render: `img = Image(spr.spec); img:drawSprite(spr, frameNumber); img:resize{width=, height=}` (nearest-neighbor is the default resize method); `img:saveAs{filename=, palette=spr.palettes[1]}`.
- Spritesheet: `app.command.ExportSpriteSheet{ui=false, askOverwrite=false, type="rows|columns|horizontal|vertical|packed" (lowercase string, case-sensitive; typos silently → None!), columns=, rows=, textureFilename=, dataFilename=, dataFormat="json-array", borderPadding=, shapePadding=, innerPadding=, listTags=true}`. Aseprite JSON durations are ms.
- GIF: `saveCopyAs("x.gif")` writes all frames with durations. PNG writes first frame only.
- Batch: `aseprite -b --script f.lua`. Uncaught `error()` → exit code 255; **print() and errors both go to stdout**. Result protocol: `print("AMCP_RESULT " .. json)`, parse in Python; rely on exit code for failure.

## Tasks

### Task 1: Scaffold
- [x] git init, .gitignore, MIT LICENSE, README stub, pyproject.toml, package skeleton, .mcp.json.example, this plan. Commit.

### Task 2: core/ops.py + core/palettes.py (TDD)
- [ ] tests/test_ops.py: hex parsing (#RGB/#RRGGBB/#RRGGBBAA, invalid → ValueError naming the value), sprite path suffix rules, canvas size limits (1..65535), color_mode set, pixels structure validation, shape kind/point-count rules, palette 1..256 + preset resolution, frame ≥1, duration 1..65535, export format/sheet_type sets, scale 1..64.
- [ ] Implement ops.py (plain functions + small dataclasses, raise ValueError with agent-actionable messages listing valid options) and palettes.py (gameboy, pico8, sweetie16).
- [ ] pytest green. Commit.

### Task 3: core/lua.py (TDD)
- [ ] tests/test_lua.py: each script contains exact verified API calls; lua string quoting (quotes/backslashes in paths); Color literals; frame duration ms→s conversion; ensure-cel normalization present in draw scripts; ExportSpriteSheet param spelling; AMCP_RESULT emission in info script.
- [ ] Implement codegen: shared snippets (open-or-error, find-layer-or-error listing available names, ensure-full-canvas-cel), one builder per op.
- [ ] pytest green. Commit.

### Task 4: core/runner.py
- [ ] tests/test_runner.py: env-var override wins over default; extract_result parses marker line / raises on missing; script error raises AsepriteError containing stdout + script.
- [ ] Implement: DEFAULT_BIN=/Users/jscocca/Repos/aseprite/build/bin/aseprite, resolve via ASEPRITE_BIN; verify_binary() runs `--version`, checks "Aseprite" prefix; run_script writes temp .lua, runs `-b --script`, raises on nonzero exit with stdout (errors land there) and generated script in the message.
- [ ] pytest green. Commit.

### Task 5: MCP layer
- [ ] mcp/app.py: FastMCP singleton with instructions (workflow: create_canvas → draw → preview after every few edits → export; never write .ase bytes directly).
- [ ] mcp/tools.py: all 9 tools; docstring = tool description; return str/dict; preview returns fastmcp Image; export spritesheet post-processes Aseprite JSON into Godot-oriented metadata (frame_size, columns/rows, per-frame durations_ms, animations from frameTags else "default").
- [ ] server.py main(): verify_binary() before serving (fail loudly, stderr), stdio transport. __main__.py.
- [ ] Commit.

### Task 6: Integration tests (real binary)
- [ ] tests/test_integration.py, module-level skipif when binary absent. Cases: create+info roundtrip; draw_pixels → export png → Pillow exact-RGBA asserts; filled rectangle + line; flood fill; indexed+gameboy palette roundtrip; duplicate layer name fails; add_frame + gif export; 3-frame spritesheet (48x16, metadata frames=3, durations); preview scale=8 → 128x128 with uniform 8px blocks; missing file error names path; out-of-bounds pixel fails.
- [ ] pytest green (full suite). Commit.

### Task 7: End-to-end slime + docs
- [ ] Script in scratchpad drives the actual tool functions: 16x16 slime, 3-frame idle (tall/squash/tall) via pixel maps, per-frame preview, gif + spritesheet + Godot JSON export. Visually confirm the preview PNG depicts a slime (read the image).
- [ ] Finalize README (config, tool table, how-it-works, development). Commit.

## Self-review notes
- Spec coverage: all 9 tools ✔, env var + startup verify ✔ (Task 4/5), unit vs integration split ✔ (Tasks 2–4 vs 6), slime e2e ✔ (Task 7), .mcp.json.example + `python -m aseprite_mcp` ✔ (Tasks 1/5), MIT + README ✔ (Tasks 1/7).
- Known risks called out in API reference: indexed putPixel, cropped cels, seconds-vs-ms, silent SpriteSheetType typo fallback, stdout error stream. `newEmptyFrame(#frames+1)` append position must be confirmed in Task 6 — if it rejects out-of-range, fall back to newFrame + clear cels.
