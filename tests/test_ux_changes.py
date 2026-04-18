"""Tests for UX friction-reduction changes (Changes 1–8 + uninstall).

Covers:
- _credentials_ready() helper
- _infer_install_cmd() helper
- _local_uninstall_cmd() helper
- status() first-run onboarding
- shapeshift() source='local' confirmation gate
- shapeshift() credential check before _do_shed (bug fix)
- shapeshift() lean hint when >4 tools loaded
- KITSUNE_TRUST env var bypasses community/local gate
- shiftback(uninstall=True) for uvx and npx packages
- shiftback() with local install but no uninstall → hint in output
- MultiRegistry last_registry_errors populated on failure
- search() reports registry failures via ⚠️ Skipped:
"""
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ---------------------------------------------------------------------------
# Helper: _credentials_ready
# ---------------------------------------------------------------------------

class TestCredentialsReady:
    def setup_method(self):
        # Make sure we're not leaking env vars between tests
        os.environ.pop("API_KEY", None)
        os.environ.pop("TEST_TOKEN", None)

    def test_no_credentials_returns_ready(self):
        from kitsune_mcp.credentials import _credentials_ready
        assert _credentials_ready({}) == "✅ ready"

    def test_credential_present_in_env_returns_ready(self):
        from kitsune_mcp.credentials import _credentials_ready
        os.environ["API_KEY"] = "sk-test"
        try:
            result = _credentials_ready({"apiKey": "Your API key"})
            assert "✅" in result
        finally:
            del os.environ["API_KEY"]

    def test_credential_missing_returns_needs(self):
        from kitsune_mcp.credentials import _credentials_ready
        os.environ.pop("API_KEY", None)
        result = _credentials_ready({"apiKey": "Your API key"})
        assert "✗" in result
        assert "API_KEY" in result

    def test_multiple_missing_shows_all(self):
        from kitsune_mcp.credentials import _credentials_ready
        os.environ.pop("API_KEY", None)
        os.environ.pop("AUTH_TOKEN", None)
        # Use creds that generate env vars matching CRED_SUFFIXES patterns
        result = _credentials_ready({"apiKey": "key", "authToken": "tok"})
        assert "✗" in result
        assert "API_KEY" in result
        assert "AUTH_TOKEN" in result


# ---------------------------------------------------------------------------
# Helper: _infer_install_cmd
# ---------------------------------------------------------------------------

class TestInferInstallCmd:
    def _fn(self):
        from kitsune_mcp.tools import _infer_install_cmd
        return _infer_install_cmd

    def test_at_scope_package_uses_npx(self):
        fn = self._fn()
        assert fn("@scope/pkg") == ["npx", "-y", "@scope/pkg"]

    def test_slash_in_id_uses_npx(self):
        fn = self._fn()
        assert fn("owner/repo") == ["npx", "-y", "owner/repo"]

    def test_simple_name_no_dots_uses_npx(self):
        fn = self._fn()
        assert fn("brave") == ["npx", "-y", "brave"]

    def test_dotted_name_uses_uvx(self):
        fn = self._fn()
        assert fn("my.python.tool") == ["uvx", "my.python.tool"]

    def test_long_npm_package_uses_npx(self):
        fn = self._fn()
        assert fn("@modelcontextprotocol/server-brave-search") == [
            "npx", "-y", "@modelcontextprotocol/server-brave-search"
        ]


# ---------------------------------------------------------------------------
# Helper: _local_uninstall_cmd
# ---------------------------------------------------------------------------

