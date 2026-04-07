"""Tests for MCP notification calls: send_tool/resource/prompt_list_changed."""
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from server import ServerInfo, _registry, morph, session, shed


def _make_ctx(*, tools=True, resources=True, prompts=True):
    """Build a mock Context with AsyncMock notification methods."""
    ctx = MagicMock()
    ctx.session = MagicMock()
    if tools:
        ctx.session.send_tool_list_changed = AsyncMock()
    if resources:
        ctx.session.send_resource_list_changed = AsyncMock()
    if prompts:
        ctx.session.send_prompt_list_changed = AsyncMock()
    return ctx


def _make_srv(source="official", transport="stdio"):
    return ServerInfo(
        id="org/notif-server", name="notif-server", description="",
        source=source, transport=transport, url="" if transport != "http" else "org/notif-server",
        install_cmd=["npx", "-y", "notif-server"] if transport == "stdio" else None,
        credentials={}, tools=[], token_cost=0,
    )


# ---------------------------------------------------------------------------
# morph() notification behaviour
# ---------------------------------------------------------------------------

class TestMorphNotifications:

    async def test_tool_list_changed_called_once_on_morph(self):
        """send_tool_list_changed is called exactly once on a successful morph."""
        ctx = _make_ctx()
        srv = _make_srv()

        with patch.object(_registry, "get_server", AsyncMock(return_value=srv)), \
             patch("chameleon_mcp.tools._register_proxy_tools", return_value=["tool_a"]), \
             patch("chameleon_mcp.tools.PersistentStdioTransport") as MockT:
            mt = MagicMock()
            mt.list_tools = AsyncMock(return_value=[{"name": "tool_a", "description": "", "inputSchema": {}}])
            mt.list_resources = AsyncMock(return_value=[])
            mt.list_prompts = AsyncMock(return_value=[])
            MockT.return_value = mt
            await morph("org/notif-server", ctx)

        ctx.session.send_tool_list_changed.assert_called_once()

    async def test_resource_notification_not_sent_when_no_resources(self):
        """send_resource_list_changed is NOT called when morph yields zero resources."""
        ctx = _make_ctx()
        srv = _make_srv()

        with patch.object(_registry, "get_server", AsyncMock(return_value=srv)), \
             patch("chameleon_mcp.tools._register_proxy_tools", return_value=["tool_a"]), \
             patch("chameleon_mcp.tools._register_proxy_resources", return_value=[]) as mock_rr, \
             patch("chameleon_mcp.tools._register_proxy_prompts", return_value=[]), \
             patch("chameleon_mcp.tools.PersistentStdioTransport") as MockT:
            mt = MagicMock()
            mt.list_tools = AsyncMock(return_value=[{"name": "tool_a", "description": "", "inputSchema": {}}])
            mt.list_resources = AsyncMock(return_value=[])
            mt.list_prompts = AsyncMock(return_value=[])
            MockT.return_value = mt
            await morph("org/notif-server", ctx)

        ctx.session.send_resource_list_changed.assert_not_called()

    async def test_resource_notification_sent_when_resources_registered(self):
        """send_resource_list_changed IS called when morph registers ≥1 resource."""
        ctx = _make_ctx()
        srv = _make_srv()

        with patch.object(_registry, "get_server", AsyncMock(return_value=srv)), \
             patch("chameleon_mcp.tools._register_proxy_tools", return_value=["tool_a"]), \
             patch("chameleon_mcp.tools._register_proxy_resources", return_value=["config://srv/r1"]), \
             patch("chameleon_mcp.tools._register_proxy_prompts", return_value=[]), \
             patch("chameleon_mcp.tools.PersistentStdioTransport") as MockT:
            mt = MagicMock()
            mt.list_tools = AsyncMock(return_value=[{"name": "tool_a", "description": "", "inputSchema": {}}])
            mt.list_resources = AsyncMock(return_value=[{"uri": "config://srv/r1", "name": "r1"}])
            mt.list_prompts = AsyncMock(return_value=[])
            MockT.return_value = mt
            await morph("org/notif-server", ctx)

        ctx.session.send_resource_list_changed.assert_called_once()

    async def test_prompt_notification_not_sent_when_no_prompts(self):
        """send_prompt_list_changed is NOT called when morph yields zero prompts."""
        ctx = _make_ctx()
        srv = _make_srv()

        with patch.object(_registry, "get_server", AsyncMock(return_value=srv)), \
             patch("chameleon_mcp.tools._register_proxy_tools", return_value=["tool_a"]), \
             patch("chameleon_mcp.tools._register_proxy_resources", return_value=[]), \
             patch("chameleon_mcp.tools._register_proxy_prompts", return_value=[]), \
             patch("chameleon_mcp.tools.PersistentStdioTransport") as MockT:
            mt = MagicMock()
            mt.list_tools = AsyncMock(return_value=[{"name": "tool_a", "description": "", "inputSchema": {}}])
            mt.list_resources = AsyncMock(return_value=[])
            mt.list_prompts = AsyncMock(return_value=[])
            MockT.return_value = mt
            await morph("org/notif-server", ctx)

        ctx.session.send_prompt_list_changed.assert_not_called()

    async def test_prompt_notification_sent_when_prompts_registered(self):
        """send_prompt_list_changed IS called when morph registers ≥1 prompt."""
        ctx = _make_ctx()
        srv = _make_srv()

        with patch.object(_registry, "get_server", AsyncMock(return_value=srv)), \
             patch("chameleon_mcp.tools._register_proxy_tools", return_value=["tool_a"]), \
             patch("chameleon_mcp.tools._register_proxy_resources", return_value=[]), \
             patch("chameleon_mcp.tools._register_proxy_prompts", return_value=["my_prompt"]), \
             patch("chameleon_mcp.tools.PersistentStdioTransport") as MockT:
            mt = MagicMock()
            mt.list_tools = AsyncMock(return_value=[{"name": "tool_a", "description": "", "inputSchema": {}}])
            mt.list_resources = AsyncMock(return_value=[])
            mt.list_prompts = AsyncMock(return_value=[{"name": "my_prompt", "description": "", "arguments": []}])
            MockT.return_value = mt
            await morph("org/notif-server", ctx)

        ctx.session.send_prompt_list_changed.assert_called_once()

    async def test_no_notifications_when_morph_fails_no_tools(self):
        """No notifications sent when morph finds no tools to register."""
        ctx = _make_ctx()
        srv = _make_srv()

        with patch.object(_registry, "get_server", AsyncMock(return_value=srv)), \
             patch("chameleon_mcp.tools.PersistentStdioTransport") as MockT:
            mt = MagicMock()
            mt.list_tools = AsyncMock(return_value=[])  # no tools
            MockT.return_value = mt
            result = await morph("org/notif-server", ctx)

        assert "No tools" in result
        ctx.session.send_tool_list_changed.assert_not_called()

    async def test_no_notifications_when_server_not_found(self):
        """No notifications when registry lookup fails."""
        ctx = _make_ctx()

        with patch.object(_registry, "get_server", AsyncMock(return_value=None)):
            result = await morph("nonexistent/server", ctx)

        assert "not found" in result.lower()
        ctx.session.send_tool_list_changed.assert_not_called()


