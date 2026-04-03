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


_CACHE_TTL_SERVER = 300.0   # 5 minutes — server metadata rarely changes
_CACHE_TTL_SEARCH = 60.0    # 1 minute — search results can shift


class MultiRegistry(BaseRegistry):
    """Fan out to all registries, dedup by name, Official → Smithery → npm priority."""

    def __init__(self):
        from chameleon_mcp.official_registry import OfficialMCPRegistry
        self._registries = [OfficialMCPRegistry(), SmitheryRegistry(), NpmRegistry()]
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
        seen = set()
        official_results, smithery_results, npm_results = [], [], []
        for batch in all_results:
            if isinstance(batch, Exception):
                continue
            for srv in batch:
                k = re.sub(r'[^a-z0-9]', '', srv.name.lower())
                if k not in seen:
                    seen.add(k)
                    if srv.source == "official":
                        official_results.append(srv)
                    elif srv.source == "smithery":
                        smithery_results.append(srv)
                    else:
                        npm_results.append(srv)
        result = (official_results + smithery_results + npm_results)[:limit]
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


_registry = MultiRegistry()