class TestLocalUninstallCmd:
    def _fn(self):
        from kitsune_mcp.tools import _local_uninstall_cmd
        return _local_uninstall_cmd

    def test_uvx_returns_uv_tool_uninstall(self):
        fn = self._fn()
        assert fn(["uvx", "mypkg"]) == ["uv", "tool", "uninstall", "mypkg"]

    def test_uvx_takes_last_element_as_package(self):
        fn = self._fn()
        result = fn(["uvx", "some-long-package-name"])
        assert result == ["uv", "tool", "uninstall", "some-long-package-name"]

    def test_npx_returns_none(self):
        fn = self._fn()
        assert fn(["npx", "-y", "brave"]) is None

    def test_empty_cmd_returns_none(self):
        fn = self._fn()
        assert fn([]) is None

    def test_unknown_cmd_returns_none(self):
        fn = self._fn()
        assert fn(["pip", "install", "something"]) is None


# ---------------------------------------------------------------------------
# status() — first-run onboarding
# ---------------------------------------------------------------------------

class TestStatusOnboarding:
    async def test_clean_session_shows_getting_started(self):
        from kitsune_mcp.session import session
        from kitsune_mcp.tools import status

        # Ensure clean session state
        original = {k: session[k] for k in ("explored", "grown", "stats", "current_form", "shapeshift_tools")}
        session["explored"] = {}
        session["grown"] = {}
        session["stats"] = {"total_calls": 0, "tokens_sent": 0, "tokens_received": 0, "tokens_saved_browse": 0}
        session["current_form"] = None
        session["shapeshift_tools"] = []
        try:
            result = await status()
            assert "Getting started:" in result
            assert "search(" in result
            assert "shapeshift(" in result
        finally:
            for k, v in original.items():
                session[k] = v

    async def test_explored_session_hides_onboarding(self):
        from kitsune_mcp.session import session
        from kitsune_mcp.tools import status

        original = {k: session[k] for k in ("explored", "grown", "stats", "current_form", "shapeshift_tools")}
        session["explored"] = {"brave": {"name": "Brave", "desc": "search", "status": "explored"}}
        session["grown"] = {}
        session["stats"] = {"total_calls": 0, "tokens_sent": 0, "tokens_received": 0, "tokens_saved_browse": 0}
        session["current_form"] = None
        session["shapeshift_tools"] = []
        try:
            result = await status()
            assert "Getting started:" not in result
        finally:
            for k, v in original.items():
                session[k] = v

    async def test_nonzero_calls_hides_onboarding(self):
        from kitsune_mcp.session import session
        from kitsune_mcp.tools import status

        original = {k: session[k] for k in ("explored", "grown", "stats", "current_form", "shapeshift_tools")}
        session["explored"] = {}
        session["grown"] = {}
        session["stats"] = {"total_calls": 5, "tokens_sent": 0, "tokens_received": 0, "tokens_saved_browse": 0}
        session["current_form"] = None
        session["shapeshift_tools"] = []
        try:
            result = await status()
            assert "Getting started:" not in result
        finally:
            for k, v in original.items():
                session[k] = v


# ---------------------------------------------------------------------------
# shapeshift() — source='local' confirmation gate
# ---------------------------------------------------------------------------

