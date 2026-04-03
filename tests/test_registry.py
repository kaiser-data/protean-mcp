"""Tests for SmitheryRegistry and NpmRegistry."""
import os
import sys

import httpx
import respx

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from server import NpmRegistry, SmitheryRegistry

# ---------------------------------------------------------------------------
# SmitheryRegistry tests
# ---------------------------------------------------------------------------

class TestSmitheryRegistryNoKey:
    async def test_search_without_api_key_returns_empty(self, monkeypatch):
        import chameleon_mcp.credentials as creds
        monkeypatch.delenv("SMITHERY_API_KEY", raising=False)
        monkeypatch.setattr(creds, "SMITHERY_API_KEY", "")
        reg = SmitheryRegistry()
        results = await reg.search("anything", 5)
        assert results == []

    async def test_get_server_without_api_key_returns_none(self, monkeypatch):
        import chameleon_mcp.credentials as creds
        monkeypatch.delenv("SMITHERY_API_KEY", raising=False)
        monkeypatch.setattr(creds, "SMITHERY_API_KEY", "")
        reg = SmitheryRegistry()
        result = await reg.get_server("any/server")
        assert result is None


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


# ---------------------------------------------------------------------------
# MultiRegistry tests
# ---------------------------------------------------------------------------

class TestMultiRegistryGetServerParallel:
    """MultiRegistry.get_server() should query all registries in parallel."""

    async def test_returns_smithery_result_when_available(self, monkeypatch):
        monkeypatch.setenv("SMITHERY_API_KEY", "test-key")
        smithery_detail = {
            "qualifiedName": "exa/exa",
            "displayName": "Exa",
            "description": "Exa web search",
            "remote": True,
            "connections": [],
            "tools": [],
        }
        npm_detail = {
            "name": "exa",
            "description": "Exa npm fallback",
            "dist-tags": {"latest": "1.0.0"},
            "versions": {"1.0.0": {"description": "Exa npm fallback"}},
        }
        with respx.mock:
            respx.get("https://registry.smithery.ai/servers/exa/exa").mock(
                return_value=httpx.Response(200, json=smithery_detail)
            )
            respx.get("https://registry.npmjs.org/exa/exa").mock(
                return_value=httpx.Response(200, json=npm_detail)
            )
            from server import MultiRegistry
            reg = MultiRegistry()
            result = await reg.get_server("exa/exa")

        assert result is not None
        assert result.source == "smithery"

    async def test_falls_back_to_npm_when_smithery_unavailable(self, monkeypatch):
        monkeypatch.delenv("SMITHERY_API_KEY", raising=False)
        import chameleon_mcp.credentials as creds
        monkeypatch.setattr(creds, "SMITHERY_API_KEY", None)
        npm_detail = {
            "name": "mcp-server-brave-search",
            "description": "Brave search MCP",
            "dist-tags": {"latest": "1.0.0"},
            "versions": {"1.0.0": {"description": "Brave search MCP"}},
        }
        with respx.mock:
            respx.get("https://registry.npmjs.org/mcp-server-brave-search").mock(
                return_value=httpx.Response(200, json=npm_detail)
            )
            from server import MultiRegistry
            reg = MultiRegistry()
            result = await reg.get_server("mcp-server-brave-search")

        assert result is not None
        assert result.source == "npm"

    async def test_returns_none_when_all_fail(self, monkeypatch):
        monkeypatch.delenv("SMITHERY_API_KEY", raising=False)
        import chameleon_mcp.credentials as creds
        monkeypatch.setattr(creds, "SMITHERY_API_KEY", None)
        with respx.mock:
            respx.get("https://registry.npmjs.org/totally-unknown-pkg-xyz").mock(
                return_value=httpx.Response(404, text="Not Found")
            )
            from server import MultiRegistry
            reg = MultiRegistry()
            result = await reg.get_server("totally-unknown-pkg-xyz")

        assert result is None


class TestMultiRegistryCaching:
    """MultiRegistry TTL cache for get_server() and search()."""

    async def test_get_server_returns_cached_result(self, monkeypatch):
        monkeypatch.delenv("SMITHERY_API_KEY", raising=False)
        import chameleon_mcp.credentials as creds
        monkeypatch.setattr(creds, "SMITHERY_API_KEY", None)
        npm_detail = {
            "name": "mcp-server-cached",
            "description": "Cached server",
            "dist-tags": {"latest": "1.0.0"},
            "versions": {"1.0.0": {"description": "Cached server"}},
        }
        from server import MultiRegistry
        reg = MultiRegistry()
        with respx.mock:
            route = respx.get("https://registry.npmjs.org/mcp-server-cached").mock(
                return_value=httpx.Response(200, json=npm_detail)
            )
            first = await reg.get_server("mcp-server-cached")
            second = await reg.get_server("mcp-server-cached")

        # Network should only be hit once; second call uses cache
        assert route.call_count == 1
        assert first is not None
        assert second is first  # same object from cache

    async def test_bust_cache_clears_all(self, monkeypatch):
        monkeypatch.delenv("SMITHERY_API_KEY", raising=False)
        import chameleon_mcp.credentials as creds
        monkeypatch.setattr(creds, "SMITHERY_API_KEY", None)
        npm_detail = {
            "name": "mcp-server-bustable",
            "description": "Bustable server",
            "dist-tags": {"latest": "1.0.0"},
            "versions": {"1.0.0": {"description": "Bustable"}},
        }
        from server import MultiRegistry
        reg = MultiRegistry()
        with respx.mock:
            route = respx.get("https://registry.npmjs.org/mcp-server-bustable").mock(
                return_value=httpx.Response(200, json=npm_detail)
            )
            await reg.get_server("mcp-server-bustable")
            reg.bust_cache()
            await reg.get_server("mcp-server-bustable")

        # After bust, network is hit again
        assert route.call_count == 2

    async def test_search_returns_cached_result(self, monkeypatch):
        monkeypatch.delenv("SMITHERY_API_KEY", raising=False)
        import chameleon_mcp.credentials as creds
        monkeypatch.setattr(creds, "SMITHERY_API_KEY", None)
        npm_search = {
            "objects": [
                {
                    "package": {
                        "name": "mcp-server-filesystem",
                        "description": "Filesystem MCP server",
                        "keywords": ["mcp"],
                    }
                }
            ]
        }
        from server import MultiRegistry
        reg = MultiRegistry()
        with respx.mock:
            route = respx.get("https://registry.npmjs.org/-/v1/search").mock(
                return_value=httpx.Response(200, json=npm_search)
            )
            first = await reg.search("filesystem", 5)
            second = await reg.search("filesystem", 5)

        assert route.call_count == 1
        assert first == second


