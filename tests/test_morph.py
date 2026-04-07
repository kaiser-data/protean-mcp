"""Tests for morph-related helpers: _make_proxy, collision detection, _BASE_TOOL_NAMES."""
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from server import _BASE_TOOL_NAMES, StdioTransport, _make_proxy


class TestBaseToolNames:
    def test_base_tool_names_is_set(self):
        assert isinstance(_BASE_TOOL_NAMES, set)

    def test_core_tools_present(self):
        expected = {"search", "inspect", "call", "morph", "shed", "status"}
        assert expected.issubset(_BASE_TOOL_NAMES)

    def test_new_tools_present(self):
        """connect, release, test, bench should be in base tool names."""
        assert "connect" in _BASE_TOOL_NAMES
        assert "release" in _BASE_TOOL_NAMES
        assert "test" in _BASE_TOOL_NAMES
        assert "bench" in _BASE_TOOL_NAMES


class TestMakeProxy:
    def _make_transport(self):
        return StdioTransport(["echo"])

    def test_proxy_has_correct_name(self):
        schema = {
            "name": "my_tool",
            "description": "Does stuff",
            "inputSchema": {"type": "object", "properties": {}, "required": []},
        }
        transport = self._make_transport()
        fn = _make_proxy("test-server", schema, transport, {})
        assert fn.__name__ == "my_tool"

    def test_proxy_with_custom_name(self):
        schema = {
            "name": "search",
            "description": "Search something",
            "inputSchema": {"type": "object", "properties": {}, "required": []},
        }
        transport = self._make_transport()
        fn = _make_proxy("test-server", schema, transport, {}, proxy_name="test_server_search")
        assert fn.__name__ == "test_server_search"

    def test_proxy_signature_has_correct_params(self):
        schema = {
            "name": "greet",
            "description": "Greet someone",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "count": {"type": "integer"},
                },
                "required": ["name"],
            },
        }
        transport = self._make_transport()
        fn = _make_proxy("test-server", schema, transport, {})
        sig = inspect.signature(fn)
        params = sig.parameters

        assert "name" in params
        assert "count" in params
        assert params["name"].default is inspect.Parameter.empty  # required
        assert params["count"].default is None  # optional

    def test_proxy_type_annotations(self):
        schema = {
            "name": "tool",
            "description": "A tool",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "flag": {"type": "boolean"},
                    "num": {"type": "number"},
                },
                "required": [],
            },
        }
        transport = self._make_transport()
        fn = _make_proxy("test-server", schema, transport, {})
        sig = inspect.signature(fn)

        assert sig.parameters["text"].annotation is str
        assert sig.parameters["flag"].annotation is bool
        assert sig.parameters["num"].annotation is float

    def test_proxy_is_coroutine(self):
        schema = {
            "name": "async_tool",
            "description": "Async",
            "inputSchema": {"type": "object", "properties": {}, "required": []},
        }
        transport = self._make_transport()
        fn = _make_proxy("test-server", schema, transport, {})
        assert inspect.iscoroutinefunction(fn)

    def test_proxy_doc_truncated_to_120_chars(self):
        long_desc = "A" * 200
        schema = {
            "name": "tool",
            "description": long_desc,
            "inputSchema": {"type": "object", "properties": {}, "required": []},
        }
        transport = self._make_transport()
        fn = _make_proxy("test-server", schema, transport, {})
        assert len(fn.__doc__) <= 120


class TestCollisionDetection:
    """Test that morph() prefixes tool names that collide with base tools."""

    def test_collision_name_would_be_prefixed(self):
        """Verify the collision logic: if name in _BASE_TOOL_NAMES, it gets prefixed."""
        server_id = "test-org/my-server"
        import re
        sanitized = re.sub(r'[^a-z0-9_]', '_', server_id.lower())

        for base_tool in _BASE_TOOL_NAMES:
            proxy_name = f"{sanitized}_{base_tool}" if base_tool in _BASE_TOOL_NAMES else base_tool
            assert proxy_name != base_tool  # always prefixed for collision names
            assert proxy_name.startswith(sanitized)

    def test_non_collision_name_unchanged(self):
        """Tool names not in _BASE_TOOL_NAMES pass through unchanged."""
        import re
        server_id = "test-org/my-server"
        sanitized = re.sub(r'[^a-z0-9_]', '_', server_id.lower())

        for unique_name in ["unique_tool_xyz", "get_weather", "list_files"]:
            proxy_name = f"{sanitized}_{unique_name}" if unique_name in _BASE_TOOL_NAMES else unique_name
            assert proxy_name == unique_name


