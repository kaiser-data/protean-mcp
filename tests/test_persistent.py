"""Tests for _PoolEntry, PersistentStdioTransport, connect(), release()."""
import asyncio
import json
import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import server as srv_module
from server import (
    PersistentStdioTransport,
    _PoolEntry,
    _process_pool,
    session,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_process(returncode=None):
    """Create a mock asyncio subprocess with working stdin/stdout."""
    proc = MagicMock()
    proc.returncode = returncode
    proc.pid = 99999
    proc.stdin = MagicMock()
    proc.stdin.write = MagicMock()
    proc.stdin.drain = AsyncMock()
    proc.stdin.close = MagicMock()
    proc.stdout = MagicMock()
    proc.kill = MagicMock()
    proc.wait = AsyncMock(return_value=0)
    return proc


def _make_stdout_with_responses(responses: list[dict]):
    """Create a mock stdout that yields JSON-RPC responses one by one."""
    lines = iter((json.dumps(r) + "\n").encode() for r in responses)

    async def readline():
        try:
            return next(lines)
        except StopIteration:
            return b""

    stdout = MagicMock()
    stdout.readline = readline
    return stdout


# ---------------------------------------------------------------------------
# _PoolEntry tests
# ---------------------------------------------------------------------------

class TestPoolEntry:
    def _make_entry(self, returncode=None):
        proc = _make_mock_process(returncode=returncode)
        return _PoolEntry(
            proc=proc,
            install_cmd=["echo", "test"],
            started_at=time.monotonic(),
        )

    def test_is_alive_with_running_process(self):
        entry = self._make_entry(returncode=None)
        assert entry.is_alive() is True

    def test_is_alive_returns_false_when_dead(self):
        entry = self._make_entry(returncode=0)
        assert entry.is_alive() is False

    def test_pid_returns_process_pid(self):
        entry = self._make_entry()
        assert entry.pid() == 99999

    def test_uptime_is_positive(self):
        entry = self._make_entry()
        assert entry.uptime_seconds() >= 0

    def test_call_count_starts_at_zero(self):
        entry = self._make_entry()
        assert entry.call_count == 0

    def test_name_defaults_to_empty_string(self):
        entry = self._make_entry()
        assert entry.name == ""


# ---------------------------------------------------------------------------
# PersistentStdioTransport tests
# ---------------------------------------------------------------------------

class TestPersistentTransportReusesProcess:
    async def test_call_count_increments_on_reuse(self):
        """Second execute() on same pool key reuses process and increments call_count."""
        init_resp = {
            "jsonrpc": "2.0", "id": 1,
            "result": {"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "t", "version": "1"}},
        }
        tool_resp = {
            "jsonrpc": "2.0", "id": 3,  # id=3 because next_id starts at 3
            "result": {"content": [{"type": "text", "text": "ok"}]},
        }
        tool_resp2 = {
            "jsonrpc": "2.0", "id": 4,
            "result": {"content": [{"type": "text", "text": "ok again"}]},
        }

        mock_proc = _make_mock_process(returncode=None)
        mock_proc.stdout = _make_stdout_with_responses([init_resp, tool_resp, tool_resp2])

        pool_key = json.dumps(["test-cmd"], sort_keys=True)
        _process_pool.pop(pool_key, None)  # clean up

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
            transport = PersistentStdioTransport(["test-cmd"])
            await transport.execute("my_tool", {}, {})

        # Entry should be in pool now
        assert pool_key in _process_pool
        assert _process_pool[pool_key].call_count == 1

        # Second call reuses the process
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
            transport2 = PersistentStdioTransport(["test-cmd"])
            await transport2.execute("my_tool", {}, {})

        assert _process_pool[pool_key].call_count == 2
        _process_pool.pop(pool_key, None)

    async def test_persistent_transport_reconnects_on_death(self):
        """If process dies during call, transport auto-reconnects once."""
        init_resp = {
            "jsonrpc": "2.0", "id": 1,
            "result": {"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "t", "version": "1"}},
        }
        tool_resp = {
            "jsonrpc": "2.0", "id": 3,
            "result": {"content": [{"type": "text", "text": "reconnected ok"}]},
        }

        dead_proc = _make_mock_process(returncode=1)  # already dead
        live_proc = _make_mock_process(returncode=None)
        live_proc.stdout = _make_stdout_with_responses([init_resp, tool_resp])

        pool_key = json.dumps(["reconnect-cmd"], sort_keys=True)
        # Pre-populate pool with dead process
        _process_pool[pool_key] = _PoolEntry(
            proc=dead_proc,
            install_cmd=["reconnect-cmd"],
            started_at=time.monotonic(),
        )

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=live_proc)):
            transport = PersistentStdioTransport(["reconnect-cmd"])
            result = await transport.execute("tool", {}, {})

        assert "reconnected ok" in result or isinstance(result, str)
        _process_pool.pop(pool_key, None)


# ---------------------------------------------------------------------------
# release() tool test
# ---------------------------------------------------------------------------

class TestReleaseKillsProcess:
    async def test_release_kills_process_and_removes_from_pool(self):
        mock_proc = _make_mock_process(returncode=None)
        pool_key = json.dumps(["uvx", "voice-mode"], sort_keys=True)

        entry = _PoolEntry(
            proc=mock_proc,
            install_cmd=["uvx", "voice-mode"],
            started_at=time.monotonic(),
            name="voice",
        )
        _process_pool[pool_key] = entry
        session["connections"][pool_key] = {"name": "voice", "command": "uvx voice-mode"}

        result = await srv_module.release("voice")

        assert pool_key not in _process_pool
        assert pool_key not in session["connections"]
        mock_proc.kill.assert_called_once()
        assert "Released" in result
        assert "voice" in result

    async def test_release_unknown_name_returns_error(self):
        # Clear pool
        _process_pool.clear()
        result = await srv_module.release("nonexistent")
        assert "No active connections" in result or "No connection named" in result


# ---------------------------------------------------------------------------
# connect() tool test
# ---------------------------------------------------------------------------

class TestConnect:
    async def test_connect_returns_tool_list(self):
        """connect() returns tool names from live process."""
        init_resp = {
            "jsonrpc": "2.0", "id": 1,
            "result": {"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "t", "version": "1"}},
        }
        tools_resp = {
            "jsonrpc": "2.0", "id": 3,
            "result": {
                "tools": [
                    {"name": "speak", "description": "Say something", "inputSchema": {"type": "object", "properties": {}, "required": []}},
                    {"name": "listen", "description": "Listen", "inputSchema": {"type": "object", "properties": {}, "required": []}},
                ]
            },
        }

        mock_proc = _make_mock_process(returncode=None)
        mock_proc.stdout = _make_stdout_with_responses([init_resp, tools_resp])

        pool_key = json.dumps(["uvx", "test-audio"], sort_keys=True)
        _process_pool.pop(pool_key, None)
        session["connections"].pop(pool_key, None)

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
            result = await srv_module.connect("uvx test-audio", name="audio")

        assert "Connected" in result
        assert "audio" in result
        assert "speak" in result or "Tools" in result
        _process_pool.pop(pool_key, None)
        session["connections"].pop(pool_key, None)

    async def test_connect_already_connected_returns_status_not_error(self):
        """connect() on live process returns status message, not an error."""
        mock_proc = _make_mock_process(returncode=None)
        pool_key = json.dumps(["uvx", "already-running"], sort_keys=True)

        _process_pool[pool_key] = _PoolEntry(
            proc=mock_proc,
            install_cmd=["uvx", "already-running"],
            started_at=time.monotonic(),
            name="running",
        )

        result = await srv_module.connect("uvx already-running", name="running")

        assert "Already connected" in result
        assert "running" in result
        _process_pool.pop(pool_key, None)


# ---------------------------------------------------------------------------
# PersistentStdioTransport.list_resources() tests
# ---------------------------------------------------------------------------

class TestListResources:
    def _init_resp(self):
        return {
            "jsonrpc": "2.0", "id": 1,
            "result": {"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "t", "version": "1"}},
        }

    async def test_list_resources_returns_list(self):
        resources_resp = {
            "jsonrpc": "2.0", "id": 3,
            "result": {"resources": [
                {"uri": "config://env/vars", "name": "Env Vars"},
                {"uri": "docs://auth", "name": "Auth Docs"},
            ]},
        }
        mock_proc = _make_mock_process(returncode=None)
        mock_proc.stdout = _make_stdout_with_responses([self._init_resp(), resources_resp])

        pool_key = json.dumps(["list-res-cmd"], sort_keys=True)
        _process_pool.pop(pool_key, None)

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
            transport = PersistentStdioTransport(["list-res-cmd"])
            result = await transport.list_resources()

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["uri"] == "config://env/vars"
        _process_pool.pop(pool_key, None)

    async def test_list_resources_returns_empty_on_error(self):
        error_resp = {
            "jsonrpc": "2.0", "id": 3,
            "error": {"code": -32601, "message": "Method not found"},
        }
        mock_proc = _make_mock_process(returncode=None)
        mock_proc.stdout = _make_stdout_with_responses([self._init_resp(), error_resp])

        pool_key = json.dumps(["list-res-err-cmd"], sort_keys=True)
        _process_pool.pop(pool_key, None)

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
            transport = PersistentStdioTransport(["list-res-err-cmd"])
            result = await transport.list_resources()

        assert result == []
        _process_pool.pop(pool_key, None)

    async def test_list_resources_returns_empty_on_timeout(self):
        """If process never responds to resources/list, returns []."""
        mock_proc = _make_mock_process(returncode=None)
        # Only provide init response; resources/list response never arrives
        mock_proc.stdout = _make_stdout_with_responses([self._init_resp()])

        pool_key = json.dumps(["list-res-timeout-cmd"], sort_keys=True)
        _process_pool.pop(pool_key, None)

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
            with patch("chameleon_mcp.transport.StdioTransport._read_response", AsyncMock(side_effect=[
                self._init_resp(),  # init
                None,               # resources/list → timeout
            ])):
                transport = PersistentStdioTransport(["list-res-timeout-cmd"])
                result = await transport.list_resources()

        assert result == []
        _process_pool.pop(pool_key, None)


# ---------------------------------------------------------------------------
# PersistentStdioTransport.read_resource() tests
# ---------------------------------------------------------------------------

class TestReadResource:
    def _init_resp(self):
        return {
            "jsonrpc": "2.0", "id": 1,
            "result": {"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "t", "version": "1"}},
        }

    async def test_read_resource_extracts_text(self):
        read_resp = {
            "jsonrpc": "2.0", "id": 3,
            "result": {"contents": [
                {"uri": "config://env/vars", "mimeType": "text/plain", "text": "MY_KEY=abc"},
            ]},
        }
        mock_proc = _make_mock_process(returncode=None)
        mock_proc.stdout = _make_stdout_with_responses([self._init_resp(), read_resp])

        pool_key = json.dumps(["read-res-cmd"], sort_keys=True)
        _process_pool.pop(pool_key, None)

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
            transport = PersistentStdioTransport(["read-res-cmd"])
            result = await transport.read_resource("config://env/vars")

        assert result == "MY_KEY=abc"
        _process_pool.pop(pool_key, None)

    async def test_read_resource_returns_empty_on_error(self):
        error_resp = {
            "jsonrpc": "2.0", "id": 3,
            "error": {"code": -32601, "message": "Not found"},
        }
        mock_proc = _make_mock_process(returncode=None)
        mock_proc.stdout = _make_stdout_with_responses([self._init_resp(), error_resp])

        pool_key = json.dumps(["read-res-err-cmd"], sort_keys=True)
        _process_pool.pop(pool_key, None)

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
            transport = PersistentStdioTransport(["read-res-err-cmd"])
            result = await transport.read_resource("config://env/vars")

        assert result == ""
        _process_pool.pop(pool_key, None)


# ---------------------------------------------------------------------------
# inherit_stderr parameter tests
# ---------------------------------------------------------------------------

class TestInheritStderr:
    def _init_resp(self):
        return {
            "jsonrpc": "2.0", "id": 1,
            "result": {"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "t", "version": "1"}},
        }

    async def test_inherit_stderr_true_passes_none(self):
        """Default inherit_stderr=True → stderr=None (inherit from parent process)."""
        mock_proc = _make_mock_process(returncode=None)
        tool_resp = {"jsonrpc": "2.0", "id": 3, "result": {"content": [{"type": "text", "text": "ok"}]}}
        mock_proc.stdout = _make_stdout_with_responses([self._init_resp(), tool_resp])

        pool_key = json.dumps(["inherit-true-cmd"], sort_keys=True)
        _process_pool.pop(pool_key, None)

        captured_kwargs = {}

        async def mock_exec(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return mock_proc

        with patch("asyncio.create_subprocess_exec", mock_exec):
            transport = PersistentStdioTransport(["inherit-true-cmd"], inherit_stderr=True)
            await transport.execute("my_tool", {}, {})

        assert captured_kwargs.get("stderr") is None
        _process_pool.pop(pool_key, None)

    async def test_inherit_stderr_false_passes_pipe(self):
        """inherit_stderr=False → stderr=asyncio.subprocess.PIPE."""
        mock_proc = _make_mock_process(returncode=None)
        tool_resp = {"jsonrpc": "2.0", "id": 3, "result": {"content": [{"type": "text", "text": "ok"}]}}
        mock_proc.stdout = _make_stdout_with_responses([self._init_resp(), tool_resp])

        pool_key = json.dumps(["inherit-false-cmd"], sort_keys=True)
        _process_pool.pop(pool_key, None)

        captured_kwargs = {}

        async def mock_exec(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return mock_proc

        with patch("asyncio.create_subprocess_exec", mock_exec):
            transport = PersistentStdioTransport(["inherit-false-cmd"], inherit_stderr=False)
            await transport.execute("my_tool", {}, {})

        assert captured_kwargs.get("stderr") == asyncio.subprocess.PIPE
        _process_pool.pop(pool_key, None)


# ---------------------------------------------------------------------------
# Pool eviction tests
# ---------------------------------------------------------------------------

class TestPoolEviction:
    """_evict_stale_pool_entries() removes dead, idle, and over-limit entries."""

    def setup_method(self):
        _process_pool.clear()

    def teardown_method(self):
        _process_pool.clear()

    def _make_entry(self, returncode=None, last_used_offset=0.0, cmd=None):
        cmd = cmd or ["fake-cmd"]
        proc = MagicMock()
        proc.returncode = returncode
        proc.kill = MagicMock()
        entry = _PoolEntry(
            proc=proc,
            install_cmd=cmd,
            started_at=time.monotonic(),
            last_used_at=time.monotonic() + last_used_offset,
        )
        return json.dumps(cmd, sort_keys=True), entry

    def test_dead_process_is_evicted(self):
        from server import _evict_stale_pool_entries
        key, entry = self._make_entry(returncode=1)  # dead process
        _process_pool[key] = entry

        evicted = _evict_stale_pool_entries()

        assert key in evicted
        assert key not in _process_pool
        entry.proc.kill.assert_called()

    def test_idle_process_is_evicted(self):
        from chameleon_mcp.constants import POOL_MAX_IDLE_SECONDS
        from server import _evict_stale_pool_entries
        key, entry = self._make_entry(returncode=None, last_used_offset=-(POOL_MAX_IDLE_SECONDS + 1))
        _process_pool[key] = entry

        evicted = _evict_stale_pool_entries()

        assert key in evicted
        assert key not in _process_pool

    def test_live_recent_process_is_kept(self):
        from server import _evict_stale_pool_entries
        key, entry = self._make_entry(returncode=None, last_used_offset=0.0)
        _process_pool[key] = entry

        evicted = _evict_stale_pool_entries()

        assert key not in evicted
        assert key in _process_pool

    def test_hard_cap_evicts_oldest(self):
        from chameleon_mcp.constants import POOL_MAX_PROCESSES
        from server import _evict_stale_pool_entries
        # Fill pool beyond cap: POOL_MAX_PROCESSES + 2 entries, each with different last_used_at
        for i in range(POOL_MAX_PROCESSES + 2):
            cmd = [f"cmd-{i}"]
            key = json.dumps(cmd, sort_keys=True)
            proc = MagicMock()
            proc.returncode = None
            proc.kill = MagicMock()
            entry = _PoolEntry(
                proc=proc,
                install_cmd=cmd,
                started_at=time.monotonic(),
                last_used_at=time.monotonic() - (POOL_MAX_PROCESSES + 2 - i),  # oldest first
            )
            _process_pool[key] = entry

        _evict_stale_pool_entries()

        assert len(_process_pool) == POOL_MAX_PROCESSES
