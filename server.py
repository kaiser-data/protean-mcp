import asyncio
import inspect as _inspect
import os
import re
import json
import base64
import shutil
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
import httpx
import certifi
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP, Context

load_dotenv()

mcp = FastMCP("chameleon")

SMITHERY_API_KEY = os.getenv("SMITHERY_API_KEY")
REGISTRY_BASE = "https://registry.smithery.ai"
ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

MAX_RESPONSE_TOKENS = 1500   # ~6000 chars — hard cap on all tool returns
MAX_EXPLORE_DESC = 80
MAX_INSPECT_DESC = 120

# Base tool names — used for collision detection in morph()
_BASE_TOOL_NAMES = {
    "search", "inspect", "call", "run", "fetch",
    "skill", "key", "auto", "status", "morph", "shed",
}

# Session state
session = {
    "explored": {},
    "skills": {},
    "grown": {},
    "morphed_tools": [],      # names of dynamically registered proxy tools
    "current_form": None,     # server_id currently morphed into
    "stats": {
        "total_calls": 0,
        "tokens_sent": 0,
        "tokens_received": 0,
        "tokens_saved_browse": 0,
    },
}


# ---------------------------------------------------------------------------
# Core Abstractions
# ---------------------------------------------------------------------------

@dataclass
class ServerInfo:
    id: str
    name: str
    description: str
    source: str           # "smithery" | "npm"
    transport: str        # "http" | "stdio"
    url: str = ""
    install_cmd: list = field(default_factory=list)
    credentials: dict = field(default_factory=dict)  # {field: description}
    tools: list = field(default_factory=list)         # lazy-loaded
    token_cost: int = 0


class BaseRegistry(ABC):
    @abstractmethod
    async def search(self, query: str, limit: int) -> list: ...

    @abstractmethod
    async def get_server(self, id: str): ...


class BaseTransport(ABC):
    @abstractmethod
    async def execute(self, tool: str, args: dict, config: dict) -> str: ...


# ---------------------------------------------------------------------------
# Token Helpers
# ---------------------------------------------------------------------------

def _estimate_tokens(text) -> int:
    if isinstance(text, list):
        return sum(len(json.dumps(t)) for t in text) // 4
    return len(str(text)) // 4


def _truncate(text: str, max_tokens: int = MAX_RESPONSE_TOKENS) -> str:
    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n[...truncated at ~{max_tokens} tokens]"


def _clean_response(text: str) -> str:
    text = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', text)  # strip markdown links, keep label
    text = re.sub(r'!\[[^\]]*\]', '', text)                # strip images
    text = re.sub(r'\n{3,}', '\n\n', text)                 # collapse blank lines
    text = re.sub(r'[ \t]{2,}', ' ', text)                 # collapse spaces
    return text.strip()


def _strip_html(text: str) -> str:
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = (text
            .replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
            .replace('&quot;', '"').replace('&#39;', "'").replace('&nbsp;', ' '))
    return _clean_response(text)


# ---------------------------------------------------------------------------
# Credential Helpers
# ---------------------------------------------------------------------------

def _registry_headers():
    api_key = os.getenv("SMITHERY_API_KEY") or SMITHERY_API_KEY
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _smithery_available() -> bool:
    return bool(os.getenv("SMITHERY_API_KEY") or SMITHERY_API_KEY)


def _check_api_key() -> str | None:
    if not _smithery_available():
        return "No SMITHERY_API_KEY set. Run: key('SMITHERY_API_KEY', 'your-key')"
    return None


def _to_env_var(k: str) -> str:
    s = re.sub(r'([a-z])([A-Z])', r'\1_\2', k)
    s = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1_\2', s)
    return s.upper()


def _save_to_env(env_var: str, value: str) -> None:
    try:
        try:
            with open(ENV_PATH, 'r') as f:
                lines = f.readlines()
        except FileNotFoundError:
            lines = []
        found = False
        for i, line in enumerate(lines):
            if line.startswith(f"{env_var}="):
                lines[i] = f"{env_var}={value}\n"
                found = True
                break
        if not found:
            if lines and not lines[-1].endswith('\n'):
                lines.append('\n')
            lines.append(f"{env_var}={value}\n")
        with open(ENV_PATH, 'w') as f:
            f.writelines(lines)
    except OSError:
        pass
    os.environ[env_var] = value


