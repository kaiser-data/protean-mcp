import asyncio
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from chameleon_mcp.constants import MAX_EXPLORE_DESC, TIMEOUT_FETCH_URL
from chameleon_mcp.credentials import _registry_headers, _smithery_available
from chameleon_mcp.utils import _estimate_tokens, _get_http_client

REGISTRY_BASE = "https://registry.smithery.ai"


@dataclass
class ServerInfo:
    id: str
    name: str
    description: str
    source: str           # "smithery" | "npm"
    transport: str        # "http" | "stdio"
    url: str = ""
    install_cmd: list = field(default_factory=list)
    credentials: dict = field(default_factory=dict)  # {field: description}
    tools: list = field(default_factory=list)         # lazy-loaded
    token_cost: int = 0


class BaseRegistry(ABC):
    @abstractmethod
    async def search(self, query: str, limit: int) -> list: ...

    @abstractmethod
    async def get_server(self, id: str): ...


def _extract_credentials(server_dict: dict) -> dict:
    credentials = {}
    for conn in server_dict.get("connections", []):
        for k, val in conn.get("configSchema", {}).get("properties", {}).items():
            credentials[k] = val.get("description", "")
    return credentials


class SmitheryRegistry(BaseRegistry):
    async def search(self, query: str, limit: int) -> list:
        if not _smithery_available():
            return []
        try:
            r = await _get_http_client().get(
                f"{REGISTRY_BASE}/servers",
                params={"q": f"{query} is:verified", "pageSize": limit},
                headers=_registry_headers(),
                timeout=TIMEOUT_FETCH_URL,
            )
            r.raise_for_status()
            data = r.json()
        except Exception:
            return []

        results = []
        for s in data.get("servers", []):
            qname = s.get("qualifiedName", "")
            if not qname:
                continue
            credentials = _extract_credentials(s)
            remote = s.get("remote", False)
            results.append(ServerInfo(
                id=qname,
                name=s.get("displayName") or qname,
                description=(s.get("description") or "").strip()[:MAX_EXPLORE_DESC],
                source="smithery",
                transport="http" if remote else "stdio",
                url=f"https://server.smithery.ai/{qname}" if remote else "",
                install_cmd=[],
                credentials=credentials,
                tools=[],
                token_cost=0,
            ))
        return results

    async def get_server(self, id: str):
        if not _smithery_available():
            return None
        try:
            r = await _get_http_client().get(
                f"{REGISTRY_BASE}/servers/{id}",
                headers=_registry_headers(),
                timeout=TIMEOUT_FETCH_URL,
            )
            r.raise_for_status()
            s = r.json()
        except Exception:
            return None

        credentials = _extract_credentials(s)
        tools = s.get("tools") or []
        remote = s.get("remote", False)
        qname = s.get("qualifiedName", id)
        return ServerInfo(
            id=qname,
            name=s.get("displayName") or qname,
            description=(s.get("description") or "").strip(),
            source="smithery",
            transport="http" if remote else "stdio",
            url=f"https://server.smithery.ai/{qname}" if remote else "",
            install_cmd=[],
            credentials=credentials,
            tools=tools,
            token_cost=_estimate_tokens(tools),
        )


class NpmRegistry(BaseRegistry):
    """Search npm for MCP server packages — no auth required."""

    async def search(self, query: str, limit: int) -> list:
        try:
            r = await _get_http_client().get(
                "https://registry.npmjs.org/-/v1/search",
                params={"text": f"mcp-server {query}", "size": limit * 2},
                timeout=TIMEOUT_FETCH_URL,
            )
            r.raise_for_status()
            data = r.json()
        except Exception:
            return []

        results = []
        for obj in data.get("objects", []):
            pkg = obj.get("package", {})
            name = pkg.get("name", "")
            if not name:
                continue
            keywords = [k.lower() for k in (pkg.get("keywords") or [])]
            if not any(k in ("mcp", "model-context-protocol", "mcp-server") for k in keywords):
                continue
            desc = (pkg.get("description") or "").strip()[:MAX_EXPLORE_DESC]
            results.append(ServerInfo(
                id=name,
                name=name,
                description=desc,
                source="npm",
                transport="stdio",
                url="",
                install_cmd=["npx", "-y", name],
                credentials={},
                tools=[],
                token_cost=0,
            ))
            if len(results) >= limit:
                break
        return results

    async def get_server(self, id: str):
        try:
            r = await _get_http_client().get(
                f"https://registry.npmjs.org/{id}",
                timeout=TIMEOUT_FETCH_URL,
            )
            r.raise_for_status()
            pkg = r.json()
        except Exception:
            return None

        latest = pkg.get("dist-tags", {}).get("latest", "")
        version_data = pkg.get("versions", {}).get(latest, {})
        desc = (version_data.get("description") or pkg.get("description") or "").strip()
        return ServerInfo(
            id=id,
            name=id,
            description=desc,
            source="npm",
            transport="stdio",
            url="",
            install_cmd=["npx", "-y", id],
            credentials={},
            tools=[],
            token_cost=0,
        )


