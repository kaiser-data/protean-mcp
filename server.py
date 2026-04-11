"""Kitsune MCP — entry point and re-export facade.

All logic lives in the kitsune_mcp package. This file:
  1. Loads .env before any kitsune_mcp imports read os.getenv() at module level.
  2. Imports all modules so their @mcp.tool() decorators register with the shared mcp instance.
  3. Prunes tools based on KITSUNE_TOOLS env var (default: lean 7-tool profile).
  4. Re-exports public names so existing tests (from server import ...) continue to work.

KITSUNE_TOOLS env var controls which tools are registered:
  (not set)                     — lean profile: shapeshift, shiftback, search, inspect, key, status, call
  KITSUNE_TOOLS=all           — all 17 tools (forge / evaluator mode)
  KITSUNE_TOOLS=shapeshift,shiftback — exactly those tools
"""

import contextlib
import os

from dotenv import load_dotenv

# Must run before kitsune_mcp.credentials reads SMITHERY_API_KEY at module level.
load_dotenv()

from kitsune_mcp.app import mcp  # noqa: E402, F401
from kitsune_mcp.constants import *  # noqa: E402, F401, F403
from kitsune_mcp.credentials import (  # noqa: E402, F401
    ENV_PATH,
    SMITHERY_API_KEY,
    _credentials_guide,
    _credentials_inspect_block,
    _dotenv_revision,
    _registry_headers,
    _reload_dotenv,
    _resolve_config,
    _save_to_env,
    _smithery_available,
    _to_env_var,
)
from kitsune_mcp.official_registry import OfficialMCPRegistry  # noqa: E402, F401
from kitsune_mcp.probe import (  # noqa: E402, F401
    _ENV_VAR_RE,
    _LOCAL_URL_RE,
    _classify_provider,
    _doc_uri_priority,
    _format_setup_guide,
    _probe_requirements,
)
from kitsune_mcp.registry import (  # noqa: E402, F401
    _CACHE_TTL_SEARCH,
    _CACHE_TTL_SERVER,
    REGISTRY_BASE,
    BaseRegistry,
    GitHubRegistry,
    GlamaRegistry,
    McpRegistryIO,
    MultiRegistry,
    NpmRegistry,
    PyPIRegistry,
    ServerInfo,
    SmitheryRegistry,
    _dedup_key,
    _detect_github_install_cmd,
    _extract_credentials,
    _registry,
    _relevance_score,
)
from kitsune_mcp.session import (  # noqa: E402, F401
    SKILLS_PATH,
    _load_skills,
    _save_skills,
    session,
)
from kitsune_mcp.shapeshift import (  # noqa: E402, F401
    _do_shed,
    _fetch_tools_list,
    _json_type_to_py,
    _make_proxy,
    _register_proxy_prompts,
    _register_proxy_resources,
    _register_proxy_tools,
)
from kitsune_mcp.tools import (  # noqa: E402, F401
    _BASE_TOOL_NAMES,
    auto,
    bench,
    call,
    cast_off,  # deprecated alias — kept for programmatic callers
    connect,
    craft,
    fetch,
    inspect,
    key,
    mount,  # deprecated alias — kept for programmatic callers
    receive,  # deprecated alias — kept for programmatic callers
    release,
    run,
    search,
    setup,
    shapeshift,
    shiftback,
    skill,
    status,
    test,
    unmount,  # deprecated alias — kept for programmatic callers
)
from kitsune_mcp.transport import (  # noqa: E402, F401
    BaseTransport,
    DockerTransport,
    HTTPSSETransport,
    PersistentStdioTransport,
    StdioTransport,
    WebSocketTransport,
    _evict_stale_pool_entries,
    _ping,
    _PoolEntry,
    _process_pool,
    _read_stdio_response,
    _validate_install_cmd,
)
from kitsune_mcp.utils import (  # noqa: E402, F401
    _clean_response,
    _estimate_tokens,
    _extract_content,
    _get_http_client,
    _rss_mb,
    _strip_html,
    _truncate,
    _try_axonmcp,
)

# ── Tool profile selection ────────────────────────────────────────────────────
# All tools registered above via @mcp.tool(). Prune to the requested profile.

_LEAN_TOOLS = {"shapeshift", "shiftback", "search", "inspect", "key", "status", "call"}
_KITSUNE_TOOLS_ENV = os.getenv("KITSUNE_TOOLS", "")

if _KITSUNE_TOOLS_ENV.lower() == "all":
    _active_tools = _BASE_TOOL_NAMES
elif _KITSUNE_TOOLS_ENV:
    _active_tools = {t.strip() for t in _KITSUNE_TOOLS_ENV.split(",")} & _BASE_TOOL_NAMES
else:
    _active_tools = _LEAN_TOOLS

for _t in _BASE_TOOL_NAMES - _active_tools:
    with contextlib.suppress(Exception):
        mcp.remove_tool(_t)

if __name__ == "__main__":
    mcp.run()