def _resolve_config(credentials: dict, user_config: dict) -> tuple:
    resolved = dict(user_config)
    for cred_key in credentials:
        if not resolved.get(cred_key):
            val = os.getenv(_to_env_var(cred_key))
            if val:
                resolved[cred_key] = val
    missing = {k: v for k, v in credentials.items() if not resolved.get(k)}
    return resolved, missing


def _credentials_guide(server_id: str, credentials: dict, resolved: dict) -> str:
    missing = {k: v for k, v in credentials.items() if not resolved.get(k)}
    if not missing:
        return ""
    first_var = _to_env_var(next(iter(missing)))
    lines = [f"Server '{server_id}' needs credentials:"]
    for cred_key, desc in missing.items():
        env = _to_env_var(cred_key)
        lines.append(f"  {cred_key} → {env}" + (f"  ({desc[:80]})" if desc else ""))
    example = "{" + ", ".join(f'"{k}": "val"' for k in missing) + "}"
    lines += [
        "",
        f"Save permanently:  key('{first_var}', 'your-value')",
        f"Or inline:  call('{server_id}', '<tool>', {{...}}, {example})",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Registries
# ---------------------------------------------------------------------------

class SmitheryRegistry(BaseRegistry):
    async def search(self, query: str, limit: int) -> list:
        if not _smithery_available():
            return []
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    f"{REGISTRY_BASE}/servers",
                    params={"q": f"{query} is:verified", "pageSize": limit},
                    headers=_registry_headers(),
                    timeout=15.0,
                )
                r.raise_for_status()
                data = r.json()
        except Exception:
            return []

        results = []
        for s in data.get("servers", []):
            qname = s.get("qualifiedName", "")
            if not qname:
                continue
            credentials = {}
            for conn in s.get("connections", []):
                for k, val in conn.get("configSchema", {}).get("properties", {}).items():
                    credentials[k] = val.get("description", "")
            remote = s.get("remote", False)
            results.append(ServerInfo(
                id=qname,
                name=s.get("displayName") or qname,
                description=(s.get("description") or "").strip()[:MAX_EXPLORE_DESC],
                source="smithery",
                transport="http" if remote else "stdio",
                url=f"https://server.smithery.ai/{qname}" if remote else "",
                install_cmd=[],
                credentials=credentials,
                tools=[],
                token_cost=0,
            ))
        return results

    async def get_server(self, id: str):
        if not _smithery_available():
            return None
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    f"{REGISTRY_BASE}/servers/{id}",
                    headers=_registry_headers(),
                    timeout=15.0,
                )
                r.raise_for_status()
                s = r.json()
        except Exception:
            return None

        credentials = {}
        for conn in s.get("connections", []):
            for k, val in conn.get("configSchema", {}).get("properties", {}).items():
                credentials[k] = val.get("description", "")
        tools = s.get("tools") or []
        remote = s.get("remote", False)
        qname = s.get("qualifiedName", id)
        return ServerInfo(
            id=qname,
            name=s.get("displayName") or qname,
            description=(s.get("description") or "").strip(),
            source="smithery",
            transport="http" if remote else "stdio",
            url=f"https://server.smithery.ai/{qname}" if remote else "",
            install_cmd=[],
            credentials=credentials,
            tools=tools,
            token_cost=_estimate_tokens(tools),
        )


