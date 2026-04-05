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


# ---------------------------------------------------------------------------
# GitHubRegistry tests
# ---------------------------------------------------------------------------

class TestGitHubRegistry:
    """GitHubRegistry resolves github:owner/repo IDs."""

    async def test_non_github_id_returns_none(self):
        from server import GitHubRegistry
        reg = GitHubRegistry()
        result = await reg.get_server("mcp-server-filesystem")
        assert result is None

    async def test_invalid_slug_returns_none(self):
        from server import GitHubRegistry
        reg = GitHubRegistry()
        result = await reg.get_server("github:no-slash-here")
        assert result is None

    async def test_search_always_returns_empty(self):
        from server import GitHubRegistry
        reg = GitHubRegistry()
        results = await reg.search("anything", 10)
        assert results == []

    async def test_npm_repo_detected_via_package_json(self):
        from server import GitHubRegistry
        with respx.mock:
            respx.get("https://api.github.com/repos/user/my-mcp").mock(
                return_value=httpx.Response(200, json={"name": "my-mcp", "description": "A test server"})
            )
            respx.get("https://api.github.com/repos/user/my-mcp/contents/package.json").mock(
                return_value=httpx.Response(200, json={"content": ""})
            )
            reg = GitHubRegistry()
            result = await reg.get_server("github:user/my-mcp")

        assert result is not None
        assert result.source == "github"
        assert result.transport == "stdio"
        assert result.install_cmd == ["npx", "github:user/my-mcp"]
        assert result.name == "my-mcp"

    async def test_pip_repo_detected_via_pyproject_toml(self):
        import base64

        from server import GitHubRegistry
        pyproject_content = b"[project.scripts]\nmy-server = \"my_package:main\"\n"
        encoded = base64.b64encode(pyproject_content).decode()
        with respx.mock:
            respx.get("https://api.github.com/repos/user/my-pip-mcp").mock(
                return_value=httpx.Response(200, json={"name": "my-pip-mcp", "description": "pip server"})
            )
            respx.get("https://api.github.com/repos/user/my-pip-mcp/contents/package.json").mock(
                return_value=httpx.Response(404, text="Not Found")
            )
            respx.get("https://api.github.com/repos/user/my-pip-mcp/contents/pyproject.toml").mock(
                return_value=httpx.Response(200, json={"content": encoded})
            )
            reg = GitHubRegistry()
            result = await reg.get_server("github:user/my-pip-mcp")

        assert result is not None
        assert result.install_cmd[0] == "uvx"
        assert "git+https://github.com/user/my-pip-mcp" in result.install_cmd
        assert "my-server" in result.install_cmd

    async def test_fallback_to_npm_when_no_manifest(self):
        from server import GitHubRegistry
        with respx.mock:
            respx.get("https://api.github.com/repos/user/unknown-mcp").mock(
                return_value=httpx.Response(200, json={"name": "unknown-mcp", "description": ""})
            )
            respx.get("https://api.github.com/repos/user/unknown-mcp/contents/package.json").mock(
                return_value=httpx.Response(404, text="Not Found")
            )
            respx.get("https://api.github.com/repos/user/unknown-mcp/contents/pyproject.toml").mock(
                return_value=httpx.Response(404, text="Not Found")
            )
            reg = GitHubRegistry()
            result = await reg.get_server("github:user/unknown-mcp")

        assert result is not None
        assert result.install_cmd == ["npx", "github:user/unknown-mcp"]


class TestDedupKey:
    def test_strips_mcp_server_prefix(self):
        from server import _dedup_key
        assert _dedup_key("mcp-server-filesystem") == _dedup_key("filesystem")

    def test_strips_npm_scope(self):
        from server import _dedup_key
        assert _dedup_key("@modelcontextprotocol/server-filesystem") == _dedup_key("filesystem")

    def test_strips_server_prefix(self):
        from server import _dedup_key
        assert _dedup_key("server-brave-search") == _dedup_key("brave-search")

    def test_different_names_stay_different(self):
        from server import _dedup_key
        assert _dedup_key("filesystem") != _dedup_key("sqlite")


