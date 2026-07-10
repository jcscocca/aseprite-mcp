# aseprite-mcp

Pixel-art MCP server driving Aseprite in batch mode (`aseprite -b --script`).

## Commands

- Tests: `.venv/bin/pytest` — unit tests need no binary; integration tests run
  the real Aseprite and skip cleanly when it's missing.
- Binary resolution: `$ASEPRITE_BIN`, else `aseprite` on PATH, else the local
  dev build path in `runner.py`.
- Failed-script errors omit the generated Lua; set `ASEPRITE_MCP_DEBUG=1` to
  include it.

## Architecture

- `aseprite_mcp/core/` is deterministic and MCP-free: `ops.py` validates every
  op (fail loudly — name the bad value, list the valid options), `lua.py`
  generates batch scripts, `runner.py` executes them and parses the
  `AMCP_RESULT <json>` stdout line.
- `aseprite_mcp/mcp/tools.py` is argument-shaping only. Every tool takes the
  sprite file path — there is no session state.

## Conventions

- Never hand-write `.ase`/`.aseprite` bytes — all mutations go through
  generated Lua.
- Verify Lua API names against the Aseprite source before using them; batch
  mode has traps (cropped cels, app palette vs sprite palette, `newFrame(n)`
  semantics) — see the README's "How it works" section before touching
  `lua.py`.
- TDD: new behavior gets a failing test first. Tests are layered to match the
  code: `test_ops` (validation), `test_lua` (codegen text asserts),
  `test_runner` (subprocess plumbing, fake binaries), `test_integration`
  (real binary, Pillow pixel asserts).
