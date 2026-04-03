"""Shared test fixtures for Chameleon MCP tests."""
import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx

# ---------------------------------------------------------------------------
# Shared subprocess mock helpers (importable or usable as fixtures)
# ---------------------------------------------------------------------------

def make_mock_process(returncode=None):
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


def make_stdout_with_responses(responses: list[dict]):
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


@pytest.fixture
def mock_process():
    """Pytest fixture: a mock asyncio subprocess (alive by default)."""
    return make_mock_process(returncode=None)


# ---------------------------------------------------------------------------
# Mock subprocess helpers
# ---------------------------------------------------------------------------

class MockProcess:
    """Minimal asyncio subprocess mock for stdio transport tests."""

    def __init__(self, responses: list[dict], returncode: int = 0):
        self._responses = iter(responses)
        self.returncode = returncode
        self.stdin = MockStdin()
        self.stdout = MockStdout(responses)
        self.stderr = MockStdout([])
        self.pid = 12345

    async def wait(self):
        return self.returncode

    def kill(self):
        self.returncode = -9


class MockStdin:
    def write(self, data: bytes):
        pass

    async def drain(self):
        pass

    def close(self):
        pass


class MockStdout:
    def __init__(self, responses: list[dict]):
        self._lines = iter(
            (json.dumps(r) + "\n").encode() for r in responses
        )

    async def readline(self) -> bytes:
        try:
            return next(self._lines)
        except StopIteration:
            return b""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_smithery_server():
    """Mock Smithery registry responses."""
    server_list = {
        "servers": [
            {
                "qualifiedName": "test-org/test-server",
                "displayName": "Test Server",
                "description": "A test MCP server for unit tests",
                "remote": False,
                "connections": [
                    {
                        "configSchema": {
                            "properties": {
                                "apiKey": {"description": "Your API key"}
                            }
                        }
                    }
                ],
            }
        ]
    }
    server_detail = {
        "qualifiedName": "test-org/test-server",
        "displayName": "Test Server",
        "description": "A test MCP server for unit tests",
        "remote": False,
        "connections": [
            {
                "configSchema": {
                    "properties": {
                        "apiKey": {"description": "Your API key"}
                    }
                }
            }
        ],
        "tools": [
            {
                "name": "do_thing",
                "description": "Does a thing",
                "inputSchema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            }
        ],
    }
    with respx.mock:
        respx.get("https://registry.smithery.ai/servers").mock(
            return_value=httpx.Response(200, json=server_list)
        )
        respx.get("https://registry.smithery.ai/servers/test-org/test-server").mock(
            return_value=httpx.Response(200, json=server_detail)
        )
        yield server_list, server_detail


@pytest.fixture
def mock_npm_server():
    """Mock npm registry responses."""
    npm_search = {
        "objects": [
            {
                "package": {
                    "name": "mcp-server-test",
                    "description": "A test npm MCP server",
                    "keywords": ["mcp", "mcp-server"],
                }
            }
        ]
    }
    npm_detail = {
        "name": "mcp-server-test",
        "description": "A test npm MCP server",
        "dist-tags": {"latest": "1.0.0"},
        "versions": {
            "1.0.0": {"description": "A test npm MCP server"}
        },
    }
    with respx.mock:
        respx.get("https://registry.npmjs.org/-/v1/search").mock(
            return_value=httpx.Response(200, json=npm_search)
        )
        respx.get("https://registry.npmjs.org/mcp-server-test").mock(
            return_value=httpx.Response(200, json=npm_detail)
        )
        yield npm_search, npm_detail


@pytest.fixture
def stdio_init_responses():
    """Standard init + tool list JSON-RPC responses for a stdio process mock."""
    return [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "serverInfo": {"name": "test", "version": "1.0"},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "tools": [
                    {
                        "name": "hello",
                        "description": "Say hello",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"name": {"type": "string"}},
                            "required": ["name"],
                        },
                    }
                ]
            },
        },
    ]


@pytest.fixture
def stdio_tool_call_responses():
    """Standard init + tool call JSON-RPC responses."""
    return [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "serverInfo": {"name": "test", "version": "1.0"},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "content": [{"type": "text", "text": "Hello, world!"}]
            },
        },
    ]