class TestShapeshiftLocalGate:
    def _make_ctx(self):
        ctx = MagicMock()
        ctx.session = MagicMock()
        ctx.session.send_tool_list_changed = AsyncMock()
        return ctx

    def _make_srv(self, source="npm", transport="stdio", install_cmd=None, credentials=None):
        from kitsune_mcp.registry import ServerInfo
        return ServerInfo(
            id="test-server",
            name="Test Server",
            description="A test server",
            source=source,
            transport=transport,
            url="",
            install_cmd=install_cmd or [],
            credentials=credentials or {},
            tools=[],
            token_cost=0,
        )

    async def test_local_without_confirm_shows_gate(self):
        from kitsune_mcp.tools import shapeshift

        ctx = self._make_ctx()
        srv = self._make_srv(source="official", transport="stdio")

        with patch("kitsune_mcp.tools._registry") as mock_reg, \
             patch.dict(os.environ, {}, clear=False):
            os.environ.pop("KITSUNE_TRUST", None)
            mock_reg.get_server = AsyncMock(return_value=srv)
            mock_reg._get = MagicMock(return_value=mock_reg)

            result = await shapeshift("test-server", ctx, source="local", confirm=False)

        assert "source='local' will run" in result
        assert "npx" in result or "uvx" in result
        assert "confirm=True" in result

    async def test_local_gate_shows_exact_command(self):
        from kitsune_mcp.tools import shapeshift

        ctx = self._make_ctx()
        srv = self._make_srv(source="official", transport="stdio", install_cmd=["npx", "-y", "@scope/test"])

        with patch("kitsune_mcp.tools._registry") as mock_reg, \
             patch.dict(os.environ, {}, clear=False):
            os.environ.pop("KITSUNE_TRUST", None)
            mock_reg.get_server = AsyncMock(return_value=srv)
            mock_reg._get = MagicMock(return_value=mock_reg)

            result = await shapeshift("test-server", ctx, source="local", confirm=False)

        assert "npx -y @scope/test" in result

    async def test_local_gate_bypassed_with_kitsune_trust(self):
        """KITSUNE_TRUST=community bypasses the local confirmation gate."""
        from kitsune_mcp.tools import shapeshift

        ctx = self._make_ctx()
        srv = self._make_srv(source="official", transport="stdio", install_cmd=["npx", "-y", "test"])

        with patch("kitsune_mcp.tools._registry") as mock_reg, \
             patch("kitsune_mcp.tools._do_shed"), \
             patch("kitsune_mcp.tools._resolve_config", return_value=({}, {})), \
             patch("kitsune_mcp.tools.PersistentStdioTransport") as mock_transport_cls, \
             patch.dict(os.environ, {"KITSUNE_TRUST": "community"}):
            mock_reg.get_server = AsyncMock(return_value=srv)
            mock_reg._get = MagicMock(return_value=mock_reg)
            mock_transport = AsyncMock()
            mock_transport.list_tools = AsyncMock(return_value=[
                {"name": "test_tool", "description": "A tool", "inputSchema": {"type": "object", "properties": {}, "required": []}}
            ])
            mock_transport.list_resources = AsyncMock(return_value=[])
            mock_transport.list_prompts = AsyncMock(return_value=[])
            mock_transport_cls.return_value = mock_transport

            result = await shapeshift("test-server", ctx, source="local", confirm=False)

        # Should NOT show the gate message (proceeds past it)
        assert "source='local' will run" not in result


# ---------------------------------------------------------------------------
# shapeshift() — credential check BEFORE _do_shed (bug fix)
# ---------------------------------------------------------------------------

