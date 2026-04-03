import asyncio
import base64
import contextlib
import json
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from chameleon_mcp.constants import (
    MCP_CLIENT_INFO,
    MCP_PROTOCOL_VERSION,
    POOL_MAX_IDLE_SECONDS,
    POOL_MAX_PROCESSES,
    TIMEOUT_HTTP_TOOL,
    TIMEOUT_RESOURCE_LIST,
    TIMEOUT_STDIO_INIT,
    TIMEOUT_STDIO_TOOL,
)
from chameleon_mcp.credentials import SMITHERY_API_KEY, _credentials_guide, _resolve_config
from chameleon_mcp.registry import SmitheryRegistry
from chameleon_mcp.session import session
from chameleon_mcp.utils import (
    _clean_response,
    _estimate_tokens,
    _extract_content,
    _get_http_client,
    _truncate,
)


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
            f"?config={config_b64}"
        )
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {api_key}",
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
                base_url, content=json.dumps(payload), headers=hdrs, timeout=TIMEOUT_HTTP_TOOL
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

        result = response.get("result", {})
        raw = _extract_content(result)

        tokens_out = _estimate_tokens({"tool": tool, "args": args})
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
        return await _read_stdio_response(reader, expected_id, timeout)

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

        _process_pool[self._pool_key] = entry
        return entry

    async def _get_or_start(self) -> _PoolEntry:
        """Return existing live pool entry or start a new one (evicts stale entries first)."""
        _evict_stale_pool_entries()
        entry = _process_pool.get(self._pool_key)
        if entry is not None and entry.is_alive():
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

    async def execute(self, tool: str, args: dict, config: dict) -> str:
        try:
            entry = await self._get_or_start()
        except RuntimeError as e:
            return str(e)

        async with entry.lock:
            if not entry.is_alive():
                # Auto-reconnect once
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
            except Exception as e:
                return f"Failed to send to {self.install_cmd[0]}: {e}"

            tool_resp = await StdioTransport._read_response(
                entry.proc.stdout, expected_id=msg_id, timeout=TIMEOUT_STDIO_TOOL
            )
            if tool_resp is None:
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