class NpmRegistry(BaseRegistry):
    """Search npm for MCP server packages — no auth required."""

    async def search(self, query: str, limit: int) -> list:
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    "https://registry.npmjs.org/-/v1/search",
                    params={"text": f"mcp-server {query}", "size": limit * 2},
                    timeout=15.0,
                )
                r.raise_for_status()
                data = r.json()
        except Exception:
            return []

        results = []
        for obj in data.get("objects", []):
            pkg = obj.get("package", {})
            name = pkg.get("name", "")
            if not name:
                continue
            keywords = [k.lower() for k in (pkg.get("keywords") or [])]
            if not any(k in ("mcp", "model-context-protocol", "mcp-server") for k in keywords):
                continue
            desc = (pkg.get("description") or "").strip()[:MAX_EXPLORE_DESC]
            results.append(ServerInfo(
                id=name,
                name=name,
                description=desc,
                source="npm",
                transport="stdio",
                url="",
                install_cmd=["npx", "-y", name],
                credentials={},
                tools=[],
                token_cost=0,
            ))
            if len(results) >= limit:
                break
        return results

    async def get_server(self, id: str):
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    f"https://registry.npmjs.org/{id}",
                    timeout=15.0,
                )
                r.raise_for_status()
                pkg = r.json()
        except Exception:
            return None

        latest = pkg.get("dist-tags", {}).get("latest", "")
        version_data = pkg.get("versions", {}).get(latest, {})
        desc = (version_data.get("description") or pkg.get("description") or "").strip()
        return ServerInfo(
            id=id,
            name=id,
            description=desc,
            source="npm",
            transport="stdio",
            url="",
            install_cmd=["npx", "-y", id],
            credentials={},
            tools=[],
            token_cost=0,
        )


class MultiRegistry(BaseRegistry):
    """Fan out to all registries, dedup by name, Smithery results first."""

    def __init__(self):
        self._registries = [SmitheryRegistry(), NpmRegistry()]

    async def search(self, query: str, limit: int) -> list:
        tasks = [reg.search(query, limit) for reg in self._registries]
        all_results = await asyncio.gather(*tasks, return_exceptions=True)
        seen = set()
        smithery_results, npm_results = [], []
        for batch in all_results:
            if isinstance(batch, Exception):
                continue
            for srv in batch:
                k = re.sub(r'[^a-z0-9]', '', srv.name.lower())
                if k not in seen:
                    seen.add(k)
                    if srv.source == "smithery":
                        smithery_results.append(srv)
                    else:
                        npm_results.append(srv)
        return (smithery_results + npm_results)[:limit]

    async def get_server(self, id: str):
        for reg in self._registries:
            result = await reg.get_server(id)
            if result:
                return result
        return None


_registry = MultiRegistry()


# ---------------------------------------------------------------------------
# Transports
# ---------------------------------------------------------------------------

class HTTPSSETransport(BaseTransport):
    """Execute tool calls on remote Smithery-hosted MCP servers via HTTP+SSE."""

    def __init__(self, qualified_name: str):
        self.qualified_name = qualified_name

    async def execute(self, tool: str, args: dict, config: dict) -> str:
        api_key = os.getenv("SMITHERY_API_KEY") or SMITHERY_API_KEY
        config_b64 = base64.urlsafe_b64encode(
            json.dumps(config).encode()
        ).decode().rstrip("=")
        base_url = (
            f"https://server.smithery.ai/{self.qualified_name}"
            f"?config={config_b64}&api_key={api_key}"
        )
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }

        def _parse_sse(text: str) -> dict | None:
            for line in text.splitlines():
                if line.startswith("data:"):
                    try:
                        return json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        pass
            return None

        async def _post(client, payload, session_id=None):
            hdrs = dict(headers)
            if session_id:
                hdrs["mcp-session-id"] = session_id
            return await client.post(
                base_url, content=json.dumps(payload), headers=hdrs, timeout=30.0
            )

        async def _run():
            async with httpx.AsyncClient() as client:
                r = await _post(client, {
                    "jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "chameleon", "version": "1.0.0"},
                    },
                })
                if r.status_code in (401, 403):
                    raise PermissionError(f"HTTP {r.status_code}")
                r.raise_for_status()

                session_id = r.headers.get("mcp-session-id")
                init_msg = _parse_sse(r.text)
                if init_msg and "error" in init_msg:
                    raise RuntimeError(f"Initialize failed: {init_msg['error']}")

                await _post(client, {
                    "jsonrpc": "2.0", "method": "notifications/initialized", "params": {},
                }, session_id)

                r2 = await _post(client, {
                    "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {"name": tool, "arguments": args},
                }, session_id)
                r2.raise_for_status()

                msg = _parse_sse(r2.text)
                if msg is None:
                    raise RuntimeError(f"Empty response: {r2.text[:200]}")
                return msg

        try:
            response = await asyncio.wait_for(_run(), timeout=30.0)
        except asyncio.TimeoutError:
            return f"Timeout connecting to {self.qualified_name}. Server may be sleeping — try again."
        except PermissionError:
            srv = await SmitheryRegistry().get_server(self.qualified_name)
            if srv and srv.credentials:
                resolved, missing = _resolve_config(srv.credentials, config)
                if missing:
                    return _credentials_guide(self.qualified_name, srv.credentials, resolved)
            return (
                f"Auth failed for {self.qualified_name}. "
                "Check SMITHERY_API_KEY at smithery.ai/account/api-keys"
            )
        except Exception as e:
            return f"Failed to connect to {self.qualified_name}: {e}"

        if "error" in response:
            err_obj = response["error"]
            return f"Error from {self.qualified_name}/{tool}: {err_obj.get('message', json.dumps(err_obj))}"

        result = response.get("result", {})
        content = result.get("content", [])
        if content:
            text_parts = [c.get("text", "") for c in content if c.get("type") == "text"]
            raw = "\n".join(text_parts) if text_parts else json.dumps(content, indent=2)
        else:
            raw = json.dumps(result, indent=2)

        tokens_out = _estimate_tokens(json.dumps({"tool": tool, "args": args}))
        tokens_in = _estimate_tokens(raw)
        session["stats"]["total_calls"] += 1
        session["stats"]["tokens_sent"] += tokens_out
        session["stats"]["tokens_received"] += tokens_in

        return _truncate(_clean_response(raw))