class TestShapeshiftCredBugFix:
    def _make_ctx(self):
        ctx = MagicMock()
        ctx.session = MagicMock()
        ctx.session.send_tool_list_changed = AsyncMock()
        return ctx

    async def test_do_shed_not_called_when_creds_missing(self):
        """If credentials are missing, _do_shed should NOT be called — current form preserved."""
        from kitsune_mcp.registry import ServerInfo
        from kitsune_mcp.tools import shapeshift

        ctx = self._make_ctx()
        srv = ServerInfo(
            id="needs-key",
            name="Needs Key",
            description="Requires an API key",
            source="smithery",
            transport="http",
            url="https://example.com",
            install_cmd=[],
            credentials={"apiKey": "Your API key"},
            tools=[],
            token_cost=0,
        )

        with patch("kitsune_mcp.tools._registry") as mock_reg, \
             patch("kitsune_mcp.tools._do_shed") as mock_shed, \
             patch("kitsune_mcp.tools._resolve_config", return_value=({}, {"apiKey": "Your API key"})), \
             patch.dict(os.environ, {}, clear=False):
            os.environ.pop("KITSUNE_TRUST", None)
            mock_reg.get_server = AsyncMock(return_value=srv)
            mock_reg._get = MagicMock(return_value=mock_reg)

            result = await shapeshift("needs-key", ctx, confirm=True)

        mock_shed.assert_not_called()
        assert "missing credentials" in result.lower() or "Cannot shapeshift" in result

    async def test_do_shed_called_when_creds_ok(self):
        """When credentials pass, _do_shed should be called."""
        from kitsune_mcp.registry import ServerInfo
        from kitsune_mcp.tools import shapeshift

        ctx = self._make_ctx()
        srv = ServerInfo(
            id="free-server",
            name="Free Server",
            description="No credentials needed",
            source="smithery",
            transport="http",
            url="https://example.com",
            install_cmd=[],
            credentials={},
            tools=[{"name": "my_tool", "description": "A tool", "inputSchema": {"type": "object", "properties": {}, "required": []}}],
            token_cost=0,
        )

        with patch("kitsune_mcp.tools._registry") as mock_reg, \
             patch("kitsune_mcp.tools._do_shed", return_value=[]) as mock_shed, \
             patch("kitsune_mcp.tools._resolve_config", return_value=({}, {})), \
             patch("kitsune_mcp.tools._get_transport") as mock_transport_fn, \
             patch("kitsune_mcp.tools._register_proxy_tools", return_value=["my_tool"]), \
             patch("kitsune_mcp.tools._register_proxy_resources", return_value=[]), \
             patch("kitsune_mcp.tools._register_proxy_prompts", return_value=[]), \
             patch("kitsune_mcp.tools._probe_requirements", return_value={}):
            mock_reg.get_server = AsyncMock(return_value=srv)
            mock_reg._get = MagicMock(return_value=mock_reg)
            mock_transport = AsyncMock()
            mock_transport.list_tools = AsyncMock(return_value=srv.tools)
            mock_transport.list_resources = AsyncMock(return_value=[])
            mock_transport.list_prompts = AsyncMock(return_value=[])
            mock_transport_fn.return_value = mock_transport

            await shapeshift("free-server", ctx)

        mock_shed.assert_called_once()


# ---------------------------------------------------------------------------
# shapeshift() — lean hint
# ---------------------------------------------------------------------------

class TestShapeshiftLeanHint:
    def _make_ctx(self):
        ctx = MagicMock()
        ctx.session = MagicMock()
        ctx.session.send_tool_list_changed = AsyncMock()
        return ctx

    def _make_srv(self, n_tools=6):
        from kitsune_mcp.registry import ServerInfo
        tools = [
            {"name": f"tool_{i}", "description": f"Tool {i}", "inputSchema": {"type": "object", "properties": {}, "required": []}}
            for i in range(n_tools)
        ]
        return ServerInfo(
            id="heavy-server", name="Heavy Server", description="Has many tools",
            source="smithery", transport="http", url="https://example.com",
            install_cmd=[], credentials={}, tools=tools, token_cost=0,
        )

    async def _shapeshift_with_mock(self, n_tools=6, tools_filter=None):
        from kitsune_mcp.tools import shapeshift

        ctx = self._make_ctx()
        srv = self._make_srv(n_tools)
        registered = [f"tool_{i}" for i in range(n_tools)]

        with patch("kitsune_mcp.tools._registry") as mock_reg, \
             patch("kitsune_mcp.tools._do_shed", return_value=[]), \
             patch("kitsune_mcp.tools._resolve_config", return_value=({}, {})), \
             patch("kitsune_mcp.tools._get_transport") as mock_transport_fn, \
             patch("kitsune_mcp.tools._register_proxy_tools", return_value=registered[:len(tools_filter)] if tools_filter else registered), \
             patch("kitsune_mcp.tools._register_proxy_resources", return_value=[]), \
             patch("kitsune_mcp.tools._register_proxy_prompts", return_value=[]), \
             patch("kitsune_mcp.tools._probe_requirements", return_value={}):
            mock_reg.get_server = AsyncMock(return_value=srv)
            mock_reg._get = MagicMock(return_value=mock_reg)
            mock_transport = AsyncMock()
            mock_transport.list_tools = AsyncMock(return_value=srv.tools)
            mock_transport.list_resources = AsyncMock(return_value=[])
            mock_transport.list_prompts = AsyncMock(return_value=[])
            mock_transport_fn.return_value = mock_transport

            return await shapeshift("heavy-server", ctx, tools=tools_filter)

    async def test_many_tools_no_filter_shows_lean_hint(self):
        result = await self._shapeshift_with_mock(n_tools=6, tools_filter=None)
        assert "💡" in result
        assert "tokens" in result
        assert "shapeshift(" in result

    async def test_few_tools_no_hint(self):
        result = await self._shapeshift_with_mock(n_tools=3, tools_filter=None)
        assert "💡" not in result

    async def test_filter_applied_no_hint(self):
        result = await self._shapeshift_with_mock(n_tools=6, tools_filter=["tool_0", "tool_1"])
        assert "💡" not in result