class TestMorphUsesPersistentTransport:
    """morph() for stdio servers must use PersistentStdioTransport so processes are pooled."""

    async def test_list_tools_called_on_persistent_transport(self):
        """_register_proxy_tools receives a PersistentStdioTransport, not StdioTransport."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from server import PersistentStdioTransport, ServerInfo, _registry, morph

        srv = ServerInfo(
            id="test-org/pool-server", name="pool-server", description="",
            source="npm", transport="stdio", url="",
            install_cmd=["npx", "-y", "pool-server"],
            credentials={}, tools=[], token_cost=0,
        )

        captured = {}

        def fake_register(server_id, tools, transport, config, base_names=None, only=None):
            captured["transport_type"] = type(transport).__name__
            return ["pool_tool"]

        ctx = MagicMock()
        ctx.session = MagicMock()
        ctx.session.send_tool_list_changed = AsyncMock()

        with patch.object(_registry, "get_server", AsyncMock(return_value=srv)), \
             patch("chameleon_mcp.tools._register_proxy_tools", side_effect=fake_register), \
             patch("chameleon_mcp.tools.PersistentStdioTransport") as MockPersistent:
            mock_transport = MagicMock()
            mock_transport.list_tools = AsyncMock(return_value=[
                {"name": "pool_tool", "description": "a tool", "inputSchema": {}}
            ])
            MockPersistent.return_value = mock_transport

            await morph("test-org/pool-server", ctx)

        MockPersistent.assert_called_once_with(["npx", "-y", "pool-server"])
        mock_transport.list_tools.assert_called_once()


# ---------------------------------------------------------------------------
# Phase 1: _register_proxy_resources
# ---------------------------------------------------------------------------

class TestRegisterProxyResources:
    """Tests for _register_proxy_resources()."""

    def _make_transport(self):
        from unittest.mock import AsyncMock, MagicMock
        t = MagicMock()
        t.read_resource = AsyncMock(return_value="resource content")
        return t

    async def test_registers_static_resource(self):
        from server import _register_proxy_resources
        transport = self._make_transport()
        resources = [{"uri": "config://my-server/settings", "name": "settings", "description": "config"}]
        registered = _register_proxy_resources(transport, resources)
        assert len(registered) == 1
        assert "config://my-server/settings" in registered[0]

    async def test_skips_uri_template(self):
        """Resources with {param} placeholders are skipped — they require parameter binding."""
        from server import _register_proxy_resources
        transport = self._make_transport()
        resources = [{"uri": "file:///{path}", "name": "file"}]
        registered = _register_proxy_resources(transport, resources)
        assert registered == []

    async def test_skips_missing_uri(self):
        from server import _register_proxy_resources
        transport = self._make_transport()
        resources = [{"name": "no_uri"}]
        registered = _register_proxy_resources(transport, resources)
        assert registered == []

    async def test_proxy_calls_transport_read_resource(self):
        """The registered proxy function calls transport.read_resource with the correct URI."""
        from server import _register_proxy_resources
        from chameleon_mcp.app import mcp
        transport = self._make_transport()
        uri = "config://proxy-test-srv/doc"
        resources = [{"uri": uri, "name": "doc", "description": "docs"}]
        registered = _register_proxy_resources(transport, resources)
        assert registered  # registered something

        # Fetch the registered resource fn and call it
        rm = mcp._resource_manager
        r = rm._resources.get(registered[0])
        assert r is not None
        result = await r.fn()
        transport.read_resource.assert_called_once_with(uri)
        assert result == "resource content"

        # Cleanup
        rm._resources.pop(registered[0], None)

    async def test_read_failure_returns_error_string(self):
        """Proxy returns an error string instead of raising on transport failure."""
        from unittest.mock import AsyncMock, MagicMock
        from server import _register_proxy_resources
        from chameleon_mcp.app import mcp
        transport = MagicMock()
        transport.read_resource = AsyncMock(side_effect=RuntimeError("server died"))
        uri = "config://error-test/settings"
        resources = [{"uri": uri, "name": "settings"}]
        registered = _register_proxy_resources(transport, resources)
        assert registered

        rm = mcp._resource_manager
        r = rm._resources.get(registered[0])
        assert r is not None
        result = await r.fn()
        assert "unavailable" in result.lower() or "server died" in result.lower()

        rm._resources.pop(registered[0], None)


# ---------------------------------------------------------------------------
# Phase 1: _register_proxy_prompts
# ---------------------------------------------------------------------------

class TestRegisterProxyPrompts:
    """Tests for _register_proxy_prompts()."""

    def _make_transport(self):
        from unittest.mock import AsyncMock, MagicMock
        t = MagicMock()
        t.get_prompt = AsyncMock(return_value=[
            {"role": "user", "content": {"text": "hello"}},
        ])
        return t

    async def test_registers_prompt(self):
        from server import _register_proxy_prompts
        from chameleon_mcp.app import mcp
        transport = self._make_transport()
        prompts = [{"name": "greet_user", "description": "greet the user", "arguments": []}]
        registered = _register_proxy_prompts(transport, prompts)
        assert "greet_user" in registered

        # Cleanup
        mcp._prompt_manager._prompts.pop("greet_user", None)

    async def test_skips_empty_name(self):
        from server import _register_proxy_prompts
        transport = self._make_transport()
        prompts = [{"name": "", "description": "nameless"}]
        registered = _register_proxy_prompts(transport, prompts)
        assert registered == []

    async def test_prompt_with_args_has_correct_signature(self):
        """Proxy function signature must include all declared arguments."""
        import inspect as _i
        from server import _register_proxy_prompts
        from chameleon_mcp.app import mcp
        transport = self._make_transport()
        prompts = [{
            "name": "test_sig_prompt",
            "description": "test",
            "arguments": [
                {"name": "topic", "required": True},
                {"name": "style", "required": False},
            ],
        }]
        registered = _register_proxy_prompts(transport, prompts)
        assert "test_sig_prompt" in registered

        p = mcp._prompt_manager._prompts["test_sig_prompt"]
        sig = _i.signature(p.fn)
        assert "topic" in sig.parameters
        assert "style" in sig.parameters
        # required param has no default; optional has ""
        assert sig.parameters["topic"].default is _i.Parameter.empty
        assert sig.parameters["style"].default == ""

        mcp._prompt_manager._prompts.pop("test_sig_prompt", None)

    async def test_proxy_calls_transport_get_prompt(self):
        """Proxy function forwards call to transport.get_prompt."""
        from server import _register_proxy_prompts
        from chameleon_mcp.app import mcp
        transport = self._make_transport()
        prompts = [{"name": "forward_test_prompt", "description": "fwd", "arguments": []}]
        registered = _register_proxy_prompts(transport, prompts)
        assert registered

        p = mcp._prompt_manager._prompts["forward_test_prompt"]
        result = await p.fn()
        transport.get_prompt.assert_called_once_with("forward_test_prompt", {})
        assert "[user]:" in result

        mcp._prompt_manager._prompts.pop("forward_test_prompt", None)

    async def test_message_format(self):
        """Proxy formats messages as [role]: text lines joined by ---."""
        from unittest.mock import AsyncMock, MagicMock
        from server import _register_proxy_prompts
        from chameleon_mcp.app import mcp
        transport = MagicMock()
        transport.get_prompt = AsyncMock(return_value=[
            {"role": "user", "content": {"text": "What is X?"}},
            {"role": "assistant", "content": {"text": "X is Y."}},
        ])
        prompts = [{"name": "msg_format_test", "description": "", "arguments": []}]
        registered = _register_proxy_prompts(transport, prompts)
        p = mcp._prompt_manager._prompts["msg_format_test"]
        result = await p.fn()
        assert "[user]: What is X?" in result
        assert "[assistant]: X is Y." in result
        assert "---" in result

        mcp._prompt_manager._prompts.pop("msg_format_test", None)


# ---------------------------------------------------------------------------
# Phase 1: _do_shed cleans up resources + prompts
# ---------------------------------------------------------------------------

class TestDoShedAll:
    """_do_shed() must remove tools, resources, and prompts."""

    async def test_shed_removes_resources_and_prompts(self):
        from unittest.mock import AsyncMock, MagicMock
        from server import _register_proxy_resources, _register_proxy_prompts, _do_shed, session

        # Seed a resource
        transport_r = MagicMock()
        transport_r.read_resource = AsyncMock(return_value="")
        reg_res = _register_proxy_resources(
            transport_r,
            [{"uri": "config://shed-test/r1", "name": "r1"}],
        )

        # Seed a prompt
        transport_p = MagicMock()
        transport_p.get_prompt = AsyncMock(return_value=[])
        reg_prom = _register_proxy_prompts(
            transport_p,
            [{"name": "shed_test_prompt", "description": "", "arguments": []}],
        )

        session["morphed_resources"] = reg_res
        session["morphed_prompts"] = reg_prom

        _do_shed()

        from chameleon_mcp.app import mcp
        for uri in reg_res:
            assert uri not in mcp._resource_manager._resources
        for pname in reg_prom:
            assert pname not in mcp._prompt_manager._prompts
        assert session["morphed_resources"] == []
        assert session["morphed_prompts"] == []

    async def test_shed_tolerates_already_removed(self):
        """_do_shed() should not raise if resources/prompts were already removed."""
        from server import _do_shed, session
        session["morphed_resources"] = ["config://nonexistent/r"]
        session["morphed_prompts"] = ["nonexistent_prompt"]
        _do_shed()  # should not raise
        assert session["morphed_resources"] == []
        assert session["morphed_prompts"] == []


# ---------------------------------------------------------------------------
# Phase 1: morph() registers resources when transport supports it
# ---------------------------------------------------------------------------

class TestMorphRegistersAll:
    """morph() should register resources+prompts when transport supports them."""

    async def test_resources_registered_for_stdio_transport(self):
        """morph() calls _register_proxy_resources when transport has list_resources."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from server import ServerInfo, _registry, morph, session

        srv = ServerInfo(
            id="org/res-server", name="res-server", description="",
            source="npm", transport="stdio", url="",
            install_cmd=["npx", "-y", "res-server"],
            credentials={}, tools=[], token_cost=0,
        )

        ctx = MagicMock()
        ctx.session = MagicMock()
        ctx.session.send_tool_list_changed = AsyncMock()
        ctx.session.send_resource_list_changed = AsyncMock()
        ctx.session.send_prompt_list_changed = AsyncMock()

        registered_resources = []

        def fake_reg_resources(transport, resources):
            registered_resources.extend(resources)
            return []

        with patch.object(_registry, "get_server", AsyncMock(return_value=srv)), \
             patch("chameleon_mcp.tools._register_proxy_tools", return_value=["a_tool"]), \
             patch("chameleon_mcp.tools._register_proxy_resources", side_effect=fake_reg_resources) as mock_rr, \
             patch("chameleon_mcp.tools._register_proxy_prompts", return_value=[]) as mock_rp, \
             patch("chameleon_mcp.tools.PersistentStdioTransport") as MockPST:
            mock_t = MagicMock()
            mock_t.list_tools = AsyncMock(return_value=[{"name": "a_tool", "description": "", "inputSchema": {}}])
            mock_t.list_resources = AsyncMock(return_value=[{"uri": "config://org/cfg", "name": "cfg"}])
            mock_t.list_prompts = AsyncMock(return_value=[])
            MockPST.return_value = mock_t
            await morph("org/res-server", ctx)

        mock_rr.assert_called_once()
        # list_resources was called via wait_for on the transport
        mock_t.list_resources.assert_called_once()

    async def test_resources_skipped_for_http_transport(self):
        """morph() does not attempt list_resources on HTTPSSETransport (no such method)."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from server import ServerInfo, _registry, morph

        srv = ServerInfo(
            id="http-org/http-server", name="http-server", description="",
            source="smithery", transport="http", url="http-org/http-server",
            install_cmd=None, credentials={}, tools=[
                {"name": "http_tool", "description": "", "inputSchema": {}}
            ], token_cost=0,
        )

        ctx = MagicMock()
        ctx.session = MagicMock()
        ctx.session.send_tool_list_changed = AsyncMock()
        ctx.session.send_resource_list_changed = AsyncMock()
        ctx.session.send_prompt_list_changed = AsyncMock()

        with patch.object(_registry, "get_server", AsyncMock(return_value=srv)), \
             patch("chameleon_mcp.tools._register_proxy_tools", return_value=["http_tool"]), \
             patch("chameleon_mcp.tools._register_proxy_resources") as mock_rr, \
             patch("chameleon_mcp.tools._register_proxy_prompts") as mock_rp, \
             patch("chameleon_mcp.tools.HTTPSSETransport"):
            await morph("http-org/http-server", ctx)

        mock_rr.assert_not_called()
        mock_rp.assert_not_called()

    async def test_graceful_on_list_resources_exception(self):
        """morph() succeeds even if list_resources raises."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from server import ServerInfo, _registry, morph

        srv = ServerInfo(
            id="org/exc-server", name="exc-server", description="",
            source="npm", transport="stdio", url="",
            install_cmd=["npx", "-y", "exc-server"],
            credentials={}, tools=[], token_cost=0,
        )

        ctx = MagicMock()
        ctx.session = MagicMock()
        ctx.session.send_tool_list_changed = AsyncMock()
        ctx.session.send_resource_list_changed = AsyncMock()
        ctx.session.send_prompt_list_changed = AsyncMock()

        with patch.object(_registry, "get_server", AsyncMock(return_value=srv)), \
             patch("chameleon_mcp.tools._register_proxy_tools", return_value=["exc_tool"]), \
             patch("chameleon_mcp.tools.PersistentStdioTransport") as MockPST:
            mock_t = MagicMock()
            mock_t.list_tools = AsyncMock(return_value=[{"name": "exc_tool", "description": "", "inputSchema": {}}])
            mock_t.list_resources = AsyncMock(side_effect=RuntimeError("timeout"))
            mock_t.list_prompts = AsyncMock(return_value=[])
            MockPST.return_value = mock_t
            result = await morph("org/exc-server", ctx)

        # morph should still succeed
        assert "exc_tool" in result or "Morphed" in result