class TestRelevanceScore:
    def _make_srv(self, id, name, desc="", source="npm"):
        from server import ServerInfo
        return ServerInfo(id=id, name=name, description=desc, source=source,
                          transport="stdio", url="", install_cmd=[], credentials={},
                          tools=[], token_cost=0)

    def test_exact_name_match_scores_highest(self):
        from server import _relevance_score
        exact = self._make_srv("filesystem", "filesystem")
        partial = self._make_srv("mcp-server-filesystem", "MCP Filesystem Tools")
        assert _relevance_score(exact, "filesystem") > _relevance_score(partial, "filesystem")

    def test_official_beats_npm_same_name(self):
        from server import _relevance_score
        official = self._make_srv("filesystem", "filesystem", source="official")
        npm = self._make_srv("mcp-server-filesystem", "filesystem", source="npm")
        assert _relevance_score(official, "filesystem") > _relevance_score(npm, "filesystem")

    def test_name_match_beats_desc_only_match(self):
        from server import _relevance_score
        in_name = self._make_srv("brave-search", "brave-search", desc="web search")
        in_desc = self._make_srv("web-tools", "web-tools", desc="brave search engine")
        assert _relevance_score(in_name, "brave") > _relevance_score(in_desc, "brave")

    def test_unrelated_server_scores_low(self):
        from server import _relevance_score
        srv = self._make_srv("random-tool", "random-tool", desc="does things")
        assert _relevance_score(srv, "filesystem") < 5.0


class TestMultiRegistrySearchDedup:
    def _srv(self, id, name, source="npm"):
        from server import ServerInfo
        return ServerInfo(id=id, name=name, description="", source=source,
                          transport="stdio", url="", install_cmd=[], credentials={},
                          tools=[], token_cost=0)

    async def test_same_server_from_two_registries_deduplicated(self):
        from unittest.mock import AsyncMock
        from server import MultiRegistry

        official_srv = self._srv("filesystem", "filesystem", source="official")
        npm_srv = self._srv("mcp-server-filesystem", "mcp-server-filesystem", source="npm")

        reg = MultiRegistry()
        r1, r2 = AsyncMock(), AsyncMock()
        r1.search = AsyncMock(return_value=[official_srv])
        r2.search = AsyncMock(return_value=[npm_srv])
        reg._registries = [r1, r2]
        reg._search_cache.clear()

        results = await reg.search("filesystem", 10)

        # Both normalize to "filesystem" — only one should appear
        names = [s.name for s in results]
        assert len(names) == len(set(names))

    async def test_results_sorted_by_relevance(self):
        from unittest.mock import AsyncMock
        from server import MultiRegistry

        weak = self._srv("tools-pack", "tools-pack")
        strong = self._srv("filesystem", "filesystem", source="official")

        reg = MultiRegistry()
        r1 = AsyncMock()
        r1.search = AsyncMock(return_value=[weak, strong])
        reg._registries = [r1]
        reg._search_cache.clear()

        results = await reg.search("filesystem", 10)

        assert results[0].name == "filesystem"

    async def test_exception_from_one_registry_skipped(self):
        from unittest.mock import AsyncMock
        from server import MultiRegistry

        good = self._srv("brave-search", "brave-search", source="npm")

        reg = MultiRegistry()
        r1, r2 = AsyncMock(), AsyncMock()
        r1.search = AsyncMock(side_effect=Exception("network error"))
        r2.search = AsyncMock(return_value=[good])
        reg._registries = [r1, r2]
        reg._search_cache.clear()

        results = await reg.search("brave", 10)
        assert len(results) == 1
        assert results[0].name == "brave-search"


# ---------------------------------------------------------------------------
# McpRegistryIO tests
# ---------------------------------------------------------------------------