class StdioTransport(BaseTransport):
    """Execute tool calls on local MCP servers via stdio subprocess + JSON-RPC."""

    def __init__(self, install_cmd: list):
        self.install_cmd = install_cmd

    @staticmethod
    def _frame(msg: dict) -> bytes:
        return json.dumps(msg).encode() + b"\n"

    @staticmethod
    async def _read_response(reader, expected_id: int, timeout: float = 30.0) -> dict | None:
        """Read lines from stdout, skipping notifications, until we find expected_id."""
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                return None
            try:
                line = await asyncio.wait_for(reader.readline(), timeout=remaining)
            except asyncio.TimeoutError:
                return None
            if not line:
                return None
            try:
                msg = json.loads(line.decode().strip())
                if msg.get("id") == expected_id:
                    return msg
                # Skip notifications (no id) and other messages
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass  # Skip malformed lines

    async def execute(self, tool: str, args: dict, config: dict) -> str:
        try:
            proc = await asyncio.create_subprocess_exec(
                *self.install_cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            return f"Cannot find '{self.install_cmd[0]}'. Is node/npx installed?"
        except Exception as e:
            return f"Failed to start {self.install_cmd[0]}: {e}"

        try:
            # 1. Initialize (allow extra time for first-run package download)
            init_req = {
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "chameleon", "version": "1.0.0"},
                },
            }
            proc.stdin.write(self._frame(init_req))
            await proc.stdin.drain()

            init_resp = await self._read_response(proc.stdout, expected_id=1, timeout=60.0)
            if init_resp is None:
                return f"No initialize response from {self.install_cmd[0]}"
            if "error" in init_resp:
                return f"Initialize error from {self.install_cmd[0]}: {init_resp['error']}"

            # 2. Notify initialized
            proc.stdin.write(self._frame(
                {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
            ))
            await proc.stdin.drain()

            # 3. Call tool
            proc.stdin.write(self._frame({
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": tool, "arguments": args},
            }))
            await proc.stdin.drain()

            tool_resp = await self._read_response(proc.stdout, expected_id=2, timeout=30.0)
            if tool_resp is None:
                return f"No response from {self.install_cmd[0]} for tool '{tool}'"
            if "error" in tool_resp:
                err = tool_resp["error"]
                return f"Tool error: {err.get('message', json.dumps(err))}"

            result = tool_resp.get("result", {})
            content = result.get("content", [])
            if content:
                text_parts = [c.get("text", "") for c in content if c.get("type") == "text"]
                raw = "\n".join(text_parts) if text_parts else json.dumps(content, indent=2)
            else:
                raw = json.dumps(result, indent=2)

            tokens_in = _estimate_tokens(raw)
            session["stats"]["total_calls"] += 1
            session["stats"]["tokens_received"] += tokens_in

            return _truncate(_clean_response(raw))

        except Exception as e:
            return f"Stdio transport error: {e}"
        finally:
            try:
                proc.stdin.close()
                proc.kill()
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Fetch Helper
# ---------------------------------------------------------------------------

async def _try_axonmcp(url: str, intent: str) -> str | None:
    axon = shutil.which("axon-mcp")
    if not axon:
        return None
    try:
        cmd = [axon, "browse", url]
        if intent:
            cmd += ["--intent", intent]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=20.0)
        result = stdout.decode().strip()
        return result if result else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Morph Helpers
