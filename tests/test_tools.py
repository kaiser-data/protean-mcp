"""Tests for tool helper functions: _truncate, _clean_response, _estimate_tokens, _credentials_guide."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from server import (
    _clean_response,
    _credentials_guide,
    _estimate_tokens,
    _extract_content,
    _load_skills,
    _save_skills,
    _truncate,
    session,
)


class TestTruncate:
    def test_short_text_unchanged(self):
        text = "Hello, world!"
        result = _truncate(text, max_tokens=1500)
        assert result == text

    def test_long_text_truncated(self):
        # 1500 tokens * 4 chars/token = 6000 chars
        text = "X" * 10_000
        result = _truncate(text, max_tokens=1500)
        assert len(result) < len(text)
        assert "[...truncated" in result

    def test_truncation_note_includes_token_count(self):
        text = "A" * 10_000
        result = _truncate(text, max_tokens=100)
        assert "100" in result

    def test_exact_limit_not_truncated(self):
        # exactly 400 chars = 100 tokens
        text = "B" * 400
        result = _truncate(text, max_tokens=100)
        assert "[...truncated" not in result
        assert result == text


class TestCleanResponse:
    def test_strips_markdown_links(self):
        text = "See [this link](https://example.com) for details."
        result = _clean_response(text)
        assert "this link" in result
        assert "https://example.com" not in result
        assert "[" not in result

    def test_strips_images(self):
        text = "Here is ![an image](https://img.example.com/pic.jpg) shown."
        result = _clean_response(text)
        assert "![" not in result

    def test_collapses_blank_lines(self):
        text = "Line 1\n\n\n\nLine 2"
        result = _clean_response(text)
        assert "\n\n\n" not in result

    def test_collapses_spaces(self):
        text = "Word1   Word2    Word3"
        result = _clean_response(text)
        assert "   " not in result

    def test_strips_surrounding_whitespace(self):
        text = "  \n  content  \n  "
        result = _clean_response(text)
        assert result == "content"


class TestEstimateTokens:
    def test_string_estimate(self):
        text = "A" * 400  # 400 chars / 4 = 100 tokens
        assert _estimate_tokens(text) == 100

    def test_list_estimate(self):
        items = [{"name": "tool1"}, {"name": "tool2"}]
        result = _estimate_tokens(items)
        assert isinstance(result, int)
        assert result > 0

    def test_empty_string(self):
        assert _estimate_tokens("") == 0

    def test_non_string_coerced(self):
        result = _estimate_tokens(12345)
        assert isinstance(result, int)


class TestCredentialsGuide:
    def test_no_missing_returns_empty(self):
        credentials = {"apiKey": "Your API key"}
        resolved = {"apiKey": "sk-123"}
        result = _credentials_guide("test-server", credentials, resolved)
        assert result == ""

    def test_missing_cred_returns_guide(self):
        credentials = {"apiKey": "Your API key"}
        resolved = {}
        result = _credentials_guide("test-server", credentials, resolved)
        assert "test-server" in result
        assert "API_KEY" in result  # env var form shown
        assert "✗" in result        # shown as missing

    def test_shows_key_command(self):
        credentials = {"apiKey": "API key description"}
        resolved = {}
        result = _credentials_guide("my-server", credentials, resolved)
        assert "key(" in result

    def test_shows_dotenv_instructions(self):
        credentials = {"token": "Auth token", "secret": "Secret value"}
        resolved = {}
        result = _credentials_guide("my-server", credentials, resolved)
        assert "Add to .env:" in result
        assert "TOKEN=your-value" in result
        assert "SECRET=your-value" in result

    def test_multiple_missing_all_shown(self):
        credentials = {
            "apiKey": "Key A",
            "token": "Key B",
            "secret": "Key C",
        }
        resolved = {"apiKey": "already-set"}
        result = _credentials_guide("multi-server", credentials, resolved)
        assert "TOKEN" in result
        assert "SECRET" in result
        assert "✓" in result   # apiKey is resolved — should show as found


class TestExtractContent:
    def test_single_text_part_extracted(self):
        result = {"content": [{"type": "text", "text": "Hello world"}]}
        assert _extract_content(result) == "Hello world"

    def test_multiple_text_parts_joined(self):
        result = {"content": [
            {"type": "text", "text": "Part 1"},
            {"type": "text", "text": "Part 2"},
        ]}
        assert _extract_content(result) == "Part 1\nPart 2"

    def test_non_text_content_falls_back_to_json(self):
        result = {"content": [{"type": "image", "data": "abc123"}]}
        out = _extract_content(result)
        assert "image" in out  # JSON dump includes the type field

    def test_empty_content_falls_back_to_json_result(self):
        result = {"someKey": "someValue"}
        out = _extract_content(result)
        assert "someKey" in out


class TestSkillPersistence:
    """_load_skills / _save_skills round-trip tests."""

    def _make_skill(self, name="test-skill", content="do the thing"):
        return {
            "name": name,
            "content": content,
            "tokens": len(content) // 4,
            "installed_at": "2026-01-01T00:00:00",
        }

    def test_save_and_load_round_trip(self, tmp_path, monkeypatch):
        import chameleon_mcp.session as sess_mod

        skills_file = tmp_path / "skills.json"
        monkeypatch.setattr(sess_mod, "SKILLS_PATH", skills_file)

        session["skills"]["org/my-skill"] = self._make_skill()
        _save_skills()

        assert skills_file.exists()
        data = json.loads(skills_file.read_text())
        assert "org/my-skill" in data
        assert data["org/my-skill"]["content"] == "do the thing"

    def test_load_populates_session(self, tmp_path, monkeypatch):
        import chameleon_mcp.session as sess_mod

        skills_file = tmp_path / "skills.json"
        skills_file.write_text(json.dumps({"org/loaded-skill": self._make_skill("loaded")}))
        monkeypatch.setattr(sess_mod, "SKILLS_PATH", skills_file)

        # Clear session and reload
        session["skills"].clear()
        _load_skills()

        assert "org/loaded-skill" in session["skills"]
        assert session["skills"]["org/loaded-skill"]["name"] == "loaded"

    def test_load_missing_file_is_silent(self, tmp_path, monkeypatch):
        import chameleon_mcp.session as sess_mod

        monkeypatch.setattr(sess_mod, "SKILLS_PATH", tmp_path / "nonexistent.json")
        session["skills"].clear()
        _load_skills()  # should not raise
        assert session["skills"] == {}

    def test_load_corrupt_file_is_silent(self, tmp_path, monkeypatch):
        import chameleon_mcp.session as sess_mod

        skills_file = tmp_path / "skills.json"
        skills_file.write_text("not valid json{{{")
        monkeypatch.setattr(sess_mod, "SKILLS_PATH", skills_file)

        session["skills"].clear()
        _load_skills()  # should not raise
        assert session["skills"] == {}


class TestConnectServerIdResolution:
    """connect() resolves server_id via registry when no spaces/executor prefix."""

    async def test_server_id_resolves_install_cmd(self):
        from unittest.mock import AsyncMock, MagicMock, patch
        import json as _json
        from server import ServerInfo, _registry, connect, _process_pool

        srv = ServerInfo(
            id="filesystem", name="filesystem", description="",
            source="official", transport="stdio", url="",
            install_cmd=["npx", "-y", "@modelcontextprotocol/server-filesystem"],
            credentials={}, tools=[], token_cost=0,
        )

        init_msg = _json.dumps({"jsonrpc": "2.0", "id": 1, "result": {
            "protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "fs", "version": "1"}
        }}).encode() + b"\n"

        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stdin.write = MagicMock()
        mock_proc.stdin.drain = AsyncMock()
        mock_proc.stdin.close = MagicMock()
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.readline = AsyncMock(side_effect=[
            init_msg,
            _json.dumps({"jsonrpc": "2.0", "id": 3, "result": {"tools": []}}).encode() + b"\n",
            _json.dumps({"jsonrpc": "2.0", "id": 4, "result": {"resources": []}}).encode() + b"\n",
            b"",
        ])
        mock_proc.returncode = None
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock(return_value=0)

        with patch.object(_registry, "get_server", AsyncMock(return_value=srv)), \
             patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
            result = await connect("filesystem", name="fs")

        assert "Connected" in result or "Already" in result
        # The resolved install_cmd must have been used — pool key reflects it
        import json
        expected_key = json.dumps(["npx", "-y", "@modelcontextprotocol/server-filesystem"], sort_keys=True)
        assert expected_key in _process_pool

    async def test_shell_command_bypasses_registry(self):
        """'npx -y something' should NOT hit the registry."""
        from unittest.mock import AsyncMock, patch
        from server import _registry, connect

        with patch.object(_registry, "get_server", AsyncMock()) as mock_get, \
             patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
            await connect("npx -y some-package")

        mock_get.assert_not_called()


class TestCraftTool:
    """Tests for the craft() endpoint-backed custom tool."""

    def setup_method(self):
        from server import mcp, session
        # Clean up any crafted tools from previous tests
        for name in list(session.get("crafted_tools", {}).keys()):
            try:
                mcp.remove_tool(name)
            except Exception:
                pass
        session["crafted_tools"] = {}
        session["morphed_tools"] = [t for t in session.get("morphed_tools", [])
                                     if t not in session.get("crafted_tools", {})]

    async def test_craft_registers_tool_post(self):
        """craft() with POST registers the tool and records it in session."""
        import respx
        import httpx
        from unittest.mock import MagicMock, AsyncMock
        from server import craft, session

        ctx = MagicMock()
        ctx.session = MagicMock()
        ctx.session.send_tool_list_changed = AsyncMock()

        with respx.mock:
            respx.post("http://localhost:9999/rank").mock(
                return_value=httpx.Response(200, text="ranked!")
            )
            result = await craft(
                ctx=ctx,
                name="my_ranker",
                description="rank results",
                params={"query": {"type": "string", "description": "search query"}},
                url="http://localhost:9999/rank",
            )

        assert "my_ranker" in result
        assert "my_ranker" in session["crafted_tools"]
        assert "my_ranker" in session["morphed_tools"]

    async def test_craft_tool_calls_endpoint(self):
        """Registered proxy actually POSTs to the endpoint."""
        import respx
        import httpx
        from unittest.mock import MagicMock, AsyncMock
        from server import craft, mcp, session

        ctx = MagicMock()
        ctx.session = MagicMock()
        ctx.session.send_tool_list_changed = AsyncMock()

        with respx.mock:
            route = respx.post("http://localhost:9999/echo").mock(
                return_value=httpx.Response(200, text="pong")
            )
            await craft(
                ctx=ctx,
                name="echo_tool",
                description="echo",
                params={"msg": {"type": "string", "description": "message"}},
                url="http://localhost:9999/echo",
            )

            # Call the registered tool directly
            tool_fn = next(t.fn for t in mcp._tool_manager._tools.values() if t.fn.__name__ == "echo_tool")
            response = await tool_fn(msg="hello")

        assert response == "pong"
        assert route.called
        import json as _json2
        body = _json2.loads(route.calls[0].request.content)
        assert body == {"msg": "hello"}

    async def test_craft_get_uses_query_params(self):
        """craft() with GET sends args as query string, not body."""
        import respx
        import httpx
        from unittest.mock import MagicMock, AsyncMock
        from server import craft, mcp

        ctx = MagicMock()
        ctx.session = MagicMock()
        ctx.session.send_tool_list_changed = AsyncMock()

        with respx.mock:
            route = respx.get("http://localhost:9999/search").mock(
                return_value=httpx.Response(200, text="results")
            )
            await craft(
                ctx=ctx,
                name="get_searcher",
                description="search via GET",
                params={"q": {"type": "string", "description": "query"}},
                url="http://localhost:9999/search",
                method="GET",
            )

            tool_fn = next(t.fn for t in mcp._tool_manager._tools.values() if t.fn.__name__ == "get_searcher")
            await tool_fn(q="mcp")

        assert route.called
        assert "q=mcp" in str(route.calls[0].request.url)

    async def test_craft_endpoint_error_returns_message(self):
        """HTTP errors from the endpoint are returned as strings, not raised."""
        import respx
        import httpx
        from unittest.mock import MagicMock, AsyncMock
        from server import craft, mcp

        ctx = MagicMock()
        ctx.session = MagicMock()
        ctx.session.send_tool_list_changed = AsyncMock()

        with respx.mock:
            respx.post("http://localhost:9999/fail").mock(
                return_value=httpx.Response(500, text="Internal Error")
            )
            await craft(
                ctx=ctx,
                name="fail_tool",
                description="always fails",
                params={"x": {"type": "string", "description": "input"}},
                url="http://localhost:9999/fail",
            )

            tool_fn = next(t.fn for t in mcp._tool_manager._tools.values() if t.fn.__name__ == "fail_tool")
            result = await tool_fn(x="anything")

        assert "500" in result

    async def test_craft_shed_removes_tool(self):
        """shed() removes crafted tools."""
        import respx
        import httpx
        from unittest.mock import MagicMock, AsyncMock
        from server import craft, unmount, mcp, session

        ctx = MagicMock()
        ctx.session = MagicMock()
        ctx.session.send_tool_list_changed = AsyncMock()

        with respx.mock:
            respx.post("http://localhost:9999/tmp").mock(return_value=httpx.Response(200, text="ok"))
            await craft(
                ctx=ctx,
                name="tmp_tool",
                description="temp",
                params={"v": {"type": "string", "description": "val"}},
                url="http://localhost:9999/tmp",
            )

        assert "tmp_tool" in session["morphed_tools"]
        await unmount(ctx)
        assert "tmp_tool" not in session["morphed_tools"]

    async def test_craft_invalid_name_rejected(self):
        """Names with special characters are rejected."""
        from unittest.mock import MagicMock, AsyncMock
        from server import craft

        ctx = MagicMock()
        ctx.session = MagicMock()
        ctx.session.send_tool_list_changed = AsyncMock()

        result = await craft(
            ctx=ctx,
            name="bad name!",
            description="x",
            params={},
            url="http://localhost:9999/x",
        )
        assert "alphanumeric" in result.lower()

    async def test_craft_invalid_url_rejected(self):
        """Non-HTTP URLs are rejected."""
        from unittest.mock import MagicMock, AsyncMock
        from server import craft

        ctx = MagicMock()
        ctx.session = MagicMock()
        ctx.session.send_tool_list_changed = AsyncMock()

        result = await craft(
            ctx=ctx,
            name="bad_url",
            description="x",
            params={},
            url="ftp://example.com/tool",
        )
        assert "http" in result.lower()


class TestLeanMorph:
    """Tests for morph(tools=[...]) — lean morph filter."""

    async def test_lean_morph_filters_tools(self):
        """morph(tools=['read_file']) only registers the specified tool."""
        from unittest.mock import MagicMock, AsyncMock, patch
        from server import _registry, mount, session, mcp, ServerInfo

        srv = ServerInfo(
            id="filesystem", name="Filesystem", description="fs",
            source="official", transport="stdio", url="",
            install_cmd=["npx", "-y", "@modelcontextprotocol/server-filesystem"],
            credentials={}, tools=[], token_cost=0,
        )

        all_tools = [
            {"name": "read_file", "description": "read", "inputSchema": {"properties": {}, "required": []}},
            {"name": "write_file", "description": "write", "inputSchema": {"properties": {}, "required": []}},
            {"name": "list_directory", "description": "list", "inputSchema": {"properties": {}, "required": []}},
        ]

        ctx = MagicMock()
        ctx.session = MagicMock()
        ctx.session.send_tool_list_changed = AsyncMock()

        with patch.object(_registry, "get_server", AsyncMock(return_value=srv)), \
             patch("chameleon_mcp.tools.PersistentStdioTransport") as MockTransport:
            mock_t = MagicMock()
            mock_t.list_tools = AsyncMock(return_value=all_tools)
            MockTransport.return_value = mock_t

            result = await mount("filesystem", ctx, tools=["read_file"])

        assert "read_file" in session["morphed_tools"]
        assert "write_file" not in session["morphed_tools"]
        assert "list_directory" not in session["morphed_tools"]
        assert "lean" in result

    async def test_full_morph_registers_all_tools(self):
        """morph() with no tools filter registers everything."""
        from unittest.mock import MagicMock, AsyncMock, patch
        from server import _registry, mount, session, ServerInfo

        srv = ServerInfo(
            id="filesystem", name="Filesystem", description="fs",
            source="official", transport="stdio", url="",
            install_cmd=["npx", "-y", "@modelcontextprotocol/server-filesystem"],
            credentials={}, tools=[], token_cost=0,
        )

        all_tools = [
            {"name": "read_file", "description": "read", "inputSchema": {}},
            {"name": "write_file", "description": "write", "inputSchema": {}},
        ]

        ctx = MagicMock()
        ctx.session = MagicMock()
        ctx.session.send_tool_list_changed = AsyncMock()

        with patch.object(_registry, "get_server", AsyncMock(return_value=srv)), \
             patch("chameleon_mcp.tools.PersistentStdioTransport") as MockTransport:
            mock_t = MagicMock()
            mock_t.list_tools = AsyncMock(return_value=all_tools)
            MockTransport.return_value = mock_t

            await mount("filesystem", ctx)

        assert "read_file" in session["morphed_tools"]
        assert "write_file" in session["morphed_tools"]


# ---------------------------------------------------------------------------
# Phase 1: proactive credential warning in morph()
# ---------------------------------------------------------------------------

class TestMorphCredentialWarning:
    """morph() should warn about missing env vars probed from tool schemas."""

    def _make_srv(self, source="npm"):
        from server import ServerInfo
        return ServerInfo(
            id="org/cred-server", name="cred-server", description="",
            source=source, transport="stdio", url="",
            install_cmd=["npx", "-y", "cred-server"],
            credentials={}, tools=[], token_cost=0,
        )

    async def test_warns_on_missing_credentials(self):
        """morph() output includes key() hint when a tool schema references an unset env var."""
        import os
        from unittest.mock import AsyncMock, MagicMock, patch
        from server import _registry, mount, session

        # Ensure the env var is NOT set
        env_var = "TEST_CRED_SERVER_API_KEY"
        os.environ.pop(env_var, None)

        srv = self._make_srv()
        tools_with_cred = [{
            "name": "do_thing",
            "description": f"Requires {env_var}",
            "inputSchema": {"properties": {}, "required": []},
        }]

        ctx = MagicMock()
        ctx.session = MagicMock()
        ctx.session.send_tool_list_changed = AsyncMock()
        ctx.session.send_resource_list_changed = AsyncMock()
        ctx.session.send_prompt_list_changed = AsyncMock()

        with patch.object(_registry, "get_server", AsyncMock(return_value=srv)), \
             patch("chameleon_mcp.tools.PersistentStdioTransport") as MockT:
            mock_t = MagicMock()
            mock_t.list_tools = AsyncMock(return_value=tools_with_cred)
            mock_t.list_resources = AsyncMock(return_value=[])
            mock_t.list_prompts = AsyncMock(return_value=[])
            MockT.return_value = mock_t

            result = await mount("org/cred-server", ctx)

        assert env_var in result
        assert 'key("' in result

    async def test_no_warning_when_credentials_set(self):
        """No credential warning when the referenced env var is already set."""
        import os
        from unittest.mock import AsyncMock, MagicMock, patch
        from server import _registry, mount

        env_var = "TEST_CRED_ALREADY_SET_KEY"
        os.environ[env_var] = "sk-test-value"

        try:
            srv = self._make_srv()
            tools_with_cred = [{
                "name": "do_thing",
                "description": f"Requires {env_var}",
                "inputSchema": {"properties": {}, "required": []},
            }]

            ctx = MagicMock()
            ctx.session = MagicMock()
            ctx.session.send_tool_list_changed = AsyncMock()
            ctx.session.send_resource_list_changed = AsyncMock()
            ctx.session.send_prompt_list_changed = AsyncMock()

            with patch.object(_registry, "get_server", AsyncMock(return_value=srv)), \
                 patch("chameleon_mcp.tools.PersistentStdioTransport") as MockT:
                mock_t = MagicMock()
                mock_t.list_tools = AsyncMock(return_value=tools_with_cred)
                mock_t.list_resources = AsyncMock(return_value=[])
                mock_t.list_prompts = AsyncMock(return_value=[])
                MockT.return_value = mock_t

                result = await mount("org/cred-server", ctx)

            # No warning since the env var is set
            assert "Credentials may be required" not in result
        finally:
            os.environ.pop(env_var, None)

    async def test_morph_succeeds_when_credential_probe_fails(self):
        """morph() succeeds even if _probe_requirements raises unexpectedly."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from server import _registry, mount

        srv = self._make_srv()

        ctx = MagicMock()
        ctx.session = MagicMock()
        ctx.session.send_tool_list_changed = AsyncMock()
        ctx.session.send_resource_list_changed = AsyncMock()
        ctx.session.send_prompt_list_changed = AsyncMock()

        with patch.object(_registry, "get_server", AsyncMock(return_value=srv)), \
             patch("chameleon_mcp.tools._probe_requirements", side_effect=RuntimeError("probe failed")), \
             patch("chameleon_mcp.tools.PersistentStdioTransport") as MockT:
            mock_t = MagicMock()
            mock_t.list_tools = AsyncMock(return_value=[
                {"name": "simple_tool", "description": "", "inputSchema": {}}
            ])
            mock_t.list_resources = AsyncMock(return_value=[])
            mock_t.list_prompts = AsyncMock(return_value=[])
            MockT.return_value = mock_t

            result = await mount("org/cred-server", ctx)

        # morph must succeed even when probe fails
        assert "Morphed" in result or "simple_tool" in result
