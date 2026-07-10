"""Entrypoint for the aseprite-mcp server (stdio transport)."""

from __future__ import annotations

import sys

from .core.runner import AsepriteError, verify_binary
from .mcp.app import server
from .mcp import tools  # noqa: F401  (imported for @server.tool registration side effects)


def main() -> None:
    try:
        version = verify_binary()
    except AsepriteError as e:
        print(f"aseprite-mcp: {e}", file=sys.stderr)
        raise SystemExit(1) from None
    print(f"aseprite-mcp: driving {version}", file=sys.stderr)
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
