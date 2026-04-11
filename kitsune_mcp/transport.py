import asyncio
import contextlib
import datetime
import json
import os
import re
import time
import urllib.parse
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import kitsune_mcp.credentials as _creds
from kitsune_mcp.constants import (
    MCP_CLIENT_INFO,
    MCP_PROTOCOL_VERSION,
    POOL_MAX_IDLE_SECONDS,
    POOL_MAX_PROCESSES,
    TIMEOUT_HTTP_TOOL,
    TIMEOUT_PROMPT_LIST,
    TIMEOUT_RESOURCE_LIST,
    TIMEOUT_STDIO_INIT,
    TIMEOUT_STDIO_TOOL,
)
from kitsune_mcp.credentials import SMITHERY_API_KEY, _credentials_guide, _resolve_config
from kitsune_mcp.registry import SmitheryRegistry
from kitsune_mcp.session import session
from kitsune_mcp.utils import (
    _clean_response,
    _estimate_tokens,
    _extract_content,
    _get_http_client,
    _truncate,
)

# ---------------------------------------------------------------------------
# Install command validation
# ---------------------------------------------------------------------------

_SHELL_METACHAR_RE = re.compile(r'[&;|$`\n]')
_PATH_TRAVERSAL_RE = re.compile(r'\.\.[/\\]')


def _validate_install_cmd(cmd: list[str]) -> None:
    """Validate argv[0] of an install command for shell injection and path traversal.

    Only checks the executable name (argv[0]) — arguments are passed directly to
    create_subprocess_exec and are not subject to shell interpretation.

    Raises ValueError if the command looks dangerous.
    """
    if not cmd:
        raise ValueError("Empty install command")
    argv0 = cmd[0]
    if _SHELL_METACHAR_RE.search(argv0):
        raise ValueError(f"Shell metacharacter in command: {argv0!r}")
    if _PATH_TRAVERSAL_RE.search(argv0):
        raise ValueError(f"Path traversal in command: {argv0!r}")


class BaseTransport(ABC):
    @abstractmethod
    async def execute(self, tool: str, args: dict, config: dict) -> str: ...


# ---------------------------------------------------------------------------
# Persistent Process Pool
# ---------------------------------------------------------------------------

@dataclass
class _PoolEntry:
    proc: asyncio.subprocess.Process
    install_cmd: list
    started_at: float           # time.monotonic()
    next_id: int = 3            # 1=init, 2=initialized notify
    call_count: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    name: str = ""
    last_used_at: float = field(default_factory=time.monotonic)
    dotenv_revision: int = 0    # _creds._dotenv_revision at spawn time

    def pid(self) -> int | None:
        return self.proc.pid

    def uptime_seconds(self) -> float:
        return time.monotonic() - self.started_at

    def is_alive(self) -> bool:
        return self.proc.returncode is None


_process_pool: dict[str, _PoolEntry] = {}   # keyed by json(install_cmd, sort_keys=True)


def _evict_stale_pool_entries() -> list[str]:
    """Remove dead or long-idle processes from the pool. Returns evicted keys."""
    now = time.monotonic()
    to_remove = [
        k for k, e in _process_pool.items()
        if not e.is_alive() or (now - e.last_used_at) > POOL_MAX_IDLE_SECONDS
    ]
    for k in to_remove:
        with contextlib.suppress(Exception):
            _process_pool[k].proc.kill()
        _process_pool.pop(k, None)
    # Hard cap: if still over limit, evict oldest by last_used_at
    if len(_process_pool) > POOL_MAX_PROCESSES:
        oldest = sorted(_process_pool.items(), key=lambda kv: kv[1].last_used_at)
        for k, e in oldest[:len(_process_pool) - POOL_MAX_PROCESSES]:
            with contextlib.suppress(Exception):
                e.proc.kill()
            _process_pool.pop(k, None)
    return to_remove


