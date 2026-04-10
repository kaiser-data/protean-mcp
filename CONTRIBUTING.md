# Contributing to Kitsune MCP

Thank you for helping make Kitsune better! This guide gets you to a working dev setup in under 5 minutes.

## Quick Setup

```bash
git clone https://github.com/kaiser-data/kitsune-mcp
cd kitsune-mcp
make dev        # installs kitsune-mcp + dev deps (pytest, ruff)
make test       # run all tests
make lint       # ruff lint check
make format     # auto-format with ruff
```

## Tool Patterns

Every tool in `server.py` follows this pattern:

```python
@mcp.tool()
async def my_tool(param: str, optional: int = 5) -> str:
    """One-line description. param: what it does."""
    # ... implementation
    return _truncate(result)
```

Rules:
- Return `str` always — FastMCP serializes everything
- Use `_truncate()` on any response that could be large
- Use `_clean_response()` on raw external content
- Update `session["stats"]` for call counts
- Add tool name to `_BASE_TOOL_NAMES` if it's a base tool (not a proxy)

## Transport Patterns

Adding a new transport? Subclass `BaseTransport`:

```python
class MyTransport(BaseTransport):
    async def execute(self, tool: str, args: dict, config: dict) -> str:
        # connect, call, return str
        ...
```

Add a test in `tests/test_transports.py` with a `respx` or subprocess mock.

## Commit Style

```
feat: add PersistentStdioTransport for hardware servers
fix: handle timeout in StdioTransport._read_response
docs: add hardware.md connect/release guide
test: add test_connect_returns_tool_list
```

## PR Checklist

- [ ] `make test` passes
- [ ] `make lint` passes (zero ruff errors)
- [ ] New tools are in `_BASE_TOOL_NAMES` if base-level
- [ ] New tools are documented in `docs/tools.md`
- [ ] Tests cover the happy path + at least one error case

## Adding a New Server Integration

If you found a server that works well with Kitsune, open a "New Server" issue:
- Server ID (e.g. `@modelcontextprotocol/server-filesystem`)
- Transport type: `http` or `stdio`
- Any error from `call()` or `shapeshift()` you hit

## Project Structure

```
server.py          # all tools, transports, registries — single file
tests/
  conftest.py      # shared fixtures (mock HTTP, mock subprocess)
  test_transports.py
  test_registry.py
  test_shapeshift.py  # tests shapeshift/shiftback helpers
  test_tools.py
  test_persistent.py
docs/
  quickstart.md
  tools.md
  transports.md
  hardware.md
  agent-patterns.md
```