# ---------------------------------------------------------------------------
# shed() notification behaviour
# ---------------------------------------------------------------------------

class TestShedNotifications:

    async def _morph_first(self, ctx):
        """Helper: morph in a tool so shed() has something to remove."""
        srv = _make_srv()
        with patch.object(_registry, "get_server", AsyncMock(return_value=srv)), \
             patch("chameleon_mcp.tools._register_proxy_tools", return_value=["tool_a"]), \
             patch("chameleon_mcp.tools._register_proxy_resources", return_value=[]), \
             patch("chameleon_mcp.tools._register_proxy_prompts", return_value=[]), \
             patch("chameleon_mcp.tools.PersistentStdioTransport") as MockT:
            mt = MagicMock()
            mt.list_tools = AsyncMock(return_value=[{"name": "tool_a", "description": "", "inputSchema": {}}])
            mt.list_resources = AsyncMock(return_value=[])
            mt.list_prompts = AsyncMock(return_value=[])
            MockT.return_value = mt
            await morph("org/notif-server", ctx)

    async def test_tool_list_changed_called_on_shed(self):
        """send_tool_list_changed is called exactly once on shed()."""
        ctx_morph = _make_ctx()
        await self._morph_first(ctx_morph)

        ctx_shed = _make_ctx()
        await shed(ctx_shed)

        ctx_shed.session.send_tool_list_changed.assert_called_once()

    async def test_resource_notification_on_shed_only_if_resources_existed(self):
        """send_resource_list_changed is called on shed only if resources were morphed."""
        ctx_morph = _make_ctx()
        srv = _make_srv()
        with patch.object(_registry, "get_server", AsyncMock(return_value=srv)), \
             patch("chameleon_mcp.tools._register_proxy_tools", return_value=["tool_a"]), \
             patch("chameleon_mcp.tools._register_proxy_resources", return_value=["config://srv/r1"]), \
             patch("chameleon_mcp.tools._register_proxy_prompts", return_value=[]), \
             patch("chameleon_mcp.tools.PersistentStdioTransport") as MockT:
            mt = MagicMock()
            mt.list_tools = AsyncMock(return_value=[{"name": "tool_a", "description": "", "inputSchema": {}}])
            mt.list_resources = AsyncMock(return_value=[{"uri": "config://srv/r1", "name": "r1"}])
            mt.list_prompts = AsyncMock(return_value=[])
            MockT.return_value = mt
            await morph("org/notif-server", ctx_morph)

        # Inject resource into session so shed sees it
        session["morphed_resources"] = ["config://srv/r1"]

        ctx_shed = _make_ctx()
        await shed(ctx_shed)

        ctx_shed.session.send_resource_list_changed.assert_called_once()

    async def test_no_notification_on_shed_when_already_in_base_form(self):
        """No notifications when shed() called with nothing morphed."""
        # Ensure clean state
        session["morphed_tools"] = []
        session["morphed_resources"] = []
        session["morphed_prompts"] = []

        ctx = _make_ctx()
        result = await shed(ctx)

        assert result == "Already in base form."
        ctx.session.send_tool_list_changed.assert_not_called()
        ctx.session.send_resource_list_changed.assert_not_called()
        ctx.session.send_prompt_list_changed.assert_not_called()