async def _ping(entry: "_PoolEntry", timeout: float = 2.0) -> bool:
    """Send tools/list to a live pool entry and confirm it responds. Non-blocking."""
    if not entry.is_alive():
        return False
    try:
        async with entry.lock:
            msg_id = entry.next_id
            entry.next_id += 1
            entry.proc.stdin.write(
                json.dumps({"jsonrpc": "2.0", "id": msg_id, "method": "tools/list", "params": {}}).encode() + b"\n"
            )
            await entry.proc.stdin.drain()
            resp = await asyncio.wait_for(
                _read_stdio_response(entry.proc.stdout, msg_id),
                timeout=timeout,
            )
            return resp is not None and "error" not in resp
    except Exception:
        return False


async def _read_stdio_response(reader, expected_id: int, timeout: float = 30.0) -> dict | None:
    """Standalone version of StdioTransport._read_response for use before class definition."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            return None
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=remaining)
        except TimeoutError:
            return None
        if not line:
            return None
        try:
            msg = json.loads(line.decode().strip())
            if msg.get("id") == expected_id:
                return msg
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass


# ---------------------------------------------------------------------------
# Smithery Connect helpers (new API — api.smithery.ai/connect)
# ---------------------------------------------------------------------------

_SMITHERY_API_BASE = "https://api.smithery.ai"
_smithery_namespace_cache: str | None = None
_smithery_service_token: str = ""
_smithery_token_expires: float = 0.0
_smithery_connections: dict[str, str] = {}  # conn_id → mcpUrl (session cache)


async def _smithery_namespace() -> str | None:
    """Return the user's first Smithery namespace (cached for the session)."""
    global _smithery_namespace_cache
    if _smithery_namespace_cache:
        return _smithery_namespace_cache
    api_key = os.getenv("SMITHERY_API_KEY") or SMITHERY_API_KEY
    if not api_key:
        return None
    try:
        r = await _get_http_client().get(
            f"{_SMITHERY_API_BASE}/namespaces",
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            timeout=10,
        )
        r.raise_for_status()
        namespaces = r.json().get("namespaces", [])
        if namespaces:
            _smithery_namespace_cache = namespaces[0]["name"]
    except Exception:
        pass
    return _smithery_namespace_cache


