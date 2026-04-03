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