# ---------------------------------------------------------------------------
# Trust gate — KITSUNE_TRUST env var
# ---------------------------------------------------------------------------

class TestKitsuneTrustGate:
    def _make_ctx(self):
        ctx = MagicMock()
        ctx.session = MagicMock()
        ctx.session.send_tool_list_changed = AsyncMock()
        return ctx

    def _make_community_srv(self):
        from kitsune_mcp.registry import ServerInfo
        return ServerInfo(
            id="community-server", name="Community", description="From npm",
            source="npm", transport="stdio", url="",
            install_cmd=["npx", "-y", "community-server"],
            credentials={}, tools=[], token_cost=0,
        )

    async def test_community_server_without_confirm_shows_gate(self):
        from kitsune_mcp.tools import shapeshift
        ctx = self._make_ctx()
        srv = self._make_community_srv()

        with patch("kitsune_mcp.tools._registry") as mock_reg, \
             patch.dict(os.environ, {}, clear=False):
            os.environ.pop("KITSUNE_TRUST", None)
            mock_reg.get_server = AsyncMock(return_value=srv)
            mock_reg._get = MagicMock(return_value=mock_reg)

            result = await shapeshift("community-server", ctx, confirm=False)

        assert "community" in result.lower()
        assert "confirm=True" in result
        assert "KITSUNE_TRUST" in result  # teaches the feature

    async def test_kitsune_trust_community_bypasses_gate(self):
        from kitsune_mcp.tools import shapeshift
        ctx = self._make_ctx()
        srv = self._make_community_srv()
        srv = srv.__class__(
            id=srv.id, name=srv.name, description=srv.description,
            source=srv.source, transport=srv.transport, url=srv.url,
            install_cmd=srv.install_cmd, credentials={},
            tools=[{"name": "t", "description": "d", "inputSchema": {"type": "object", "properties": {}, "required": []}}],
            token_cost=0,
        )

        with patch("kitsune_mcp.tools._registry") as mock_reg, \
             patch("kitsune_mcp.tools._do_shed", return_value=[]), \
             patch("kitsune_mcp.tools._resolve_config", return_value=({}, {})), \
             patch("kitsune_mcp.tools.PersistentStdioTransport") as mock_cls, \
             patch("kitsune_mcp.tools._register_proxy_tools", return_value=["t"]), \
             patch("kitsune_mcp.tools._register_proxy_resources", return_value=[]), \
             patch("kitsune_mcp.tools._register_proxy_prompts", return_value=[]), \
             patch("kitsune_mcp.tools._probe_requirements", return_value={}), \
             patch.dict(os.environ, {"KITSUNE_TRUST": "community"}):
            mock_reg.get_server = AsyncMock(return_value=srv)
            mock_reg._get = MagicMock(return_value=mock_reg)
            mock_transport = AsyncMock()
            mock_transport.list_tools = AsyncMock(return_value=srv.tools)
            mock_transport.list_resources = AsyncMock(return_value=[])
            mock_transport.list_prompts = AsyncMock(return_value=[])
            mock_cls.return_value = mock_transport

            result = await shapeshift("community-server", ctx, confirm=False)

        # The GATE message contains "Review before trusting" — should NOT appear when bypassed
        assert "Review before trusting" not in result