# ---------------------------------------------------------------------------

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
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "chameleon", "version": "1.0.0"},
            },
        }
        proc.stdin.write(json.dumps(init_req).encode() + b"\n")
        await proc.stdin.drain()

        init_resp = await StdioTransport._read_response(proc.stdout, expected_id=1, timeout=60.0)
        if not init_resp or "error" in init_resp:
            return []

        proc.stdin.write(json.dumps(
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
        ).encode() + b"\n")
        await proc.stdin.drain()

        proc.stdin.write(json.dumps(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        ).encode() + b"\n")
        await proc.stdin.drain()

        tools_resp = await StdioTransport._read_response(proc.stdout, expected_id=2, timeout=30.0)
        if not tools_resp or "error" in tools_resp:
            return []

        return tools_resp.get("result", {}).get("tools", [])

    except Exception:
        return []
    finally:
        try:
            proc.stdin.close()
            proc.kill()
            await asyncio.wait_for(proc.wait(), timeout=5.0)
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


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def search(query: str, registry: str = "all", limit: int = 5) -> str:
    """Search for MCP servers. registry: 'all'|'smithery'|'npm'."""
    if registry == "smithery":
        reg = SmitheryRegistry()
    elif registry == "npm":
        reg = NpmRegistry()
    else:
        reg = _registry

    servers = await reg.search(query, limit)
    if not servers:
        return f"No servers found for '{query}'. Try a different query or registry."

    lines = [f"SERVERS — '{query}' ({len(servers)} found)\n"]
    for s in servers:
        creds = ", ".join(s.credentials.keys()) if s.credentials else "free"
        lines.append(f"{s.id} | {s.name} — {s.description} | {s.source}/{s.transport} | creds: {creds}")
        session["explored"][s.id] = {"name": s.name, "desc": s.description, "status": "explored"}

    lines.append(f"\ninspect('<id>') for details | call('<id>', '<tool>', args) to call")
    return "\n".join(lines)


@mcp.tool()
async def inspect(server_id: str) -> str:
    """Show a server's tools, credentials, and token cost."""
    srv = await _registry.get_server(server_id)
    if srv is None:
        return f"Server '{server_id}' not found. Use search() to find servers."

    lines = [
        f"{srv.name} ({srv.id})",
        f"Source: {srv.source} | Transport: {srv.transport}",
        f"Description: {srv.description[:200]}",
        "",
    ]

    if srv.credentials:
        lines.append("CREDENTIALS REQUIRED")
        for cred_key, desc in srv.credentials.items():
            lines.append(f"  {cred_key} → {_to_env_var(cred_key)}" + (f": {desc[:80]}" if desc else ""))
        lines.append("")
    else:
        lines += ["CREDENTIALS: none required", ""]

    if srv.transport == "stdio":
        cmd_str = " ".join(srv.install_cmd) if srv.install_cmd else f"npx -y {srv.id}"
        lines += [f"RUN: {cmd_str}", ""]

    if srv.tools:
        lines.append(f"TOOLS ({len(srv.tools)})")
        for t in srv.tools:
            tname = t.get("name", "?")
            tdesc = (t.get("description") or "")[:MAX_INSPECT_DESC]
            params = list((t.get("inputSchema") or {}).get("properties", {}).keys())
            pstr = f"({', '.join(params)})" if params else ""
            lines.append(f"  {tname}{pstr} — {tdesc}")
        lines.append(f"\nToken cost: ~{srv.token_cost} tokens")
    else:
        lines.append("TOOLS: not listed in registry")

    session["explored"][srv.id] = {"name": srv.name, "desc": srv.description, "status": "inspected"}
    return "\n".join(lines)


