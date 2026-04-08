"""Chameleon Forge — full evaluation + crafting suite (all 17 tools).

Equivalent to: CHAMELEON_TOOLS=all protean-mcp
"""

import os

os.environ.setdefault("CHAMELEON_TOOLS", "all")

from server import mcp  # noqa: E402, F401 — registers all tools, applies profile

if __name__ == "__main__":
    mcp.run()
