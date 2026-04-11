"""OfficialMCPRegistry — reference servers from modelcontextprotocol/servers.

Uses a hardcoded seed list of known-stable servers (no network required) plus an
optional live fetch from the GitHub API to discover newer additions (24h TTL cache).
"""

from kitsune_mcp.constants import (
    OFFICIAL_REGISTRY_CACHE_TTL,
    TIMEOUT_FETCH_URL,
)
from kitsune_mcp.registry import BaseRegistry, ServerInfo, TTLCache, _simple_search
from kitsune_mcp.utils import _get_http_client

# ---------------------------------------------------------------------------
# Hardcoded seed list — always available, no network required
# ---------------------------------------------------------------------------

_SEED_SERVERS: list[dict] = [
    {
        "id": "@modelcontextprotocol/server-filesystem",
        "name": "Filesystem",
        "description": "Read and write files, list directories, and manage the local filesystem.",
        "transport": "stdio",
        "install_cmd": ["npx", "-y", "@modelcontextprotocol/server-filesystem"],
    },
    {
        "id": "@modelcontextprotocol/server-memory",
        "name": "Memory",
        "description": "Persistent memory for Claude using a knowledge graph stored locally.",
        "transport": "stdio",
        "install_cmd": ["npx", "-y", "@modelcontextprotocol/server-memory"],
    },
    {
        "id": "@modelcontextprotocol/server-sequential-thinking",
        "name": "Sequential Thinking",
        "description": "Dynamic problem-solving through structured sequential thought chains.",
        "transport": "stdio",
        "install_cmd": ["npx", "-y", "@modelcontextprotocol/server-sequential-thinking"],
    },
    {
        "id": "@modelcontextprotocol/server-everything",
        "name": "Everything (MCP Reference)",
        "description": "Reference implementation exercising all MCP protocol features.",
        "transport": "stdio",
        "install_cmd": ["npx", "-y", "@modelcontextprotocol/server-everything"],
    },
    {
        "id": "mcp-server-git",
        "name": "Git",
        "description": "Read, search, and manipulate Git repositories programmatically.",
        "transport": "stdio",
        "install_cmd": ["uvx", "mcp-server-git"],
    },
    {
        "id": "mcp-server-time",
        "name": "Time",
        "description": "Time queries and timezone conversions.",
        "transport": "stdio",
        "install_cmd": ["uvx", "mcp-server-time"],
    },
    {
        "id": "mcp-server-fetch",
        "name": "Fetch",
        "description": "Fetch web pages and return their content as clean text or markdown.",
        "transport": "stdio",
        "install_cmd": ["uvx", "mcp-server-fetch"],
    },
]

_SEED_BY_ID: dict[str, dict] = {s["id"]: s for s in _SEED_SERVERS}

# ---------------------------------------------------------------------------
# Live fetch cache — GitHub directory listing to pick up new servers
# ---------------------------------------------------------------------------

_live_cache: TTLCache[list[ServerInfo]] = TTLCache(OFFICIAL_REGISTRY_CACHE_TTL)

_GITHUB_SRC_API = "https://api.github.com/repos/modelcontextprotocol/servers/contents/src"


def _server_from_seed(entry: dict) -> ServerInfo:
    return ServerInfo(
        id=entry["id"],
        name=entry["name"],
        description=entry["description"],
        source="official",
        transport=entry["transport"],
        url="",
        install_cmd=entry["install_cmd"],
        credentials={},
        tools=[],
        token_cost=0,
    )


async def _fetch_live_servers() -> list[ServerInfo]:
    """Try to fetch the src/ directory listing from GitHub and extend the seed list."""
    cached = _live_cache.get()
    if cached is not None:
        return cached

    try:
        r = await _get_http_client().get(
            _GITHUB_SRC_API,
            headers={"Accept": "application/vnd.github.v3+json"},
            timeout=TIMEOUT_FETCH_URL,
        )
        r.raise_for_status()
        dirs = [item["name"] for item in r.json() if item.get("type") == "dir"]
    except Exception:
        dirs = []

    servers: list[ServerInfo] = []
    seen_ids: set[str] = set()

    # First, include seeds in order (always authoritative)
    for s in _SEED_SERVERS:
        servers.append(_server_from_seed(s))
        seen_ids.add(s["id"])

    # Map directory names to their actual package names (some differ from dirname)
    _NPM_NAME_OVERRIDES = {
        "sequentialthinking": "sequential-thinking",
    }
    _PIP_DIRS = {"git", "time", "fetch"}

    # Add any directories not covered by the seed list
    for dirname in dirs:
        if dirname in _PIP_DIRS:
            pkg_id = f"mcp-server-{dirname}"
            install_cmd = ["uvx", pkg_id]
        else:
            pkg_suffix = _NPM_NAME_OVERRIDES.get(dirname, dirname)
            pkg_id = f"@modelcontextprotocol/server-{pkg_suffix}"
            install_cmd = ["npx", "-y", pkg_id]
        if pkg_id in seen_ids:
            continue
        servers.append(ServerInfo(
            id=pkg_id,
            name=dirname.replace("-", " ").title(),
            description=f"Official MCP server: {dirname}",
            source="official",
            transport="stdio",
            url="",
            install_cmd=install_cmd,
            credentials={},
            tools=[],
            token_cost=0,
        ))
        seen_ids.add(pkg_id)

    _live_cache.set(servers)
    return servers


class OfficialMCPRegistry(BaseRegistry):
    """Registry of reference servers from github.com/modelcontextprotocol/servers."""

    async def search(self, query: str, limit: int) -> list[ServerInfo]:
        return _simple_search(await _fetch_live_servers(), query, limit)

    async def get_server(self, id: str) -> ServerInfo | None:
        # Check seed list first (instant, no network)
        if id in _SEED_BY_ID:
            return _server_from_seed(_SEED_BY_ID[id])
        # Try the live cache / fetch
        servers = await _fetch_live_servers()
        return next((s for s in servers if s.id == id), None)
