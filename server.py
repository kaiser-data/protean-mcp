"""Chameleon MCP — entry point and re-export facade.

All logic lives in the chameleon_mcp package. This file:
  1. Loads .env before any chameleon_mcp imports read os.getenv() at module level.
  2. Imports all modules so their @mcp.tool() decorators register with the shared mcp instance.
  3. Re-exports public names so existing tests (from server import ...) continue to work.
"""

from dotenv import load_dotenv

# Must run before chameleon_mcp.credentials reads SMITHERY_API_KEY at module level.
load_dotenv()

from chameleon_mcp.app import mcp  # noqa: E402, F401
from chameleon_mcp.constants import *  # noqa: E402, F401, F403
from chameleon_mcp.credentials import (  # noqa: E402, F401
    ENV_PATH,
    SMITHERY_API_KEY,
    _credentials_guide,
    _registry_headers,
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
    MultiRegistry,
    NpmRegistry,
    PyPIRegistry,
    ServerInfo,
    SmitheryRegistry,
    _extract_credentials,
    _registry,
)
from chameleon_mcp.session import session  # noqa: E402, F401
from chameleon_mcp.tools import (  # noqa: E402, F401
    _BASE_TOOL_NAMES,
    auto,
    bench,
    call,
    connect,
    fetch,
    inspect,
    key,
    morph,
    release,
    run,
    search,
    setup,
    shed,
    skill,
    status,
    test,
)
from chameleon_mcp.transport import (  # noqa: E402, F401
    BaseTransport,
    HTTPSSETransport,
    PersistentStdioTransport,
    StdioTransport,
    _evict_stale_pool_entries,
    _ping,
    _PoolEntry,
    _process_pool,
    _read_stdio_response,
)
from chameleon_mcp.utils import (  # noqa: E402, F401
    _clean_response,
    _estimate_tokens,
    _extract_content,
    _get_http_client,
    _strip_html,
    _truncate,
    _try_axonmcp,
)

if __name__ == "__main__":
    mcp.run()
