import asyncio
import inspect as _inspect
from collections.abc import Callable

from chameleon_mcp.app import mcp
from chameleon_mcp.constants import (
    MCP_CLIENT_INFO,
    MCP_PROTOCOL_VERSION,
    TIMEOUT_RESOURCE_LIST,
    TIMEOUT_STDIO_INIT,
    TIMEOUT_STDIO_TOOL,
)
from chameleon_mcp.session import session
from chameleon_mcp.transport import BaseTransport, StdioTransport

_frame = StdioTransport._frame


def _json_type_to_py(json_type: str) -> type:
    """Convert JSON Schema type string to Python type."""
    mapping = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
        "object": dict,
    }
    return mapping.get(json_type, str)


async def _fetch_tools_list(install_cmd: list) -> list[dict]:
    """Fetch tool list from a stdio MCP server via tools/list JSON-RPC."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *install_cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except Exception:
        return []

    try:
        init_req = {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": MCP_CLIENT_INFO,
            },
        }
        proc.stdin.write(_frame(init_req))
        await proc.stdin.drain()

        init_resp = await StdioTransport._read_response(proc.stdout, expected_id=1, timeout=TIMEOUT_STDIO_INIT)
        if not init_resp or "error" in init_resp:
            return []

        proc.stdin.write(_frame({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}))
        proc.stdin.write(_frame({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}))
        await proc.stdin.drain()

        tools_resp = await StdioTransport._read_response(proc.stdout, expected_id=2, timeout=TIMEOUT_STDIO_TOOL)
        if not tools_resp or "error" in tools_resp:
            return []

        return tools_resp.get("result", {}).get("tools", [])

    except Exception:
        return []
    finally:
        try:
            proc.stdin.close()
            proc.kill()
            await asyncio.wait_for(proc.wait(), timeout=TIMEOUT_RESOURCE_LIST)
        except Exception:
            pass


def _make_proxy(
    server_id: str,
    tool_schema: dict,
    transport: BaseTransport,
    config: dict,
    proxy_name: str = None,
) -> Callable:
    """Create a proxy callable that forwards calls to a remote/local MCP tool.

    proxy_name: the name the tool will be registered as in FastMCP.
                Defaults to tool_schema["name"]. The transport always uses
                the original schema name when calling the remote server.
    """
    original_name = tool_schema["name"]
    fn_name = proxy_name or original_name
    props = (tool_schema.get("inputSchema") or {}).get("properties", {})
    required_set = set((tool_schema.get("inputSchema") or {}).get("required", []))

    params = []
    for pname, pschema in props.items():
        ptype = _json_type_to_py(pschema.get("type", "string"))
        default = _inspect.Parameter.empty if pname in required_set else None
        params.append(_inspect.Parameter(
            pname, _inspect.Parameter.KEYWORD_ONLY,
            default=default, annotation=ptype,
        ))

    async def proxy_fn(**kwargs) -> str:
        return await transport.execute(original_name, kwargs, config)

    proxy_fn.__name__ = fn_name
    proxy_fn.__doc__ = (tool_schema.get("description") or "")[:120]
    proxy_fn.__signature__ = _inspect.Signature(params, return_annotation=str)
    return proxy_fn


def _do_shed() -> list[str]:
    """Remove all morphed proxy tools. Returns list of removed tool names."""
    removed = []
    for tname in session["morphed_tools"]:
        try:
            mcp.remove_tool(tname)
            removed.append(tname)
        except Exception:
            pass
    session["morphed_tools"] = []
    session["current_form"] = None
    return removed


def _register_proxy_tools(
    server_id: str, tools: list, transport: "BaseTransport", config: dict,
    base_tool_names: set = None,
) -> list[str]:
    """Register proxy tools for a server, handling name collisions with base tools."""
    import re
    sanitized = re.sub(r'[^a-z0-9_]', '_', server_id.lower())
    registered = []
    for tool_schema in tools:
        raw_name = tool_schema.get("name", "")
        if not raw_name:
            continue
        if base_tool_names and raw_name in base_tool_names:
            proxy_name = f"{sanitized}_{raw_name}"
        else:
            proxy_name = raw_name
        proxy = _make_proxy(server_id, tool_schema, transport, config, proxy_name)
        try:
            mcp.add_tool(proxy)
            registered.append(proxy_name)
        except Exception:
            pass
    return registered
