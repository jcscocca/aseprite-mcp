# aseprite-mcp

Pixel-art MCP server: lets an LLM agent create and edit pixel art by driving
[Aseprite](https://www.aseprite.org/) headlessly. "vizforge for pixel art."

Every mutation goes: validated op → generated Lua script → `aseprite -b --script` → result.
The server never hand-writes `.ase` binaries.

Work in progress — see `docs/superpowers/plans/` for the build plan.

## License

MIT
