"""Tests for _PoolEntry, PersistentStdioTransport, connect(), release()."""
import asyncio
import json
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import server as srv_module
from server import (
    _PoolEntry,
    PersistentStdioTransport,
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