# ---------------------------------------------------------------------------
# shiftback() — uninstall behaviour
# ---------------------------------------------------------------------------

class TestShiftbackUninstall:
    def _make_ctx(self):
        ctx = MagicMock()
        ctx.session = MagicMock()
        ctx.session.send_tool_list_changed = AsyncMock()
        ctx.session.send_resource_list_changed = AsyncMock()
        ctx.session.send_prompt_list_changed = AsyncMock()
        return ctx

    def _prime_session(self, package="brave", cmd=None, manager="npx"):
        """Set up session as if a local shapeshift just happened."""
        from kitsune_mcp.session import session
        install_cmd = cmd or (["npx", "-y", package] if manager == "npx" else ["uvx", package])
        session["shapeshift_tools"] = ["test_tool"]
        session["shapeshift_resources"] = []
        session["shapeshift_prompts"] = []
        session["current_form"] = package
        session["current_form_pool_key"] = None
        session["current_form_local_install"] = {"cmd": install_cmd, "package": package}

    def _reset_session(self):
        from kitsune_mcp.session import session
        session["shapeshift_tools"] = []
        session["shapeshift_resources"] = []
        session["shapeshift_prompts"] = []
        session["current_form"] = None
        session["current_form_pool_key"] = None
        session["current_form_local_install"] = None

    async def test_shiftback_without_uninstall_shows_cached_hint(self):
        from kitsune_mcp.tools import shiftback
        ctx = self._make_ctx()
        self._prime_session("brave", manager="npx")
        try:
            with patch("kitsune_mcp.tools._do_shed", return_value=["test_tool"]):
                result = await shiftback(ctx, kill=False, uninstall=False)
            assert "still cached" in result or "cached" in result
            assert "shiftback(uninstall=True)" in result
        finally:
            self._reset_session()

    async def test_shiftback_uninstall_npx_notes_ephemeral(self):
        """npx packages have no targeted uninstall — output should say so."""
        from kitsune_mcp.tools import shiftback
        ctx = self._make_ctx()
        self._prime_session("brave", manager="npx")
        try:
            with patch("kitsune_mcp.tools._do_shed", return_value=["test_tool"]):
                result = await shiftback(ctx, kill=False, uninstall=True)
            assert "npx" in result.lower() or "cached" in result.lower() or "permanently" in result.lower()
        finally:
            self._reset_session()

    async def test_shiftback_uninstall_uvx_runs_uv_command(self):
        """uvx packages trigger `uv tool uninstall <pkg>`."""
        from kitsune_mcp.tools import shiftback
        ctx = self._make_ctx()
        self._prime_session("mypkg", manager="uvx")
        try:
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(b"", b""))

            with patch("kitsune_mcp.tools._do_shed", return_value=["test_tool"]), \
                 patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
                result = await shiftback(ctx, kill=False, uninstall=True)

            # Should have called uv tool uninstall mypkg
            mock_exec.assert_called_once()
            args = mock_exec.call_args[0]
            assert args == ("uv", "tool", "uninstall", "mypkg")
            assert "Uninstalled" in result
        finally:
            self._reset_session()

    async def test_shiftback_uninstall_uvx_failed(self):
        """If uv tool uninstall fails, report the error without crashing."""
        from kitsune_mcp.tools import shiftback
        ctx = self._make_ctx()
        self._prime_session("mypkg", manager="uvx")
        try:
            mock_proc = AsyncMock()
            mock_proc.returncode = 1
            mock_proc.communicate = AsyncMock(return_value=(b"", b"Package not found"))

            with patch("kitsune_mcp.tools._do_shed", return_value=["test_tool"]), \
                 patch("asyncio.create_subprocess_exec", return_value=mock_proc):
                result = await shiftback(ctx, kill=False, uninstall=True)

            assert "Uninstall failed" in result or "error" in result.lower()
        finally:
            self._reset_session()

    async def test_shiftback_uninstall_no_local_install_is_noop(self):
        """uninstall=True with no local install tracked — just normal shiftback."""
        from kitsune_mcp.session import session
        from kitsune_mcp.tools import shiftback
        ctx = self._make_ctx()
        session["shapeshift_tools"] = ["test_tool"]
        session["shapeshift_resources"] = []
        session["shapeshift_prompts"] = []
        session["current_form"] = "some-server"
        session["current_form_pool_key"] = None
        session["current_form_local_install"] = None
        try:
            with patch("kitsune_mcp.tools._do_shed", return_value=["test_tool"]):
                result = await shiftback(ctx, kill=False, uninstall=True)
            # Should not crash, should not show cached hint
            assert "still cached" not in result
            assert "Shifted back" in result
        finally:
            self._reset_session()