class TestMcpRegistryIO:
    """McpRegistryIO wraps registry.modelcontextprotocol.io — no auth."""

    _RESPONSE = {
        "servers": [
            {
                "server": {
                    "name": "owner/my-mcp-server",
                    "description": "A great MCP server for testing",
                    "packages": [
                        {
                            "registry_name": "npm",
                            "name": "@owner/my-mcp-server",
                            "environment_variables": [
                                {"name": "MY_API_KEY", "description": "Your API key"}
                            ],
                        }
                    ],
                    "remotes": [],
                }
            },
            {
                "server": {
                    "name": "other/pip-server",
                    "description": "A pip-based MCP server",
                    "packages": [
                        {
                            "registry_name": "pypi",
                            "name": "pip-mcp-server",
                            "environment_variables": [],
                        }
                    ],
                    "remotes": [],
                }
            },
        ],
        "metadata": {"nextCursor": None, "count": 2},
    }

    async def test_search_returns_servers(self):
        import chameleon_mcp.registry as reg_mod
        from server import McpRegistryIO
        reg_mod.McpRegistryIO._cache = None
        reg_mod.McpRegistryIO._cache_expires = 0.0
        with respx.mock:
            respx.get("https://registry.modelcontextprotocol.io/v0/servers").mock(
                return_value=httpx.Response(200, json=self._RESPONSE)
            )
            reg = McpRegistryIO()
            results = await reg.search("mcp server", 10)
        assert len(results) == 2
        assert results[0].source == "mcpregistry"

    async def test_npm_package_gets_npx_install_cmd(self):
        import chameleon_mcp.registry as reg_mod
        from server import McpRegistryIO
        reg_mod.McpRegistryIO._cache = None
        reg_mod.McpRegistryIO._cache_expires = 0.0
        with respx.mock:
            respx.get("https://registry.modelcontextprotocol.io/v0/servers").mock(
                return_value=httpx.Response(200, json=self._RESPONSE)
            )
            reg = McpRegistryIO()
            results = await reg.search("my-mcp", 10)
        npm_srv = next(s for s in results if "owner/my-mcp" in s.id)
        assert npm_srv.install_cmd == ["npx", "-y", "@owner/my-mcp-server"]

    async def test_pypi_package_gets_uvx_install_cmd(self):
        import chameleon_mcp.registry as reg_mod
        from server import McpRegistryIO
        reg_mod.McpRegistryIO._cache = None
        reg_mod.McpRegistryIO._cache_expires = 0.0
        with respx.mock:
            respx.get("https://registry.modelcontextprotocol.io/v0/servers").mock(
                return_value=httpx.Response(200, json=self._RESPONSE)
            )
            reg = McpRegistryIO()
            results = await reg.search("pip", 10)
        pip_srv = next(s for s in results if "pip-server" in s.id)
        assert pip_srv.install_cmd == ["uvx", "pip-mcp-server"]

    async def test_credentials_extracted_from_env_vars(self):
        import chameleon_mcp.registry as reg_mod
        from server import McpRegistryIO
        reg_mod.McpRegistryIO._cache = None
        reg_mod.McpRegistryIO._cache_expires = 0.0
        with respx.mock:
            respx.get("https://registry.modelcontextprotocol.io/v0/servers").mock(
                return_value=httpx.Response(200, json=self._RESPONSE)
            )
            reg = McpRegistryIO()
            result = await reg.get_server("owner/my-mcp-server")
        assert result is not None
        assert "MY_API_KEY" in result.credentials

    async def test_http_error_returns_empty(self):
        import chameleon_mcp.registry as reg_mod
        from server import McpRegistryIO
        reg_mod.McpRegistryIO._cache = None
        reg_mod.McpRegistryIO._cache_expires = 0.0
        with respx.mock:
            respx.get("https://registry.modelcontextprotocol.io/v0/servers").mock(
                return_value=httpx.Response(503, text="Unavailable")
            )
            reg = McpRegistryIO()
            results = await reg.search("anything", 5)
        assert results == []


# ---------------------------------------------------------------------------
# GlamaRegistry tests
# ---------------------------------------------------------------------------

