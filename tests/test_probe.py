"""Tests for chameleon_mcp/probe.py — readiness probing and setup guide formatting."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from chameleon_mcp.constants import RESOURCE_PRIORITY_KEYWORDS
from chameleon_mcp.probe import (
    _classify_provider,
    _doc_uri_priority,
    _format_setup_guide,
    _probe_requirements,
)

# ---------------------------------------------------------------------------
# _doc_uri_priority
# ---------------------------------------------------------------------------

class TestDocUriPriority:
    def test_env_is_highest_priority(self):
        assert _doc_uri_priority("config://env/vars") == 0

    def test_param_is_second(self):
        assert _doc_uri_priority("config://params") == 1

    def test_auth_key_is_third(self):
        assert _doc_uri_priority("docs://auth/setup") == 2

    def test_key_matches_third_tier(self):
        assert _doc_uri_priority("config://api-key-info") == 2

    def test_quick_setup_is_fourth(self):
        assert _doc_uri_priority("docs://quick-start") == 3

    def test_config_is_fifth(self):
        assert _doc_uri_priority("config://general") == 4

    def test_unknown_uri_returns_max(self):
        assert _doc_uri_priority("other://something-random") == len(RESOURCE_PRIORITY_KEYWORDS)

    def test_env_beats_config(self):
        assert _doc_uri_priority("env://x") < _doc_uri_priority("config://x")


# ---------------------------------------------------------------------------
# _probe_requirements
# ---------------------------------------------------------------------------

class TestProbeRequirements:
    def test_missing_env_var_detected(self, monkeypatch):
        monkeypatch.delenv("MY_API_KEY", raising=False)
        tools = [{"description": "Needs MY_API_KEY", "inputSchema": {}}]
        reqs = _probe_requirements(tools)
        assert "MY_API_KEY" in reqs["missing_env"]

    def test_set_env_var_excluded_from_missing(self, monkeypatch):
        monkeypatch.setenv("MY_API_KEY", "sk-real")
        tools = [{"description": "Needs MY_API_KEY", "inputSchema": {}}]
        reqs = _probe_requirements(tools)
        assert "MY_API_KEY" not in reqs["missing_env"]
        assert "MY_API_KEY" in reqs["set_env"]

    def test_port_suffix_not_treated_as_credential(self, monkeypatch):
        monkeypatch.delenv("SERVER_PORT", raising=False)
        tools = [{"description": "SERVER_PORT=8080", "inputSchema": {}}]
        reqs = _probe_requirements(tools)
        assert "SERVER_PORT" not in reqs["missing_env"]

    def test_structured_not_set_parsed(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        extra = "OPENAI_API_KEY\n  Environment: [not set]"
        reqs = _probe_requirements([], extra_text=extra)
        assert "OPENAI_API_KEY" in reqs["missing_env"]

    def test_structured_set_excluded(self, monkeypatch):
        extra = "OPENAI_API_KEY\n  Environment: sk-live-abc"
        reqs = _probe_requirements([], extra_text=extra)
        assert "OPENAI_API_KEY" not in reqs["missing_env"]
        assert "OPENAI_API_KEY" in reqs["set_env"]

    def test_schema_creds_detected(self):
        tools = [{
            "description": "",
            "inputSchema": {
                "type": "object",
                "properties": {"apiKey": {"type": "string"}, "query": {"type": "string"}},
                "required": ["apiKey"],
            }
        }]
        reqs = _probe_requirements(tools)
        assert "apiKey" in reqs["schema_creds"]
        assert "query" not in reqs["schema_creds"]

    def test_oauth_keywords_detected(self):
        tools = [{"description": "Use OAuth to authorize access.", "inputSchema": {}}]
        reqs = _probe_requirements(tools)
        assert reqs["needs_oauth"] is True

    def test_no_oauth_by_default(self):
        tools = [{"description": "Simple tool", "inputSchema": {}}]
        reqs = _probe_requirements(tools)
        assert reqs["needs_oauth"] is False

    def test_local_url_unreachable(self):
        tools = [{"description": "Connects to http://127.0.0.1:19999", "inputSchema": {}}]
        reqs = _probe_requirements(tools)
        assert "http://127.0.0.1:19999" in reqs["unreachable"]

    def test_provider_enums_extracted(self):
        tools = [{
            "description": "",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "provider": {"type": "string", "enum": ["openai", "anthropic", "local"]},
                },
            }
        }]
        reqs = _probe_requirements(tools)
        assert "provider" in reqs["providers"]
        assert set(reqs["providers"]["provider"]) == {"openai", "anthropic", "local"}

    def test_resource_scan_true_when_extra_text(self):
        reqs = _probe_requirements([], extra_text="some docs")
        assert reqs["resource_scan"] is True

    def test_resource_scan_false_when_no_extra_text(self):
        reqs = _probe_requirements([])
        assert reqs["resource_scan"] is False

    def test_empty_tools_returns_empty_collections(self):
        reqs = _probe_requirements([])
        assert reqs["missing_env"] == []
        assert reqs["unreachable"] == []
        assert reqs["providers"] == {}


# ---------------------------------------------------------------------------
# _classify_provider
# ---------------------------------------------------------------------------

class TestClassifyProvider:
    def test_cloud_ready_when_cred_set(self):
        result = _classify_provider("openai", [], ["OPENAI_API_KEY"], [])
        assert result == "cloud-ready"

    def test_cloud_needs_key_when_cred_missing(self):
        result = _classify_provider("openai", ["OPENAI_API_KEY"], [], [])
        assert result == "cloud-needs-key"

    def test_local_when_url_unreachable(self):
        result = _classify_provider("kokoro", [], [], ["http://127.0.0.1:8080"])
        assert result == "local"

    def test_unknown_when_no_signals(self):
        result = _classify_provider("mystery", [], [], [])
        assert result == "unknown"


# ---------------------------------------------------------------------------
# _format_setup_guide
# ---------------------------------------------------------------------------

class TestFormatSetupGuide:
    def _reqs(self, **overrides):
        base = {
            "missing_env": [],
            "set_env": [],
            "schema_creds": [],
            "needs_oauth": False,
            "unreachable": [],
            "reachable": [],
            "providers": {},
            "resource_text": "",
            "resource_scan": False,
        }
        base.update(overrides)
        return base

    def test_all_satisfied_returns_check_mark(self):
        reqs = self._reqs(set_env=["SOME_KEY"])
        result = _format_setup_guide(reqs, "myserver")
        assert "✅" in result

    def test_missing_env_shown(self):
        reqs = self._reqs(missing_env=["MY_API_KEY"])
        result = _format_setup_guide(reqs, "myserver")
        assert "MY_API_KEY" in result

    def test_missing_uses_key_command(self):
        reqs = self._reqs(missing_env=["EXA_API_KEY"])
        result = _format_setup_guide(reqs, "myserver")
        assert 'key("EXA_API_KEY"' in result

    def test_no_service_hint_without_service_tool(self):
        reqs = self._reqs(
            providers={"provider": ["openai", "local"]},
            unreachable=["http://127.0.0.1:8000"],
        )
        result = _format_setup_guide(reqs, "myserver", tools=None)
        assert "service(" not in result

    def test_letter_labels_present(self):
        reqs = self._reqs(
            providers={"provider": ["openai", "local"]},
            missing_env=["OPENAI_API_KEY"],
            unreachable=["http://127.0.0.1:8000"],
        )
        result = _format_setup_guide(reqs, "myserver")
        assert "[A]" in result
        assert "[B]" in result

    def test_empty_all_returns_empty_string(self):
        reqs = self._reqs()
        result = _format_setup_guide(reqs, "myserver")
        assert result == ""