# ---------------------------------------------------------------------------
# MultiRegistry — last_registry_errors
# ---------------------------------------------------------------------------

class TestRegistryErrors:
    async def test_failing_registry_recorded_in_errors(self):
        """A registry that raises populates last_registry_errors."""
        from kitsune_mcp.registry import MultiRegistry, ServerInfo

        mr = MultiRegistry()
        # Replace all registries with one that succeeds and one that fails
        good_reg = AsyncMock()
        good_reg.search = AsyncMock(return_value=[
            ServerInfo("s1", "S1", "desc", "official", "stdio")
        ])
        bad_reg = AsyncMock()
        bad_reg.search = AsyncMock(side_effect=TimeoutError("timeout"))
        bad_reg.__class__.__name__ = "BadRegistry"

        mr._registries = [good_reg, bad_reg]
        mr._search_cache = {}

        results = await mr.search("test", 5)

        assert len(mr.last_registry_errors) == 1
        assert len(results) == 1  # only the good result

    async def test_no_failures_means_empty_errors(self):
        from kitsune_mcp.registry import MultiRegistry, ServerInfo

        mr = MultiRegistry()
        good1 = AsyncMock()
        good1.search = AsyncMock(return_value=[ServerInfo("s1", "S1", "d", "official", "stdio")])
        good2 = AsyncMock()
        good2.search = AsyncMock(return_value=[ServerInfo("s2", "S2", "d", "npm", "stdio")])
        mr._registries = [good1, good2]
        mr._search_cache = {}

        await mr.search("test", 5)

        assert mr.last_registry_errors == {}


# ---------------------------------------------------------------------------
# search() — registry failure warning in output
# ---------------------------------------------------------------------------

class TestSearchRegistryWarning:
    async def test_search_shows_warning_when_registry_fails(self):
        """When a registry fails during search('all'), ⚠️ Skipped: appears."""
        from kitsune_mcp.registry import ServerInfo
        from kitsune_mcp.tools import search

        mock_servers = [
            ServerInfo("brave", "Brave", "Web search", "smithery", "http"),
        ]

        mock_registry = MagicMock()
        mock_registry.search = AsyncMock(return_value=mock_servers)
        mock_registry.last_registry_errors = {"glama": "TimeoutError"}

        with patch("kitsune_mcp.tools._registry", mock_registry):
            result = await search("web search", registry="all", limit=5)

        assert "⚠️" in result
        assert "Skipped" in result
        assert "glama" in result

    async def test_search_no_warning_when_no_failures(self):
        from kitsune_mcp.registry import ServerInfo
        from kitsune_mcp.tools import search

        mock_servers = [
            ServerInfo("brave", "Brave", "Web search", "smithery", "http"),
        ]

        mock_registry = MagicMock()
        mock_registry.search = AsyncMock(return_value=mock_servers)
        mock_registry.last_registry_errors = {}

        with patch("kitsune_mcp.tools._registry", mock_registry):
            result = await search("web search", registry="all", limit=5)

        assert "Skipped" not in result