@mcp.tool()
async def call(
    server_id: str,
    tool_name: str,
    arguments: dict = {},
    config: dict = {},
) -> str:
    """Call a tool on an MCP server (remote HTTP or local stdio). Creds auto-loaded from env."""
    srv = await _registry.get_server(server_id)
    credentials = srv.credentials if srv else {}

    resolved_config, missing = _resolve_config(credentials, config)
    if missing:
        return _credentials_guide(server_id, credentials, resolved_config)

    if srv and srv.transport == "stdio":
        cmd = srv.install_cmd or ["npx", "-y", server_id]
        transport: BaseTransport = StdioTransport(cmd)
    else:
        transport = HTTPSSETransport(server_id)

    result = await transport.execute(tool_name, arguments, resolved_config)

    prior = session["grown"].get(server_id, {"calls": 0})
    session["grown"][server_id] = {
        "last_tool": tool_name,
        "calls": prior["calls"] + 1,
        "status": "active",
    }
    return result


@mcp.tool()
async def run(
    package: str,
    tool_name: str,
    arguments: dict = {},
) -> str:
    """Run a tool from a local npm/pip package directly (no registry lookup).

    package: npm name (npx) or 'uvx:package-name' for Python uv packages.
    """
    if package.startswith("uvx:"):
        cmd = ["uvx", package[4:]]
    else:
        cmd = ["npx", "-y", package]

    transport = StdioTransport(cmd)
    result = await transport.execute(tool_name, arguments, {})

    prior = session["grown"].get(package, {"calls": 0})
    session["grown"][package] = {
        "last_tool": tool_name,
        "calls": prior["calls"] + 1,
        "status": "active",
    }
    return result


@mcp.tool()
async def fetch(url: str, intent: str = "") -> str:
    """Fetch a URL and return compressed content (~500 tokens vs ~25K raw HTML)."""
    raw_estimate = 6000  # typical webpage token count before compression

    axon_result = await _try_axonmcp(url, intent)
    if axon_result:
        saved = max(0, raw_estimate - _estimate_tokens(axon_result))
        session["stats"]["tokens_saved_browse"] += saved
        return axon_result

    # Fallback: httpx + HTML stripping
    try:
        async with httpx.AsyncClient(follow_redirects=True, verify=certifi.where()) as client:
            r = await client.get(
                url, timeout=15.0, headers={"User-Agent": "Mozilla/5.0"}
            )
            r.raise_for_status()
            text = r.text
    except Exception as e:
        return f"Failed to fetch {url}: {e}"

    stripped = _strip_html(text)
    result = _truncate(stripped, max_tokens=1500)
    saved = max(0, raw_estimate - _estimate_tokens(result))
    session["stats"]["tokens_saved_browse"] += saved

    header = f"[{url}]" + (f" — intent: {intent}" if intent else "")
    return f"{header}\n\n{result}"


@mcp.tool()
async def skill(qualified_name: str) -> str:
    """Inject a Smithery skill into context. Requires API key."""
    err = _check_api_key()
    if err:
        return err

    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{REGISTRY_BASE}/skills/{qualified_name}",
                headers=_registry_headers(),
                timeout=15.0,
            )
            r.raise_for_status()
            skill_meta = r.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return f"Skill '{qualified_name}' not found."
        return f"Registry error: {e.response.status_code}"
    except Exception as e:
        return f"Failed to fetch skill: {e}"

    skill_name = skill_meta.get("name") or skill_meta.get("displayName") or qualified_name
    skill_desc = (skill_meta.get("description") or "").strip()

    content = None
    content_url = (skill_meta.get("contentUrl") or skill_meta.get("url")
                   or skill_meta.get("content_url"))
    if content_url:
        try:
            async with httpx.AsyncClient() as client:
                rc = await client.get(content_url, timeout=15.0)
                rc.raise_for_status()
                content = rc.text
        except Exception:
            content = None

    if not content:
        content = (skill_meta.get("content") or skill_meta.get("markdown")
                   or skill_meta.get("text"))

    if not content:
        return "\n".join([
            f"Skill: {skill_name} ({qualified_name})",
            f"Description: {skill_desc}" if skill_desc else "",
            "Warning: could not fetch skill content.",
            json.dumps(skill_meta, indent=2),
        ])

    token_estimate = len(content) // 4
    session["skills"][qualified_name] = {
        "name": skill_name,
        "content": content,
        "tokens": token_estimate,
        "installed_at": datetime.utcnow().isoformat(),
    }

    lines = [
        f"Skill injected: {skill_name} ({qualified_name})",
        f"Context cost: ~{token_estimate:,} tokens",
    ]
    if skill_desc:
        lines.append(f"Description: {skill_desc}")
    lines += ["", "--- SKILL CONTENT ---", "", content]
    return "\n".join(lines)