# ---------------------------------------------------------------------------
# OfficialMCPRegistry tests
# ---------------------------------------------------------------------------

class TestOfficialMCPRegistry:
    """OfficialMCPRegistry returns trusted reference servers."""

    async def test_search_filesystem_returns_official_server(self):
        from server import OfficialMCPRegistry
        reg = OfficialMCPRegistry()
        with respx.mock:
            # Allow GitHub API call (but don't require it — seed list is enough)
            respx.get("https://api.github.com/repos/modelcontextprotocol/servers/contents/src").mock(
                return_value=httpx.Response(200, json=[])
            )
            results = await reg.search("filesystem", 5)

        assert len(results) >= 1
        assert results[0].source == "official"
        assert "@modelcontextprotocol/server-filesystem" in results[0].id or "filesystem" in results[0].id.lower()

    async def test_get_server_returns_seed_entry(self):
        from server import OfficialMCPRegistry
        reg = OfficialMCPRegistry()
        result = await reg.get_server("@modelcontextprotocol/server-filesystem")

        assert result is not None
        assert result.source == "official"
        assert result.install_cmd == ["npx", "-y", "@modelcontextprotocol/server-filesystem"]

    async def test_get_server_pip_uses_uvx(self):
        from server import OfficialMCPRegistry
        reg = OfficialMCPRegistry()
        result = await reg.get_server("mcp-server-git")

        assert result is not None
        assert result.source == "official"
        assert result.install_cmd[0] == "uvx"

    async def test_get_server_unknown_returns_none(self):
        import chameleon_mcp.official_registry as oreg
        from server import OfficialMCPRegistry
        # Reset cache so the live fetch runs
        oreg._live_cache = None
        oreg._live_cache_expires = 0.0
        reg = OfficialMCPRegistry()
        with respx.mock:
            respx.get("https://api.github.com/repos/modelcontextprotocol/servers/contents/src").mock(
                return_value=httpx.Response(200, json=[])
            )
            result = await reg.get_server("totally-unknown-official-server")

        assert result is None


# ---------------------------------------------------------------------------
# PyPIRegistry tests
# ---------------------------------------------------------------------------

class TestPyPIRegistry:
    """PyPIRegistry searches PyPI for uvx-installable MCP servers."""

    _SEARCH_HTML = """
    <ul>
      <li>
        <a href="/project/mcp-server-git/">
          <span class="package-snippet__name">mcp-server-git</span>
          <span class="package-snippet__description">Git repository MCP server</span>
        </a>
      </li>
      <li>
        <a href="/project/mcp-server-fetch/">
          <span class="package-snippet__name">mcp-server-fetch</span>
          <span class="package-snippet__description">Fetch web pages via MCP</span>
        </a>
      </li>
    </ul>
    """

    async def test_search_returns_pypi_packages(self):
        from server import PyPIRegistry
        with respx.mock:
            respx.get("https://pypi.org/search/").mock(
                return_value=httpx.Response(200, text=self._SEARCH_HTML)
            )
            reg = PyPIRegistry()
            results = await reg.search("git", 5)

        assert len(results) == 2
        assert results[0].id == "mcp-server-git"
        assert results[0].source == "pypi"
        assert results[0].install_cmd == ["uvx", "mcp-server-git"]
        assert results[0].transport == "stdio"

    async def test_search_http_error_returns_empty(self):
        from server import PyPIRegistry
        with respx.mock:
            respx.get("https://pypi.org/search/").mock(
                return_value=httpx.Response(503, text="Service Unavailable")
            )
            reg = PyPIRegistry()
            results = await reg.search("anything", 5)
        assert results == []

    async def test_get_server_returns_server_info(self):
        pypi_detail = {
            "info": {
                "name": "mcp-server-git",
                "summary": "Git repository MCP server",
            }
        }
        from server import PyPIRegistry
        with respx.mock:
            respx.get("https://pypi.org/pypi/mcp-server-git/json").mock(
                return_value=httpx.Response(200, json=pypi_detail)
            )
            reg = PyPIRegistry()
            result = await reg.get_server("mcp-server-git")

        assert result is not None
        assert result.id == "mcp-server-git"
        assert result.source == "pypi"
        assert result.install_cmd == ["uvx", "mcp-server-git"]
        assert result.description == "Git repository MCP server"

    async def test_get_server_http_error_returns_none(self):
        from server import PyPIRegistry
        with respx.mock:
            respx.get("https://pypi.org/pypi/nonexistent-mcp-pkg/json").mock(
                return_value=httpx.Response(404, text="Not Found")
            )
            reg = PyPIRegistry()
            result = await reg.get_server("nonexistent-mcp-pkg")
        assert result is None