async def _smithery_service_token() -> str:
    """Return a valid service token with mcp scope (cached, auto-refreshed)."""
    global _smithery_service_token, _smithery_token_expires
    now = time.monotonic()
    if _smithery_service_token and now < _smithery_token_expires:
        return _smithery_service_token
    api_key = os.getenv("SMITHERY_API_KEY") or SMITHERY_API_KEY
    if not api_key:
        return ""
    try:
        r = await _get_http_client().post(
            f"{_SMITHERY_API_BASE}/tokens",
            json={"name": "kitsune-mcp", "scopes": ["mcp"]},
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        _smithery_service_token = data["token"]
        expires_at = datetime.datetime.fromisoformat(
            data["expiresAt"].replace("Z", "+00:00")
        )
        ttl = (
            expires_at - datetime.datetime.now(datetime.UTC)
        ).total_seconds()
        _smithery_token_expires = now + max(ttl - 300, 60)  # refresh 5 min early
    except Exception:
        _smithery_service_token = ""
    return _smithery_service_token


def _smithery_conn_id(qualified_name: str) -> str:
    """Stable, URL-safe connection ID derived from a qualified server name."""
    sanitized = re.sub(r"[^a-z0-9-]", "-", qualified_name.lower()).strip("-")
    return f"kitsune-{sanitized}"[:64]


def _build_mcp_url(deployment_url: str, config: dict) -> str:
    """Append non-null config values as query parameters to the deployment URL."""
    clean = {k: v for k, v in config.items() if v is not None}
    if not clean:
        return deployment_url
    qs = urllib.parse.urlencode(clean)
    sep = "&" if "?" in deployment_url else "?"
    return f"{deployment_url}{sep}{qs}"


async def _ensure_smithery_connection(
    namespace: str, conn_id: str, mcp_url: str
) -> bool:
    """Create or update a Smithery Connect connection. Returns True on success."""
    # Skip if we already set up this conn_id with the same URL this session
    if _smithery_connections.get(conn_id) == mcp_url:
        return True
    api_key = os.getenv("SMITHERY_API_KEY") or SMITHERY_API_KEY
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    client = _get_http_client()
    url = f"{_SMITHERY_API_BASE}/connect/{namespace}/{conn_id}"
    try:
        r = await client.put(url, json={"mcpUrl": mcp_url}, headers=headers, timeout=15)
        if r.status_code == 409:
            # URL mismatch — delete existing and recreate
            await client.delete(url, headers=headers, timeout=10)
            r = await client.put(url, json={"mcpUrl": mcp_url}, headers=headers, timeout=15)
        r.raise_for_status()
        _smithery_connections[conn_id] = mcp_url
        return True
    except Exception:
        return False


def _parse_sse(text: str) -> dict | None:
    """Extract the first JSON payload from an SSE response body."""
    for line in text.splitlines():
        if line.startswith("data:"):
            try:
                return json.loads(line[5:].strip())
            except json.JSONDecodeError:
                pass
    return None


# ---------------------------------------------------------------------------
# Transports
# ---------------------------------------------------------------------------

class HTTPSSETransport(BaseTransport):
    """Execute tool calls via the Smithery Connect API (api.smithery.ai/connect).

    Uses the new run.tools deployment URLs and per-user namespaced connections
    rather than the legacy server.smithery.ai/*/mcp endpoint.
    """

    def __init__(self, qualified_name: str, deployment_url: str = ""):
        self.qualified_name = qualified_name
        # deployment_url comes from the registry's deploymentUrl field
        # e.g. "https://brave.run.tools"
        self.deployment_url = deployment_url or f"https://{qualified_name}.run.tools"

    async def _connect_endpoint(self, config: dict) -> tuple[str, str] | None:
        """Return (connect_mcp_url, service_token) or None on failure."""
        namespace = await _smithery_namespace()
        if not namespace:
            return None
        token = await _smithery_service_token()
        if not token:
            return None
        mcp_url = _build_mcp_url(self.deployment_url, config)
        conn_id = _smithery_conn_id(self.qualified_name)
        ok = await _ensure_smithery_connection(namespace, conn_id, mcp_url)
        if not ok:
            return None
        endpoint = f"{_SMITHERY_API_BASE}/connect/{namespace}/{conn_id}/mcp"
        return endpoint, token

    async def execute(self, tool: str, args: dict, config: dict) -> str:
        result = await self._connect_endpoint(config)
        if result is None:
            return (
                f"Cannot reach {self.qualified_name} via Smithery Connect. "
                "Check SMITHERY_API_KEY at smithery.ai/account/api-keys"
            )
        endpoint, token = result
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }

        async def _post(client, payload, session_id=None):
            hdrs = dict(headers)
            if session_id:
                hdrs["mcp-session-id"] = session_id
            return await client.post(
                endpoint, content=json.dumps(payload), headers=hdrs, timeout=TIMEOUT_HTTP_TOOL
            )

        async def _run():
            client = _get_http_client()
            r = await _post(client, {
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": MCP_CLIENT_INFO,
                },
            })
            if r.status_code in (401, 403):
                raise PermissionError(f"HTTP {r.status_code}")
            r.raise_for_status()

            mcp_session_id = r.headers.get("mcp-session-id")
            init_msg = _parse_sse(r.text)
            if init_msg and "error" in init_msg:
                raise RuntimeError(f"Initialize failed: {init_msg['error']}")

            await _post(client, {
                "jsonrpc": "2.0", "method": "notifications/initialized", "params": {},
            }, mcp_session_id)

            r2 = await _post(client, {
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": tool, "arguments": args},
            }, mcp_session_id)
            r2.raise_for_status()

            msg = _parse_sse(r2.text)
            if msg is None:
                raise RuntimeError(f"Empty response: {r2.text[:200]}")
            return msg

        try:
            response = await asyncio.wait_for(_run(), timeout=TIMEOUT_HTTP_TOOL)
        except TimeoutError:
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

        result_data = response.get("result", {})
        raw = _extract_content(result_data)

        tokens_out = _estimate_tokens({"tool": tool, "args": args})
        tokens_in = _estimate_tokens(raw)
        session["stats"]["total_calls"] += 1
        session["stats"]["tokens_sent"] += tokens_out
        session["stats"]["tokens_received"] += tokens_in

        return _truncate(_clean_response(raw))

    async def list_tools(self, config: dict | None = None) -> list[dict]:
        """Fetch tools/list from the Smithery Connect endpoint."""
        if config is None:
            config = {}
        result = await self._connect_endpoint(config)
        if result is None:
            return []
        endpoint, token = result
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }

        async def _post(client, payload, session_id=None):
            hdrs = dict(headers)
            if session_id:
                hdrs["mcp-session-id"] = session_id
            return await client.post(
                endpoint, content=json.dumps(payload), headers=hdrs, timeout=TIMEOUT_HTTP_TOOL
            )

        async def _run() -> list[dict]:
            client = _get_http_client()
            r = await _post(client, {
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": MCP_CLIENT_INFO,
                },
            })
            if r.status_code in (401, 403):
                raise PermissionError(f"HTTP {r.status_code}")
            r.raise_for_status()
            mcp_session_id = r.headers.get("mcp-session-id")

            await _post(client, {
                "jsonrpc": "2.0", "method": "notifications/initialized", "params": {},
            }, mcp_session_id)

            r2 = await _post(client, {
                "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {},
            }, mcp_session_id)
            r2.raise_for_status()
            msg = _parse_sse(r2.text)
            if msg and "result" in msg:
                return msg["result"].get("tools", [])
            return []

        try:
            return await asyncio.wait_for(_run(), timeout=TIMEOUT_HTTP_TOOL)
        except Exception:
            return []


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
        return await _read_stdio_response(reader, expected_id, timeout)

    async def execute(self, tool: str, args: dict, config: dict) -> str:
        try:
            _validate_install_cmd(self.install_cmd)
        except ValueError as e:
            return str(e)
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
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": MCP_CLIENT_INFO,
                },
            }
            proc.stdin.write(self._frame(init_req))
            await proc.stdin.drain()

            init_resp = await self._read_response(proc.stdout, expected_id=1, timeout=TIMEOUT_STDIO_INIT)
            if init_resp is None:
                return f"No initialize response from {self.install_cmd[0]}"
            if "error" in init_resp:
                return f"Initialize error from {self.install_cmd[0]}: {init_resp['error']}"

            # 2. Notify initialized + 3. Call tool — batched into one flush
            proc.stdin.write(self._frame(
                {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
            ))
            proc.stdin.write(self._frame({
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": tool, "arguments": args},
            }))
            await proc.stdin.drain()

            tool_resp = await self._read_response(proc.stdout, expected_id=2, timeout=TIMEOUT_STDIO_TOOL)
            if tool_resp is None:
                return f"No response from {self.install_cmd[0]} for tool '{tool}'"
            if "error" in tool_resp:
                err = tool_resp["error"]
                return f"Tool error: {err.get('message', json.dumps(err))}"

            result = tool_resp.get("result", {})
            raw = _extract_content(result)

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
                await asyncio.wait_for(proc.wait(), timeout=TIMEOUT_RESOURCE_LIST)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Persistent Stdio Transport
# ---------------------------------------------------------------------------

class PersistentStdioTransport(BaseTransport):
    """Execute tool calls on a long-lived stdio subprocess.

    The process is shared across calls via _process_pool, keyed by install_cmd.
    stderr is inherited from parent by default.
    Each pool entry has an asyncio.Lock to serialize concurrent calls.
    """

    def __init__(self, install_cmd: list, inherit_stderr: bool = True):
        self.install_cmd = install_cmd
        self.inherit_stderr = inherit_stderr
        self._pool_key = json.dumps(install_cmd, sort_keys=True)

    @staticmethod
    def _frame(msg: dict) -> bytes:
        return json.dumps(msg).encode() + b"\n"

    async def _start_process(self) -> _PoolEntry:
        """Spawn subprocess, run MCP handshake, store in pool. Returns entry."""
        try:
            _validate_install_cmd(self.install_cmd)
        except ValueError as e:
            raise RuntimeError(str(e)) from e
        try:
            proc = await asyncio.create_subprocess_exec(
                *self.install_cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=None if self.inherit_stderr else asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            raise RuntimeError(f"Cannot find '{self.install_cmd[0]}'. Is it installed?") from None
        except Exception as e:
            raise RuntimeError(f"Failed to start {self.install_cmd[0]}: {e}") from e

        entry = _PoolEntry(
            proc=proc,
            install_cmd=self.install_cmd,
            started_at=time.monotonic(),
        )

        # MCP initialize handshake
        proc.stdin.write(self._frame({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": MCP_CLIENT_INFO,
            },
        }))
        await proc.stdin.drain()

        init_resp = await StdioTransport._read_response(proc.stdout, expected_id=1, timeout=TIMEOUT_STDIO_INIT)
        if init_resp is None:
            proc.kill()
            raise RuntimeError(f"No initialize response from {self.install_cmd[0]}")
        if "error" in init_resp:
            proc.kill()
            raise RuntimeError(f"Initialize error: {init_resp['error']}")

        proc.stdin.write(self._frame(
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
        ))
        await proc.stdin.drain()

        entry.dotenv_revision = _creds._dotenv_revision
        _process_pool[self._pool_key] = entry
        return entry

    async def _get_or_start(self) -> _PoolEntry:
        """Return existing live pool entry or start a new one.

        Evicts entries that are dead, idle too long, or spawned before a .env
        change — so new credentials are always picked up on the next call.
        """
        _evict_stale_pool_entries()
        entry = _process_pool.get(self._pool_key)
        if entry is not None and entry.is_alive():
            if entry.dotenv_revision != _creds._dotenv_revision:
                # .env changed since this process was spawned — kill and respawn
                with contextlib.suppress(Exception):
                    entry.proc.kill()
                _process_pool.pop(self._pool_key, None)
            else:
                return entry
        return await self._start_process()

    async def list_tools(self) -> list[dict]:
        """Ask live process for its tool list via tools/list."""
        entry = await self._get_or_start()
        async with entry.lock:
            msg_id = entry.next_id
            entry.next_id += 1
            entry.proc.stdin.write(self._frame(
                {"jsonrpc": "2.0", "id": msg_id, "method": "tools/list", "params": {}}
            ))
            await entry.proc.stdin.drain()

            resp = await StdioTransport._read_response(
                entry.proc.stdout, expected_id=msg_id, timeout=TIMEOUT_STDIO_TOOL
            )
            if not resp or "error" in resp:
                return []
            return resp.get("result", {}).get("tools", [])

    async def list_resources(self) -> list[dict]:
        """Ask live process for its resource list via resources/list."""
        entry = await self._get_or_start()
        async with entry.lock:
            msg_id = entry.next_id
            entry.next_id += 1
            entry.proc.stdin.write(self._frame(
                {"jsonrpc": "2.0", "id": msg_id, "method": "resources/list", "params": {}}
            ))
            await entry.proc.stdin.drain()
            resp = await StdioTransport._read_response(
                entry.proc.stdout, expected_id=msg_id, timeout=10.0
            )
            if not resp or "error" in resp:
                return []
            return resp.get("result", {}).get("resources", [])

    async def read_resource(self, uri: str) -> str:
        """Read a single resource by URI via resources/read."""
        entry = await self._get_or_start()
        async with entry.lock:
            msg_id = entry.next_id
            entry.next_id += 1
            entry.proc.stdin.write(self._frame(
                {"jsonrpc": "2.0", "id": msg_id, "method": "resources/read",
                 "params": {"uri": uri}}
            ))
            await entry.proc.stdin.drain()
            resp = await StdioTransport._read_response(
                entry.proc.stdout, expected_id=msg_id, timeout=10.0
            )
            if not resp or "error" in resp:
                return ""
            contents = resp.get("result", {}).get("contents", [])
            # Resource content items use mimeType, not type — extract any text field present
            return "\n".join(c["text"] for c in contents if "text" in c)

    async def list_prompts(self) -> list[dict]:
        """Ask live process for its prompt list via prompts/list."""
        entry = await self._get_or_start()
        async with entry.lock:
            msg_id = entry.next_id
            entry.next_id += 1
            entry.proc.stdin.write(self._frame(
                {"jsonrpc": "2.0", "id": msg_id, "method": "prompts/list", "params": {}}
            ))
            await entry.proc.stdin.drain()
            resp = await StdioTransport._read_response(
                entry.proc.stdout, expected_id=msg_id, timeout=TIMEOUT_PROMPT_LIST
            )
            if not resp or "error" in resp:
                return []
            return resp.get("result", {}).get("prompts", [])

    async def get_prompt(self, name: str, arguments: dict) -> list[dict]:
        """Fetch a rendered prompt by name via prompts/get."""
        entry = await self._get_or_start()
        async with entry.lock:
            msg_id = entry.next_id
            entry.next_id += 1
            entry.proc.stdin.write(self._frame(
                {"jsonrpc": "2.0", "id": msg_id, "method": "prompts/get",
                 "params": {"name": name, "arguments": arguments}}
            ))
            await entry.proc.stdin.drain()
            resp = await StdioTransport._read_response(
                entry.proc.stdout, expected_id=msg_id, timeout=TIMEOUT_PROMPT_LIST
            )
            if not resp or "error" in resp:
                return []
            return resp.get("result", {}).get("messages", [])

    async def execute(self, tool: str, args: dict, config: dict) -> str:
        try:
            entry = await self._get_or_start()
        except RuntimeError as e:
            return str(e)

        for attempt in range(2):  # one retry on mid-call process death
            async with entry.lock:
                if not entry.is_alive():
                    try:
                        entry = await self._start_process()
                    except RuntimeError as e:
                        return f"Reconnect failed: {e}"

                msg_id = entry.next_id
                entry.next_id += 1

                try:
                    entry.proc.stdin.write(self._frame({
                        "jsonrpc": "2.0", "id": msg_id, "method": "tools/call",
                        "params": {"name": tool, "arguments": args},
                    }))
                    await entry.proc.stdin.drain()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    if attempt == 0:
                        # Process died mid-write — evict and retry
                        with contextlib.suppress(Exception):
                            entry.proc.kill()
                        _process_pool.pop(self._pool_key, None)
                        try:
                            entry = await self._start_process()
                        except RuntimeError as e:
                            return f"Reconnect failed: {e}"
                        continue
                    return f"Failed to send to {self.install_cmd[0]} after reconnect"
                except Exception as e:
                    return f"Failed to send to {self.install_cmd[0]}: {e}"

                tool_resp = await StdioTransport._read_response(
                    entry.proc.stdout, expected_id=msg_id, timeout=TIMEOUT_STDIO_TOOL
                )
                if tool_resp is None:
                    if attempt == 0 and not entry.is_alive():
                        # Process died while we were waiting — retry once
                        _process_pool.pop(self._pool_key, None)
                        try:
                            entry = await self._start_process()
                        except RuntimeError as e:
                            return f"Reconnect failed: {e}"
                        continue
                    return f"No response from {self.install_cmd[0]} for tool '{tool}'"
                if "error" in tool_resp:
                    err = tool_resp["error"]
                    return f"Tool error: {err.get('message', json.dumps(err))}"

                entry.call_count += 1
                entry.last_used_at = time.monotonic()
                result = tool_resp.get("result", {})
                raw = _extract_content(result)

                tokens_in = _estimate_tokens(raw)
                session["stats"]["total_calls"] += 1
                session["stats"]["tokens_received"] += tokens_in
                return _truncate(_clean_response(raw))

        return f"Failed to call '{tool}' after reconnect"  # unreachable but satisfies type checker


class WebSocketTransport(BaseTransport):
    """One-shot MCP tool call over WebSocket (ws:// or wss://).

    Requires the 'websockets' package: pip install websockets
    """

    def __init__(self, url: str):
        self.url = url

    async def execute(self, tool: str, args: dict, config: dict) -> str:
        try:
            import websockets  # type: ignore[import]
        except ImportError:
            return "WebSocket transport requires 'websockets': pip install websockets"

        try:
            async with websockets.connect(self.url, open_timeout=TIMEOUT_STDIO_INIT) as ws:
                # Initialize handshake
                await ws.send(json.dumps({
                    "jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {
                        "protocolVersion": MCP_PROTOCOL_VERSION,
                        "clientInfo": MCP_CLIENT_INFO,
                        "capabilities": {},
                    },
                }))
                await asyncio.wait_for(ws.recv(), timeout=TIMEOUT_STDIO_INIT)

                # Initialized notification
                await ws.send(json.dumps({
                    "jsonrpc": "2.0", "method": "notifications/initialized", "params": {},
                }))

                # Tool call
                await ws.send(json.dumps({
                    "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {"name": tool, "arguments": args},
                }))
                raw = await asyncio.wait_for(ws.recv(), timeout=TIMEOUT_HTTP_TOOL)
        except Exception as e:
            return f"WebSocket error ({self.url}): {e}"

        try:
            msg = json.loads(raw)
        except Exception:
            return str(raw)

        if "error" in msg:
            err = msg["error"]
            return f"Error {err.get('code', '')}: {err.get('message', str(err))}"

        result = msg.get("result", {})
        raw_text = _extract_content(result)

        tokens_in = _estimate_tokens(raw_text)
        session["stats"]["total_calls"] += 1
        session["stats"]["tokens_received"] += tokens_in
        return _truncate(_clean_response(raw_text))


class DockerTransport(BaseTransport):
    """Run an MCP server inside a Docker container via stdio.

    Uses `docker run --rm -i --memory <limit>` so the container is:
    - ephemeral (--rm auto-removes it on exit)
    - RAM-capped (default 512m, override via config["memory"])
    - pooled through PersistentStdioTransport — shares the 10-process hard cap

    Usage:
        call("docker:mcp/my-image:latest", "tool_name", {...})
        call("docker:my-image", "tool_name", {...}, config={"memory": "256m"})
    """

    def __init__(self, image: str):
        self.image = image

    def _build_cmd(self, config: dict) -> list[str]:
        memory = str(config.get("memory") or "512m")
        cmd = [
            "docker", "run", "--rm", "-i",
            "--label", "kitsune-mcp=1",
            "--memory", memory,
        ]
        for k, v in (config.get("env") or {}).items():
            cmd += ["-e", f"{k}={v}"]
        cmd.append(self.image)
        return cmd

    async def execute(self, tool: str, args: dict, config: dict) -> str:
        cmd = self._build_cmd(config)
        return await PersistentStdioTransport(cmd).execute(tool, args, config)