@mcp.tool()
async def key(env_var: str, value: str) -> str:
    """Save an API key to .env for persistent use. e.g. key('EXA_API_KEY', 'sk-...')"""
    var = env_var.upper().replace(" ", "_")
    _save_to_env(var, value)
    return f"Saved: {var} written to .env and active for this session."


@mcp.tool()
async def auto(
    task: str,
    tool_name: str = "",
    arguments: dict = {},
    server_hint: str = "",
    keys: dict = {},
) -> str:
    """Auto-discover and call the best server for a task. Full pipeline in one call."""
    for env_var, value in keys.items():
        _save_to_env(env_var.upper(), str(value))

    if server_hint:
        srv = await _registry.get_server(server_hint)
        if srv:
            server_id, server_name, credentials = srv.id, srv.name, srv.credentials
        else:
            server_id, server_name, credentials = server_hint, server_hint, {}
    else:
        if _smithery_available():
            servers = await SmitheryRegistry().search(task, limit=3)
        else:
            servers = await NpmRegistry().search(task, limit=3)
        if not servers:
            note = "" if _smithery_available() else " (npm-only — set SMITHERY_API_KEY for Smithery results)"
            return f"No servers found for '{task}'{note}. Use search() or provide server_hint."
        best = servers[0]
        server_id, server_name, credentials = best.id, best.name, best.credentials
        session["explored"][server_id] = {
            "name": server_name, "desc": best.description, "status": "harvested"
        }

    resolved_config, missing = _resolve_config(credentials, {})
    if missing:
        missing_vars = {_to_env_var(k): v for k, v in missing.items()}
        lines = [f"Server '{server_id}' needs keys:", ""]
        for ev, desc in missing_vars.items():
            lines.append(f"  {ev}" + (f": {desc[:60]}" if desc else ""))
        args_repr = json.dumps(arguments) if arguments else "{}"
        lines += [
            "",
            "Retry:",
            f'  auto("{task}", "{tool_name}", {args_repr},',
            f'    server_hint="{server_id}",',
            '    keys={' + ", ".join(f'"{k}": "val"' for k in missing_vars) + '})',
        ]
        return "\n".join(lines)

    if not tool_name:
        srv = await _registry.get_server(server_id)
        tools = (srv.tools if srv else []) or []
        if tools:
            tool_lines = [f"  {t['name']} — {(t.get('description') or '')[:80]}" for t in tools]
            return "\n".join([
                f"{server_name} ({server_id}) ready. Available tools:",
                "",
                *tool_lines,
                "",
                f'Call: auto("{task}", "<tool>", args, server_hint="{server_id}")',
            ])
        return f"{server_id} ready (no tools listed). Use call() to call tools directly."

    srv = await _registry.get_server(server_id)
    if srv and srv.transport == "stdio":
        cmd = srv.install_cmd or ["npx", "-y", server_id]
        transport: BaseTransport = StdioTransport(cmd)
    else:
        transport = HTTPSSETransport(server_id)

    result = await transport.execute(tool_name, arguments, resolved_config)

    prior = session["grown"].get(server_id, {"calls": 0})
    session["grown"][server_id] = {
        "last_tool": tool_name,
        "calls": prior["calls"] + 1,
        "status": "active",
    }
    return result