class PyPIRegistry(BaseRegistry):
    """Search PyPI for MCP server packages (installed via uvx)."""

    async def search(self, query: str, limit: int) -> list:
        try:
            r = await _get_http_client().get(
                "https://pypi.org/search/",
                params={"q": f"mcp-server {query}"},
                headers={"Accept": "text/html"},
                timeout=TIMEOUT_FETCH_URL,
            )
            r.raise_for_status()
            names = re.findall(r'class="package-snippet__name"[^>]*>\s*([^<\s][^<]*?)\s*<', r.text)
            descs = re.findall(r'class="package-snippet__description"[^>]*>\s*([^<]*?)\s*<', r.text)
        except Exception:
            return []

        results = []
        for i, name in enumerate(names[:limit]):
            name = name.strip()
            if not name:
                continue
            desc = descs[i].strip() if i < len(descs) else ""
            results.append(ServerInfo(
                id=name,
                name=name,
                description=desc[:MAX_EXPLORE_DESC],
                source="pypi",
                transport="stdio",
                url="",
                install_cmd=["uvx", name],
                credentials={},
                tools=[],
                token_cost=0,
            ))
        return results

    async def get_server(self, id: str):
        try:
            r = await _get_http_client().get(
                f"https://pypi.org/pypi/{id}/json",
                timeout=TIMEOUT_FETCH_URL,
            )
            r.raise_for_status()
            data = r.json()
        except Exception:
            return None

        info = data.get("info", {})
        desc = (info.get("summary") or "").strip()
        return ServerInfo(
            id=id,
            name=id,
            description=desc,
            source="pypi",
            transport="stdio",
            url="",
            install_cmd=["uvx", id],
            credentials={},
            tools=[],
            token_cost=0,
        )


async def _detect_github_install_cmd(owner: str, repo: str) -> list[str]:
    """Probe a GitHub repo for package.json vs pyproject.toml to pick npx vs uvx."""
    import base64 as _b64
    base_url = f"https://api.github.com/repos/{owner}/{repo}/contents"
    headers = {"Accept": "application/vnd.github.v3+json"}
    client = _get_http_client()

    # Check package.json → npm
    try:
        r = await client.get(f"{base_url}/package.json", headers=headers, timeout=TIMEOUT_FETCH_URL)
        if r.status_code == 200:
            return ["npx", f"github:{owner}/{repo}"]
    except Exception:
        pass

    # Check pyproject.toml → pip/uvx; try to extract script name
    try:
        r = await client.get(f"{base_url}/pyproject.toml", headers=headers, timeout=TIMEOUT_FETCH_URL)
        if r.status_code == 200:
            content = _b64.b64decode(r.json().get("content", "")).decode(errors="replace")
            m = re.search(r'\[project\.scripts\][^\[]*?\n(\S+)\s*=', content)
            script = m.group(1).strip("\"'") if m else repo
            return ["uvx", "--from", f"git+https://github.com/{owner}/{repo}", script]
    except Exception:
        pass

    # Fallback: assume npm
    return ["npx", f"github:{owner}/{repo}"]


class GitHubRegistry(BaseRegistry):
    """Resolve github:owner/repo IDs to installable ServerInfo — no registry search needed."""

    async def search(self, query: str, limit: int) -> list:
        return []

    async def get_server(self, id: str) -> ServerInfo | None:
        if not id.startswith("github:"):
            return None
        slug = id[len("github:"):]
        if slug.count("/") != 1:
            return None
        owner, repo = slug.split("/", 1)
        if not owner or not repo:
            return None

        async def _fetch_meta() -> dict:
            try:
                r = await _get_http_client().get(
                    f"https://api.github.com/repos/{owner}/{repo}",
                    headers={"Accept": "application/vnd.github.v3+json"},
                    timeout=TIMEOUT_FETCH_URL,
                )
                r.raise_for_status()
                return r.json()
            except Exception:
                return {}

        meta, install_cmd = await asyncio.gather(
            _fetch_meta(),
            _detect_github_install_cmd(owner, repo),
        )

        return ServerInfo(
            id=id,
            name=meta.get("name") or repo,
            description=(meta.get("description") or "").strip()[:MAX_EXPLORE_DESC],
            source="github",
            transport="stdio",
            url="",
            install_cmd=install_cmd,
            credentials={},
            tools=[],
            token_cost=0,
        )


