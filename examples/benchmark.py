#!/usr/bin/env python3
"""Kitsune MCP — Token Overhead Benchmark

Measures actual token costs from registered schemas. No network access required.

Usage:
    python examples/benchmark.py
"""
import asyncio
import json
import os
import sys

# Must be set before server.py imports — controls which tools are registered.
os.environ.setdefault("KITSUNE_TOOLS", "all")
os.environ.setdefault("SMITHERY_API_KEY", "")  # suppress key-not-set warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import _BASE_TOOL_NAMES, _LEAN_TOOLS, mcp
from kitsune_mcp.utils import _estimate_tokens


# ---------------------------------------------------------------------------
# Representative "typical server" — used to model the always-on baseline.
# Schema designed to match the average real MCP server (8 tools, ~97 tokens/tool).
# ---------------------------------------------------------------------------

_TYPICAL_TOOLS_PER_SERVER = 8
_TYPICAL_TOOL_SCHEMA = {
    "name": "query",
    "description": "Execute a query against the data source and return structured results.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "query":  {"type": "string",  "description": "The query to run"},
            "limit":  {"type": "integer", "description": "Max results to return"},
            "format": {"type": "string",  "description": "Output format: json|csv|text"},
        },
        "required": ["query"],
    },
}
_TYPICAL_TOKENS_PER_TOOL = len(json.dumps(_TYPICAL_TOOL_SCHEMA)) // 4


def _tool_dict(tool) -> dict:
    """Convert a FastMCP internal Tool to a JSON-serialisable dict."""
    return {
        "name": tool.name,
        "description": tool.description or "",
        "inputSchema": tool.parameters or {},
    }


def _tokens(tools: list) -> int:
    return _estimate_tokens([_tool_dict(t) for t in tools])


def run_benchmark():
    all_tools = list(mcp._tool_manager._tools.values())
    tool_map  = {t.name: t for t in all_tools}

    lean_tools  = [tool_map[n] for n in sorted(_LEAN_TOOLS)       if n in tool_map]
    forge_tools = [tool_map[n] for n in sorted(_BASE_TOOL_NAMES)  if n in tool_map]

    lean_tokens  = _tokens(lean_tools)
    forge_tokens = _tokens(forge_tools)

    w = 62
    print("=" * w)
    print("  Kitsune MCP — Token Overhead Benchmark")
    print("=" * w)
    print()

    # ── Profile sizes ──────────────────────────────────────────────────────
    print("=== Profile sizes (actual registered schemas) ===")
    print(f"  lean  ({len(lean_tools):2d} tools / default):  {lean_tokens:5d} tokens")
    print(f"  forge ({len(forge_tools):2d} tools / full):    {forge_tokens:5d} tokens")
    print()

    # ── Savings vs always-on ───────────────────────────────────────────────
    print("=== Savings: kitsune vs always-on N servers ===")
    print(
        f"  Baseline: {_TYPICAL_TOOLS_PER_SERVER} tools/server "
        f"× {_TYPICAL_TOKENS_PER_TOOL} tokens/tool (representative avg)"
    )
    print()

    for n_servers in (2, 5, 10):
        baseline   = n_servers * _TYPICAL_TOOLS_PER_SERVER * _TYPICAL_TOKENS_PER_TOOL
        # Kitsune MCP exposes itself (lean or forge) + 1 mounted server at a time
        with_lean  = lean_tokens  + _TYPICAL_TOOLS_PER_SERVER * _TYPICAL_TOKENS_PER_TOOL
        with_forge = forge_tokens + _TYPICAL_TOOLS_PER_SERVER * _TYPICAL_TOKENS_PER_TOOL

        def _note(cost: int) -> str:
            diff = baseline - cost
            pct  = int(diff / baseline * 100) if baseline > 0 else 0
            return f"saves {pct}%" if diff >= 0 else f"costs {-pct}% more"

        print(f"  {n_servers} servers — always-on baseline: {baseline:5d} tokens")
        print(f"    kitsune lean:     {with_lean:5d} tokens  ({_note(with_lean)})")
        print(f"    kitsune forge:    {with_forge:5d} tokens  ({_note(with_forge)})")
        print()

    # ── Per-tool breakdown ─────────────────────────────────────────────────
    print("=== Per-tool breakdown ===")
    print(f"  {'Tool':<28} {'Tokens':>6}  Profile")
    print("  " + "-" * 44)
    for t in sorted(forge_tools, key=lambda t: _tokens([t]), reverse=True):
        toks    = _tokens([t])
        profile = "lean + forge" if t.name in _LEAN_TOOLS else "forge only"
        print(f"  {t.name:<28} {toks:>6}  {profile}")

    print()
    print("Methodology: token_count = len(json.dumps(schema)) // 4")
    print("See docs/benchmarks.md for interpretation and caveats.")


if __name__ == "__main__":
    run_benchmark()