@mcp.tool()
async def morph(server_id: str, ctx: Context) -> str:
    """Take a server's form — register its tools directly."""
    # 1. Fetch server info
    srv = await _registry.get_server(server_id)
    if srv is None:
        return f"Server '{server_id}' not found. Use search() to find servers."

    # 2. Get tool list — use registry data if available, else fetch via stdio
    tools = srv.tools or []
    if not tools:
        if srv.transport == "stdio":
            cmd = srv.install_cmd or ["npx", "-y", server_id]
            tools = await _fetch_tools_list(cmd)
        if not tools:
            return f"No tools found for '{server_id}'. Try inspect('{server_id}') first."

    # 3. Drop previous form
    _do_shed()

    # 4. Resolve credentials
    resolved_config, missing = _resolve_config(srv.credentials, {})
    if missing:
        creds_msg = _credentials_guide(server_id, srv.credentials, resolved_config)
        return f"Cannot morph into '{server_id}' — missing credentials:\n\n{creds_msg}"

    # 5. Build transport
    if srv.transport == "stdio":
        cmd = srv.install_cmd or ["npx", "-y", server_id]
        transport: BaseTransport = StdioTransport(cmd)
    else:
        transport = HTTPSSETransport(server_id)

    # 6. Register proxy tools, handling name collisions with base tools
    sanitized = re.sub(r'[^a-z0-9_]', '_', server_id.lower())
    registered = []
    for tool_schema in tools:
        raw_name = tool_schema.get("name", "")
        if not raw_name:
            continue
        proxy_name = f"{sanitized}_{raw_name}" if raw_name in _BASE_TOOL_NAMES else raw_name
        proxy = _make_proxy(server_id, tool_schema, transport, resolved_config, proxy_name)
        try:
            mcp.add_tool(proxy)
            registered.append(proxy_name)
        except Exception:
            pass  # skip tools that fail to register

    if not registered:
        return f"No tools could be registered from '{server_id}'."

    session["morphed_tools"] = registered
    session["current_form"] = server_id

    # 7. Notify client that tool list has changed
    try:
        await ctx.session.send_tool_list_changed()
    except Exception:
        pass

    lines = [
        f"Morphed into '{server_id}' — {len(registered)} tool(s) registered:",
        *[f"  {t}" for t in registered],
        "",
        "Call them directly, or use shed() to return to base form.",
    ]
    return "\n".join(lines)


@mcp.tool()
async def shed(ctx: Context) -> str:
    """Drop current form and remove morphed tools."""
    if not session["morphed_tools"]:
        return "Already in base form."
    form = session["current_form"]
    removed = _do_shed()
    try:
        await ctx.session.send_tool_list_changed()
    except Exception:
        pass
    return f"Shed '{form}'. Removed: {', '.join(removed)}"


@mcp.tool()
async def status() -> str:
    """Show current form, active connections, token stats."""
    explored = session["explored"]
    skills_data = session["skills"]
    grown = session["grown"]
    stats = session["stats"]
    current_form = session["current_form"]
    morphed = session["morphed_tools"]

    lines = ["CHAMELEON MCP STATUS", ""]

    if current_form:
        lines.append(f"CURRENT FORM: {current_form}")
        lines.append(f"MORPHED TOOLS ({len(morphed)}): {', '.join(morphed)}")
        lines.append("")
    else:
        lines += ["CURRENT FORM: base (no morph active)", ""]

    if explored:
        lines.append(f"EXPLORED ({len(explored)})")
        for sid, info in explored.items():
            lines.append(f"  {sid} [{info.get('status', '?')}]")
        lines.append("")

    if grown:
        lines.append(f"ACTIVE NODES ({len(grown)})")
        for sid, info in grown.items():
            lines.append(
                f"  {sid} | {info.get('calls', 0)} calls | last: {info.get('last_tool', '—')}"
            )
        lines.append("")

    skill_tokens = 0
    if skills_data:
        lines.append(f"SKILLS ({len(skills_data)})")
        for sid, info in skills_data.items():
            t = info.get("tokens", 0)
            skill_tokens += t
            lines.append(f"  {sid} ~{t:,} tokens")
        lines.append("")

    lines += [
        "PERFORMANCE STATS",
        f"  Total calls:       {stats['total_calls']}",
        f"  Tokens sent:     ~{stats['tokens_sent']:,}",
        f"  Tokens received: ~{stats['tokens_received']:,}",
        f"  Saved via fetch: ~{stats['tokens_saved_browse']:,}",
        f"  Skill context:   ~{skill_tokens:,} tokens",
    ]
    if stats["total_calls"] > 0:
        avg = stats["tokens_received"] // stats["total_calls"]
        lines.append(f"  Avg response:    ~{avg} tokens")

    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()