_CACHE_TTL_SERVER = 300.0   # 5 minutes — server metadata rarely changes
_CACHE_TTL_SEARCH = 60.0    # 1 minute — search results can shift


class MultiRegistry(BaseRegistry):
    """Fan out to all registries, dedup by name, Official → GitHub → Smithery → npm priority."""

    def __init__(self):
        from chameleon_mcp.official_registry import OfficialMCPRegistry
        self._registries = [OfficialMCPRegistry(), GitHubRegistry(), SmitheryRegistry(), NpmRegistry()]
        self._server_cache: dict[str, tuple] = {}   # id → (ServerInfo|None, expires_at)
        self._search_cache: dict[tuple, tuple] = {} # (query, limit) → (list, expires_at)

    def bust_cache(self, server_id: str | None = None) -> None:
        """Invalidate cache. Pass server_id to bust a single entry, or None for all."""
        if server_id is None:
            self._server_cache.clear()
            self._search_cache.clear()
        else:
            self._server_cache.pop(server_id, None)

    async def search(self, query: str, limit: int) -> list:
        cache_key = (query, limit)
        now = time.monotonic()
        if cache_key in self._search_cache:
            cached, expires = self._search_cache[cache_key]
            if now < expires:
                return cached

        tasks = [reg.search(query, limit) for reg in self._registries]
        all_results = await asyncio.gather(*tasks, return_exceptions=True)
        seen: set[str] = set()
        candidates: list[ServerInfo] = []
        for batch in all_results:
            if isinstance(batch, Exception):
                continue
            for srv in batch:
                k = _dedup_key(srv.name)
                if k and k not in seen:
                    seen.add(k)
                    candidates.append(srv)
        candidates.sort(key=lambda s: _relevance_score(s, query), reverse=True)
        result = candidates[:limit]
        self._search_cache[cache_key] = (result, now + _CACHE_TTL_SEARCH)
        return result

    async def get_server(self, id: str):
        now = time.monotonic()
        if id in self._server_cache:
            cached, expires = self._server_cache[id]
            if now < expires:
                return cached

        results = await asyncio.gather(
            *[reg.get_server(id) for reg in self._registries],
            return_exceptions=True,
        )
        result = next((r for r in results if r and not isinstance(r, Exception)), None)
        self._server_cache[id] = (result, now + _CACHE_TTL_SERVER)
        return result


_SOURCE_TIER: dict[str, int] = {
    "official": 0,
    "smithery": 1,
    "npm": 2,
    "github": 3,
    "pypi": 4,
}

_STRIP_PREFIXES = re.compile(
    r'^(?:@[^/]+/)?(?:mcp-server-|server-mcp-|mcp-|server-)?', re.IGNORECASE
)


def _dedup_key(name: str) -> str:
    """Normalize a server name for cross-registry deduplication."""
    core = _STRIP_PREFIXES.sub("", name.lower())
    return re.sub(r'[^a-z0-9]', '', core)


def _relevance_score(srv: ServerInfo, query: str) -> float:
    """Higher is better. Combines name/description match quality with source tier."""
    words = re.split(r'\W+', query.lower())
    name_lc = srv.name.lower()
    id_lc = srv.id.lower()
    desc_lc = srv.description.lower()

    score = 0.0

    # Exact id or name match
    if query.lower() in (name_lc, id_lc):
        score += 100.0

    # All query words appear in name
    if all(w in name_lc for w in words if w):
        score += 50.0
    elif any(w in name_lc for w in words if w):
        score += 20.0

    # Query as substring in name
    if query.lower() in name_lc:
        score += 10.0

    # Words in description
    if all(w in desc_lc for w in words if w):
        score += 5.0
    elif any(w in desc_lc for w in words if w):
        score += 2.0

    # Source tier tiebreaker (lower tier = higher score)
    score -= _SOURCE_TIER.get(srv.source, 5) * 0.1

    return score


_registry = MultiRegistry()