class TestGlamaRegistry:
    """GlamaRegistry wraps glama.ai/api/mcp/v1/servers — no auth."""

    _SEARCH_RESPONSE = {
        "pageInfo": {"hasNextPage": False, "endCursor": None},
        "servers": [
            {
                "name": "brave-search",
                "namespace": "example",
                "slug": "brave-search",
                "description": "Web search via Brave",
                "attributes": ["hosting:local-only"],
                "repository": {"url": "https://github.com/example/brave-search"},
                "url": "https://glama.ai/mcp/servers/abc123",
                "environmentVariablesJsonSchema": {
                    "properties": {"BRAVE_API_KEY": {"description": "Brave API key"}},
                    "required": ["BRAVE_API_KEY"],
                },
            },
            {
                "name": "time-server",
                "namespace": "example",
                "slug": "time-server",
                "description": "Get current time",
                "attributes": ["hosting:local-only"],
                "repository": {"url": "https://github.com/example/time-server"},
                "url": "https://glama.ai/mcp/servers/def456",
                "environmentVariablesJsonSchema": {
                    "properties": {},
                    "required": [],
                },
            },
        ],
    }

    async def test_search_returns_glama_servers(self):
        from server import GlamaRegistry
        with respx.mock:
            respx.get("https://glama.ai/api/mcp/v1/servers").mock(
                return_value=httpx.Response(200, json=self._SEARCH_RESPONSE)
            )
            reg = GlamaRegistry()
            results = await reg.search("brave", 5)
        assert len(results) >= 1
        assert results[0].source == "glama"

    async def test_required_env_vars_become_credentials(self):
        from server import GlamaRegistry
        with respx.mock:
            respx.get("https://glama.ai/api/mcp/v1/servers").mock(
                return_value=httpx.Response(200, json=self._SEARCH_RESPONSE)
            )
            reg = GlamaRegistry()
            results = await reg.search("brave", 5)
        brave = next(s for s in results if "brave" in s.name)
        assert "BRAVE_API_KEY" in brave.credentials

    async def test_optional_env_vars_not_in_credentials(self):
        from server import GlamaRegistry
        with respx.mock:
            respx.get("https://glama.ai/api/mcp/v1/servers").mock(
                return_value=httpx.Response(200, json=self._SEARCH_RESPONSE)
            )
            reg = GlamaRegistry()
            results = await reg.search("time", 5)
        time_srv = next(s for s in results if "time" in s.name)
        assert time_srv.credentials == {}

    async def test_github_url_becomes_install_cmd(self):
        from server import GlamaRegistry
        with respx.mock:
            respx.get("https://glama.ai/api/mcp/v1/servers").mock(
                return_value=httpx.Response(200, json=self._SEARCH_RESPONSE)
            )
            reg = GlamaRegistry()
            results = await reg.search("brave", 5)
        brave = next(s for s in results if "brave" in s.name)
        assert brave.install_cmd == ["npx", "github:example/brave-search"]

    async def test_http_error_returns_empty(self):
        from server import GlamaRegistry
        with respx.mock:
            respx.get("https://glama.ai/api/mcp/v1/servers").mock(
                return_value=httpx.Response(503, text="Unavailable")
            )
            reg = GlamaRegistry()
            results = await reg.search("anything", 5)
        assert results == []


# ---------------------------------------------------------------------------
# Relevance score: credential preference
# ---------------------------------------------------------------------------

class TestRelevanceScoreCredentialBonus:
    def _srv(self, id, name, credentials=None, source="npm"):
        from server import ServerInfo
        return ServerInfo(id=id, name=name, description="web search tool", source=source,
                          transport="stdio", url="", install_cmd=[],
                          credentials=credentials or {}, tools=[], token_cost=0)

    def test_no_cred_server_ranks_above_cred_server(self):
        from server import _relevance_score
        free = self._srv("brave-search-free", "brave search", credentials={})
        paid = self._srv("brave-search-paid", "brave search", credentials={"BRAVE_API_KEY": "key"})
        assert _relevance_score(free, "brave search") > _relevance_score(paid, "brave search")

    def test_cred_bonus_does_not_override_strong_name_match(self):
        from server import _relevance_score
        # A server with creds but exact name match should still beat a no-cred server with weak match
        exact_cred = self._srv("filesystem", "filesystem", credentials={"FS_KEY": "key"})
        weak_free = self._srv("tools-pack", "tools pack", credentials={})
        assert _relevance_score(exact_cred, "filesystem") > _relevance_score(weak_free, "filesystem")
