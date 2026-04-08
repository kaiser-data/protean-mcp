"""Protean MCP — entry point and re-export facade.

All logic lives in the chameleon_mcp package. This file:
  1. Loads .env before any chameleon_mcp imports read os.getenv() at module level.
  2. Imports all modules so their @mcp.tool() decorators register with the shared mcp instance.
  3. Prunes tools based on CHAMELEON_TOOLS env var (default: lean 7-tool profile).
  4. Re-exports public names so existing tests (from server import ...) continue to work.

CHAMELEON_TOOLS env var controls which tools are registered:
  (not set)                     — lean profile: mount, unmount, search, inspect, key, status, call
  CHAMELEON_TOOLS=all           — all 17 tools (forge / evaluator mode)
  CHAMELEON_TOOLS=mount,unmount — exactly those tools
"""

import os

from dotenv import load_dotenv

# Must run before chameleon_mcp.credentials reads SMITHERY_API_KEY at module level.
load_dotenv()

from chameleon_mcp.app import mcp  # noqa: E402, F401
from chameleon_mcp.constants import *  # noqa: E402, F401, F403
from chameleon_mcp.credentials import (  # noqa: E402, F401
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
from chameleon_mcp.morph import (  # noqa: E402, F401
    _do_shed,
    _fetch_tools_list,
    _json_type_to_py,
    _make_proxy,
    _register_proxy_prompts,
    _register_proxy_resources,
    _register_proxy_tools,
)
from chameleon_mcp.official_registry import OfficialMCPRegistry  # noqa: E402, F401
from chameleon_mcp.probe import (  # noqa: E402, F401
    _ENV_VAR_RE,
    _LOCAL_URL_RE,
    _classify_provider,
    _doc_uri_priority,
    _format_setup_guide,
    _probe_requirements,
)
from chameleon_mcp.registry import (  # noqa: E402, F401
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
from chameleon_mcp.session import (  # noqa: E402, F401
    SKILLS_PATH,
    _load_skills,
    _save_skills,
    session,
)
from chameleon_mcp.tools import (  # noqa: E402, F401
    _BASE_TOOL_NAMES,
    auto,
    bench,
    call,
    connect,
    craft,
    fetch,
    inspect,
    key,
    mount,
    release,
    run,
    search,
    setup,
    skill,
    status,
    test,
    unmount,
)
from chameleon_mcp.transport import (  # noqa: E402, F401
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
from chameleon_mcp.utils import (  # noqa: E402, F401
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

_LEAN_TOOLS = {"mount", "unmount", "search", "inspect", "key", "status", "call"}
_CHAMELEON_TOOLS_ENV = os.getenv("CHAMELEON_TOOLS", "")

if _CHAMELEON_TOOLS_ENV.lower() == "all":
    _active_tools = _BASE_TOOL_NAMES
elif _CHAMELEON_TOOLS_ENV:
    _active_tools = {t.strip() for t in _CHAMELEON_TOOLS_ENV.split(",")} & _BASE_TOOL_NAMES
else:
    _active_tools = _LEAN_TOOLS

for _t in _BASE_TOOL_NAMES - _active_tools:
    try:
        mcp.remove_tool(_t)
    except Exception:
        pass

if __name__ == "__main__":
    mcp.run()
