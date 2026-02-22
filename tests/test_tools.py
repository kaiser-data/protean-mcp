"""Tests for tool helper functions: _truncate, _clean_response, _estimate_tokens, _credentials_guide."""
import pytest

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from server import _truncate, _clean_response, _estimate_tokens, _credentials_guide


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
        assert "apiKey" in result
        assert "API_KEY" in result  # env var conversion

    def test_shows_key_command(self):
        credentials = {"apiKey": "API key description"}
        resolved = {}
        result = _credentials_guide("my-server", credentials, resolved)
        assert "key(" in result

    def test_shows_inline_call_example(self):
        credentials = {"token": "Auth token", "secret": "Secret value"}
        resolved = {}
        result = _credentials_guide("my-server", credentials, resolved)
        assert "call(" in result
        assert '"token"' in result

    def test_multiple_missing_all_shown(self):
        credentials = {
            "apiKey": "Key A",
            "token": "Key B",
            "secret": "Key C",
        }
        resolved = {"apiKey": "already-set"}
        result = _credentials_guide("multi-server", credentials, resolved)
        assert "token" in result
        assert "secret" in result
        # apiKey is resolved so should not appear in missing list
