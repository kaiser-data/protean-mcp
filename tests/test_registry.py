"""Tests for SmitheryRegistry and NpmRegistry."""
import json
import os
import pytest
import respx
import httpx

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from server import SmitheryRegistry, NpmRegistry, ServerInfo


# ---------------------------------------------------------------------------
# SmitheryRegistry tests
# ---------------------------------------------------------------------------

class TestSmitheryRegistryNoKey:
    async def test_search_without_api_key_returns_empty(self, monkeypatch):
        monkeypatch.delenv("SMITHERY_API_KEY", raising=False)
        # Patch module-level constant too
        import server
        original = server.SMITHERY_API_KEY
        server.SMITHERY_API_KEY = None
        try:
            reg = SmitheryRegistry()
            results = await reg.search("anything", 5)
            assert results == []
        finally:
            server.SMITHERY_API_KEY = original

    async def test_get_server_without_api_key_returns_none(self, monkeypatch):
        monkeypatch.delenv("SMITHERY_API_KEY", raising=False)
        import server
        original = server.SMITHERY_API_KEY
        server.SMITHERY_API_KEY = None
        try:
            reg = SmitheryRegistry()
            result = await reg.get_server("any/server")
            assert result is None
        finally:
            server.SMITHERY_API_KEY = original


class TestSmitheryRegistryWithMock:
    async def test_search_returns_server_list(self, monkeypatch):
        monkeypatch.setenv("SMITHERY_API_KEY", "test-key-123")
        server_list = {
            "servers": [
                {
                    "qualifiedName": "test-org/my-server",
                    "displayName": "My Server",
                    "description": "A great server",
                    "remote": False,
                    "connections": [],
                }
            ]
        }
        with respx.mock:
            respx.get("https://registry.smithery.ai/servers").mock(
                return_value=httpx.Response(200, json=server_list)
            )
            reg = SmitheryRegistry()
            results = await reg.search("test", 5)

        assert len(results) == 1
        assert results[0].id == "test-org/my-server"
        assert results[0].transport == "stdio"
        assert results[0].source == "smithery"

    async def test_search_remote_server_has_http_transport(self, monkeypatch):
        monkeypatch.setenv("SMITHERY_API_KEY", "test-key-123")
        server_list = {
            "servers": [
                {
                    "qualifiedName": "test-org/remote-server",
                    "displayName": "Remote Server",
                    "description": "Hosted remotely",
                    "remote": True,
                    "connections": [],
                }
            ]
        }
        with respx.mock:
            respx.get("https://registry.smithery.ai/servers").mock(
                return_value=httpx.Response(200, json=server_list)
            )
            reg = SmitheryRegistry()
            results = await reg.search("remote", 5)

        assert results[0].transport == "http"
        assert "server.smithery.ai" in results[0].url

    async def test_search_extracts_credentials(self, monkeypatch):
        monkeypatch.setenv("SMITHERY_API_KEY", "test-key-123")
        server_list = {
            "servers": [
                {
                    "qualifiedName": "org/cred-server",
                    "displayName": "Cred Server",
                    "description": "Needs creds",
                    "remote": False,
                    "connections": [
                        {
                            "configSchema": {
                                "properties": {
                                    "apiKey": {"description": "Your API key"},
                                    "token": {"description": "Auth token"},
                                }
                            }
                        }
                    ],
                }
            ]
        }
        with respx.mock:
            respx.get("https://registry.smithery.ai/servers").mock(
                return_value=httpx.Response(200, json=server_list)
            )
            reg = SmitheryRegistry()
            results = await reg.search("cred", 5)

        assert "apiKey" in results[0].credentials
        assert "token" in results[0].credentials

    async def test_search_http_error_returns_empty(self, monkeypatch):
        monkeypatch.setenv("SMITHERY_API_KEY", "test-key-123")
        with respx.mock:
            respx.get("https://registry.smithery.ai/servers").mock(
                return_value=httpx.Response(500, text="Internal Server Error")
            )
            reg = SmitheryRegistry()
            results = await reg.search("test", 5)
        assert results == []


# ---------------------------------------------------------------------------
# NpmRegistry tests
# ---------------------------------------------------------------------------

class TestNpmRegistry:
    async def test_search_returns_mcp_packages_only(self):
        npm_response = {
            "objects": [
                {
                    "package": {
                        "name": "mcp-server-filesystem",
                        "description": "MCP filesystem server",
                        "keywords": ["mcp", "mcp-server"],
                    }
                },
                {
                    "package": {
                        "name": "random-package",
                        "description": "Not an MCP package",
                        "keywords": ["utility"],
                    }
                },
            ]
        }
        with respx.mock:
            respx.get("https://registry.npmjs.org/-/v1/search").mock(
                return_value=httpx.Response(200, json=npm_response)
            )
            reg = NpmRegistry()
            results = await reg.search("filesystem", 5)

        assert len(results) == 1
        assert results[0].id == "mcp-server-filesystem"
        assert results[0].transport == "stdio"
        assert results[0].source == "npm"
        assert results[0].install_cmd == ["npx", "-y", "mcp-server-filesystem"]

    async def test_get_server_returns_server_info(self):
        npm_detail = {
            "name": "mcp-server-test",
            "description": "Test MCP server",
            "dist-tags": {"latest": "1.2.3"},
            "versions": {
                "1.2.3": {"description": "Test MCP server v1.2.3"}
            },
        }
        with respx.mock:
            respx.get("https://registry.npmjs.org/mcp-server-test").mock(
                return_value=httpx.Response(200, json=npm_detail)
            )
            reg = NpmRegistry()
            result = await reg.get_server("mcp-server-test")

        assert result is not None
        assert result.id == "mcp-server-test"
        assert result.install_cmd == ["npx", "-y", "mcp-server-test"]

    async def test_get_server_http_error_returns_none(self):
        with respx.mock:
            respx.get("https://registry.npmjs.org/nonexistent-pkg").mock(
                return_value=httpx.Response(404, text="Not Found")
            )
            reg = NpmRegistry()
            result = await reg.get_server("nonexistent-pkg")
        assert result is None
