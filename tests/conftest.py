"""Shared test fixtures for Chameleon MCP tests."""
import asyncio
import json
import pytest
import respx
import httpx

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
