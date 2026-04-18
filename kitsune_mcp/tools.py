import asyncio
import contextlib
import dataclasses
import inspect as _inspect
import ipaddress
import json
import os
import re
import shlex
import time
from datetime import datetime
from urllib.parse import urlparse

import httpx
from mcp.server.fastmcp import Context

from kitsune_mcp.app import mcp
from kitsune_mcp.constants import (
    MAX_INSPECT_DESC,
    MAX_RESOURCE_DOCS,
    MAX_RESPONSE_TOKENS,
    RESOURCE_PRIORITY_KEYWORDS,
    TIMEOUT_FETCH_URL,
    TIMEOUT_PROMPT_LIST,
    TIMEOUT_RESOURCE_LIST,
    TIMEOUT_RESOURCE_READ,
    TIMEOUT_STDIO_INIT,
    TIMEOUT_STDIO_TOOL,
    TRUST_HIGH,
    TRUST_LOW,
    TRUST_MEDIUM,
)
from kitsune_mcp.credentials import (
    _credentials_guide,
    _credentials_inspect_block,
    _credentials_ready,
    _registry_headers,
    _resolve_config,
    _save_to_env,
    _smithery_available,
    _to_env_var,
)
from kitsune_mcp.probe import _doc_uri_priority, _format_setup_guide, _probe_requirements
from kitsune_mcp.registry import (
    REGISTRY_BASE,
    NpmRegistry,
    PyPIRegistry,
    SmitheryRegistry,
    _registry,
)
from kitsune_mcp.session import _save_skills, session
from kitsune_mcp.shapeshift import (
    _do_shed,
    _json_type_to_py,
    _register_proxy_prompts,
    _register_proxy_resources,
    _register_proxy_tools,
)
from kitsune_mcp.transport import (
    BaseTransport,
    DockerTransport,
    HTTPSSETransport,
    PersistentStdioTransport,
    WebSocketTransport,
    _ping,
    _process_pool,
)
from kitsune_mcp.utils import (
    _estimate_tokens,
    _get_http_client,
    _rss_mb,
    _strip_html,
    _truncate,
    _try_axonmcp,
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _track_call(server_id: str, tool_name: str) -> None:
    """Increment call counter for a server and remember the last tool used."""
    prior = session["grown"].get(server_id, {"calls": 0})
    session["grown"][server_id] = {
        "last_tool": tool_name,
        "calls": prior["calls"] + 1,
        "status": "active",
    }


def _get_transport(server_id: str, srv) -> "BaseTransport":
    """Select the right transport for a server_id + optional ServerInfo."""
    if server_id.startswith("docker:"):
        return DockerTransport(server_id[len("docker:"):])
    if server_id.startswith(("ws://", "wss://")):
        return WebSocketTransport(server_id)
    if srv is not None and getattr(srv, "transport", None) == "websocket":
        return WebSocketTransport(srv.url)
    if srv is not None and getattr(srv, "transport", None) == "stdio":
        cmd = srv.install_cmd or ["npx", "-y", server_id]
        return PersistentStdioTransport(cmd)
    if srv is not None and getattr(srv, "transport", None) == "http":
        # srv.url is now the deploymentUrl (e.g. "https://brave.run.tools")
        return HTTPSSETransport(srv.id, deployment_url=srv.url)
    return HTTPSSETransport(server_id)


def _extract_tool_schema(tool: dict) -> tuple[dict, set]:
    """Return (properties, required_set) from a tool's inputSchema."""
    schema = tool.get("inputSchema") or {}
    return schema.get("properties") or {}, set(schema.get("required") or [])


async def _fetch_resource_docs(transport: "BaseTransport") -> str:
    """Fetch high-priority resource docs from a transport (best-effort)."""
    try:
        resources = await asyncio.wait_for(
            transport.list_resources(), timeout=TIMEOUT_RESOURCE_LIST
        )
        all_uris = [r["uri"] for r in resources]
        doc_uris = sorted(
            (u for u in all_uris if _doc_uri_priority(u) < len(RESOURCE_PRIORITY_KEYWORDS)),
            key=_doc_uri_priority,
        )[:MAX_RESOURCE_DOCS]
        parts = await asyncio.gather(
            *[asyncio.wait_for(transport.read_resource(u), timeout=TIMEOUT_RESOURCE_READ) for u in doc_uris],
            return_exceptions=True,
        )
        return "\n".join(p for p in parts if isinstance(p, str))
    except Exception:
        return ""


# Base tool names — used for collision detection in shapeshift()
_BASE_TOOL_NAMES = {
    "search", "inspect", "call", "run", "fetch",
    "skill", "key", "auto", "status", "shapeshift", "shiftback", "craft",
    "connect", "release", "test", "bench", "setup",
}


@mcp.tool()
async def search(query: str, registry: str = "all", limit: int = 5) -> str:
    """Search MCP servers. registry: all|official|mcpregistry|glama|npm|smithery|pypi"""
    if registry == "smithery":
        reg = SmitheryRegistry()
    elif registry == "npm":
        reg = NpmRegistry()
    elif registry == "pypi":
        reg = PyPIRegistry()
    elif registry in ("official", "mcpregistry", "glama"):
        from kitsune_mcp.official_registry import OfficialMCPRegistry
        from kitsune_mcp.registry import GlamaRegistry, McpRegistryIO
        reg = {"official": OfficialMCPRegistry(), "mcpregistry": McpRegistryIO(), "glama": GlamaRegistry()}[registry]
    else:
        reg = _registry

    servers = await reg.search(query, limit)
    if not servers:
        return f"No servers found for '{query}'. Try a different query or registry."

    lines = [f"SERVERS — '{query}' ({len(servers)} found)\n"]
    # Report any registry failures when searching all registries
    if registry == "all":
        errors = getattr(_registry, "last_registry_errors", {})
        if errors:
            failed = ", ".join(f"{n} (timeout)" for n in errors)
            lines.insert(1, f"⚠️  Skipped: {failed}\n")
    for s in servers:
        cred_status = _credentials_ready(s.credentials)
        lines.append(f"{s.id} | {s.name} — {s.description} | {s.source}/{s.transport} | {cred_status}")
        session["explored"][s.id] = {"name": s.name, "desc": s.description, "status": "explored"}

    lines.append("\ninspect('<id>') for details | shapeshift('<id>') to load")
    return "\n".join(lines)


@mcp.tool()
async def inspect(server_id: str) -> str:
    """Show server tools, schemas, and required credentials."""
    srv = await _registry.get_server(server_id)
    if srv is None:
        return f"Server '{server_id}' not found. Use search() to find servers."

    lines = [
        f"{srv.name} ({srv.id})",
        f"Source: {srv.source} | Transport: {srv.transport}",
        f"Description: {srv.description[:200]}",
        "",
    ]

    resolved_creds, _ = _resolve_config(srv.credentials, {})
    lines += _credentials_inspect_block(srv.credentials, resolved_creds)

    if srv.transport == "stdio":
        cmd_str = " ".join(srv.install_cmd) if srv.install_cmd else f"npx -y {srv.id}"
        lines += [f"RUN: {cmd_str}", ""]

    # For stdio: prefer live tool schemas over (potentially stale) registry data
    tools = srv.tools or []
    live_source = False
    if srv.transport == "stdio":
        cmd = srv.install_cmd or ["npx", "-y", srv.id]
        try:
            live_tools = await asyncio.wait_for(
                PersistentStdioTransport(cmd).list_tools(), timeout=TIMEOUT_STDIO_INIT
            )
            if live_tools:
                tools = live_tools
                live_source = True
        except Exception:
            pass

    if tools:
        label = "TOOLS (live)" if live_source else "TOOLS"
        lines.append(f"{label} ({len(tools)})")
        for t in tools:
            tname = t.get("name", "?")
            tdesc = (t.get("description") or "")[:MAX_INSPECT_DESC]
            params = list((t.get("inputSchema") or {}).get("properties", {}).keys())
            pstr = f"({', '.join(params)})" if params else ""
            lines.append(f"  {tname}{pstr} — {tdesc}")
        # Prefer measured cost from actual schemas over registry estimate
        token_cost = _estimate_tokens(tools)
        lines.append(f"\nToken cost: ~{token_cost} tokens (measured)")
    else:
        lines.append("TOOLS: not listed in registry (run locally to measure)")
        token_cost = srv.token_cost or 0

    session["explored"][srv.id] = {
        "name": srv.name, "desc": srv.description,
        "status": "inspected", "token_cost": token_cost,
    }

    # Suggest next action based on credential state
    _, missing_creds = _resolve_config(srv.credentials, {})
    if missing_creds:
        first_var = _to_env_var(next(iter(missing_creds)))
        lines.append(f"\nNext: key(\"{first_var}\", \"...\") then shapeshift(\"{srv.id}\")")
    else:
        lean_hint = f", tools=[\"{tools[0].get('name', '')}\"]" if tools and len(tools) > 4 else ""
        lines.append(f"\nNext: shapeshift(\"{srv.id}\"{lean_hint})")

    return "\n".join(lines)


@mcp.tool()
async def call(
    tool_name: str,
    server_id: str | None = None,
    arguments: dict | None = None,
    config: dict | None = None,
) -> str:
    """Call a tool on an MCP server. server_id optional when shapeshifted — current form used.
    After shapeshift(): call('list_directory', arguments={'path': '/tmp'})
    Direct:             call('list_directory', '@some-server', {'path': '/tmp'})"""
    if server_id is None:
        server_id = session.get("current_form")
        if not server_id:
            return "Provide a server_id, or use shapeshift() first to set a current form."
    if arguments is None:
        arguments = {}
    if config is None:
        config = {}
    srv = await _registry.get_server(server_id)
    credentials = srv.credentials if srv else {}

    resolved_config, missing = _resolve_config(credentials, config)
    if missing:
        return _credentials_guide(server_id, credentials, resolved_config)

    transport: BaseTransport = _get_transport(server_id, srv)
    result = await transport.execute(tool_name, arguments, resolved_config)

    _track_call(server_id, tool_name)

    if srv is not None:
        source = srv.source
        if source not in TRUST_HIGH | TRUST_MEDIUM:
            result = result + f"\n[source: {source}]"
    return result


@mcp.tool()
async def run(
    package: str,
    tool_name: str,
    arguments: dict | None = None,
) -> str:
    """Run a tool from npm/pip. package: 'pkg-name' (npx) or 'uvx:pkg-name' (Python)."""
    if arguments is None:
        arguments = {}
    cmd = ["uvx", package[4:]] if package.startswith("uvx:") else ["npx", "-y", package]

    transport = PersistentStdioTransport(cmd)
    result = await transport.execute(tool_name, arguments, {})

    _track_call(package, tool_name)
    return result


@mcp.tool()
async def fetch(url: str, intent: str = "") -> str:
    """Fetch a URL and return compressed content (~500 tokens vs ~25K raw HTML)."""
    raw_estimate = 6000  # typical webpage token count before compression

    axon_result = await _try_axonmcp(url, intent)
    if axon_result:
        saved = max(0, raw_estimate - _estimate_tokens(axon_result))
        session["stats"]["tokens_saved_browse"] += saved
        return axon_result

    # Fallback: httpx + HTML stripping
    try:
        r = await _get_http_client().get(
            url, timeout=TIMEOUT_FETCH_URL, headers={"User-Agent": "Mozilla/5.0"}
        )
        r.raise_for_status()
        text = r.text
    except Exception as e:
        return f"Failed to fetch {url}: {e}"

    stripped = _strip_html(text)
    result = _truncate(stripped, max_tokens=MAX_RESPONSE_TOKENS)
    saved = max(0, raw_estimate - _estimate_tokens(result))
    session["stats"]["tokens_saved_browse"] += saved

    header = f"[{url}]" + (f" — intent: {intent}" if intent else "")
    return f"{header}\n\n{result}"


def _is_safe_url(url: str) -> bool:
    """Return True only for public HTTPS URLs — blocks SSRF to private/loopback addresses."""
    try:
        p = urlparse(url)
        if p.scheme != "https":
            return False
        host = p.hostname or ""
        if not host or host == "localhost":
            return False
        try:
            addr = ipaddress.ip_address(host)
            return addr.is_global
        except ValueError:
            pass  # hostname, not a bare IP — allow it
        return True
    except Exception:
        return False


@mcp.tool()
async def skill(qualified_name: str, forget: bool = False) -> str:
    """Load a Smithery skill into context. forget=True removes it."""
    # --- forget / uninstall ---
    if forget:
        if qualified_name in session["skills"]:
            name = session["skills"][qualified_name].get("name", qualified_name)
            del session["skills"][qualified_name]
            _save_skills()
            return f"Skill removed: {name} ({qualified_name})"
        return f"Skill '{qualified_name}' is not installed."

    # --- serve from cache if already loaded ---
    cached = session["skills"].get(qualified_name)
    if cached and cached.get("content"):
        content = cached["content"]
        skill_name = cached.get("name", qualified_name)
        token_estimate = cached.get("tokens", len(content) // 4)
        lines = [
            f"Skill injected (cached): {skill_name} ({qualified_name})",
            f"Context cost: ~{token_estimate:,} tokens",
            "", "--- SKILL CONTENT ---", "", content,
        ]
        return "\n".join(lines)

    # --- fetch from Smithery API ---
    if not _smithery_available():
        return "No SMITHERY_API_KEY set. Run: key('SMITHERY_API_KEY', 'your-key')"

    try:
        r = await _get_http_client().get(
            f"{REGISTRY_BASE}/skills/{qualified_name}",
            headers=_registry_headers(),
            timeout=TIMEOUT_FETCH_URL,
        )
        r.raise_for_status()
        skill_meta = r.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return f"Skill '{qualified_name}' not found."
        return f"Registry error: {e.response.status_code}"
    except Exception as e:
        return f"Failed to fetch skill: {e}"

    skill_name = skill_meta.get("name") or skill_meta.get("displayName") or qualified_name
    skill_desc = (skill_meta.get("description") or "").strip()

    content = None
    content_url = (skill_meta.get("contentUrl") or skill_meta.get("url")
                   or skill_meta.get("content_url"))
    if content_url and _is_safe_url(content_url):
        try:
            rc = await _get_http_client().get(content_url, timeout=TIMEOUT_FETCH_URL)
            rc.raise_for_status()
            content = rc.text
        except Exception:
            content = None

    if not content:
        content = (skill_meta.get("content") or skill_meta.get("markdown")
                   or skill_meta.get("text"))

    if not content:
        return "\n".join([
            f"Skill: {skill_name} ({qualified_name})",
            f"Description: {skill_desc}" if skill_desc else "",
            "Warning: could not fetch skill content.",
            json.dumps(skill_meta, indent=2),
        ])

    token_estimate = len(content) // 4
    session["skills"][qualified_name] = {
        "name": skill_name,
        "content": content,
        "tokens": token_estimate,
        "installed_at": datetime.utcnow().isoformat(),
    }
    _save_skills()

    lines = [
        f"Skill injected: {skill_name} ({qualified_name})",
        f"Context cost: ~{token_estimate:,} tokens",
    ]
    if skill_desc:
        lines.append(f"Description: {skill_desc}")
    lines += ["", "--- SKILL CONTENT ---", "", content]
    return "\n".join(lines)


@mcp.tool()
async def key(env_var: str, value: str) -> str:
    """Save an API key to .env for persistent use. e.g. key('EXA_API_KEY', 'sk-...')"""
    var = env_var.upper().replace(" ", "_")
    _save_to_env(var, value)
    _registry.bust_cache()  # credentials changed — invalidate cached server records
    return f"Saved: {var} written to .env and active for this session."


@mcp.tool()
async def auto(
    task: str,
    tool_name: str = "",
    arguments: dict | None = None,
    server_hint: str = "",
    keys: dict | None = None,
) -> str:
    """Search → pick best server → call tool in one step."""
    if arguments is None:
        arguments = {}
    if keys is None:
        keys = {}
    for env_var, value in keys.items():
        _save_to_env(env_var.upper(), str(value))

    if server_hint:
        srv = await _registry.get_server(server_hint)
        if srv:
            server_id, server_name, credentials = srv.id, srv.name, srv.credentials
        else:
            server_id, server_name, credentials = server_hint, server_hint, {}
    else:
        servers = await _registry.search(task, limit=3)
        if not servers:
            return f"No servers found for '{task}'. Use search() or provide server_hint."
        best = servers[0]
        server_id, server_name, credentials = best.id, best.name, best.credentials
        session["explored"][server_id] = {
            "name": server_name, "desc": best.description, "status": "harvested"
        }

    resolved_config, missing = _resolve_config(credentials, {})
    if missing:
        missing_vars = {_to_env_var(k): v for k, v in missing.items()}
        lines = [f"Server '{server_id}' needs keys:", ""]
        for ev, desc in missing_vars.items():
            lines.append(f"  {ev}" + (f": {desc[:60]}" if desc else ""))
        args_repr = json.dumps(arguments) if arguments else "{}"
        lines += [
            "",
            "Retry:",
            f'  auto("{task}", "{tool_name}", {args_repr},',
            f'    server_hint="{server_id}",',
            '    keys={' + ", ".join(f'"{k}": "val"' for k in missing_vars) + '})',
        ]
        return "\n".join(lines)

    if not tool_name:
        srv = await _registry.get_server(server_id)
        tools = (srv.tools if srv else []) or []

        # For stdio servers with no registry tools, fetch live schemas
        if not tools and srv and srv.transport == "stdio":
            cmd = srv.install_cmd or ["npx", "-y", server_id]
            with contextlib.suppress(Exception):
                tools = await asyncio.wait_for(
                    PersistentStdioTransport(cmd).list_tools(), timeout=TIMEOUT_STDIO_INIT
                )

        if not tools:
            return f"{server_id} ready (no tools listed). Use call() to call tools directly."

        # Auto-select: only one tool → use it; multiple → pick best match for task
        if len(tools) == 1:
            tool_name = tools[0]["name"]
        else:
            task_lc = task.lower()
            task_words = set(re.split(r'\W+', task_lc))

            def _tool_score(t: dict) -> float:
                n = (t.get("name") or "").lower()
                d = (t.get("description") or "").lower()
                score = 0.0
                if task_lc in n:
                    score += 10.0
                score += sum(2.0 for w in task_words if w and w in n)
                score += sum(1.0 for w in task_words if w and w in d)
                return score

            scored = sorted(tools, key=_tool_score, reverse=True)
            best_score = _tool_score(scored[0])
            if best_score > 0:
                tool_name = scored[0]["name"]
            else:
                # No match — list tools and ask user to pick
                tool_lines = [f"  {t['name']} — {(t.get('description') or '')[:80]}" for t in tools]
                return "\n".join([
                    f"{server_name} ({server_id}) ready. Available tools:",
                    "",
                    *tool_lines,
                    "",
                    f'Call: auto("{task}", "<tool>", args, server_hint="{server_id}")',
                ])

    srv = await _registry.get_server(server_id)
    transport: BaseTransport = _get_transport(server_id, srv)
    result = await transport.execute(tool_name, arguments, resolved_config)

    _track_call(server_id, tool_name)
    return result


def _infer_install_cmd(server_id: str) -> list[str]:
    """npm-style (@scope/pkg, has /, no dots) → npx -y; Python-style (has dots) → uvx."""
    if server_id.startswith("@") or "/" in server_id or "." not in server_id:
        return ["npx", "-y", server_id]
    return ["uvx", server_id]


def _local_uninstall_cmd(install_cmd: list[str]) -> list[str] | None:
    """uvx pkg → uv tool uninstall pkg. npx → None (cache is ephemeral)."""
    if install_cmd and install_cmd[0] == "uvx" and len(install_cmd) >= 2:
        return ["uv", "tool", "uninstall", install_cmd[-1]]
    return None


async def _commit_shapeshift(
    server_id: str,
    transport: BaseTransport,
    tool_schemas: list,
    resolved_config: dict,
    tools: list[str] | None,
    ctx: Context,
    pool_key: str | None,
    trust_note: str,
    lean_eligible: bool = False,
) -> str:
    """Register tools/resources/prompts, update session, notify client, return output string.

    Called by both the pool-connection path and the registry path of shapeshift() so
    neither path has to duplicate the ~70-line registration + output block.
    """
    only = set(tools) if tools else None
    registered = _register_proxy_tools(server_id, tool_schemas, transport, resolved_config, _BASE_TOOL_NAMES, only)
    if not registered:
        return f"No tools could be shapeshifted from '{server_id}'."

    shapeshift_resources: list[str] = []
    shapeshift_prompts: list[str] = []
    if hasattr(transport, "list_resources"):
        with contextlib.suppress(Exception):
            raw_res = await asyncio.wait_for(transport.list_resources(), timeout=TIMEOUT_RESOURCE_LIST)
            shapeshift_resources = _register_proxy_resources(transport, raw_res)
    if hasattr(transport, "list_prompts"):
        with contextlib.suppress(Exception):
            raw_prompts = await asyncio.wait_for(transport.list_prompts(), timeout=TIMEOUT_PROMPT_LIST)
            shapeshift_prompts = _register_proxy_prompts(transport, raw_prompts)

    session["shapeshift_tools"] = registered
    session["shapeshift_resources"] = shapeshift_resources
    session["shapeshift_prompts"] = shapeshift_prompts
    session["current_form"] = server_id
    session["current_form_pool_key"] = pool_key

    with contextlib.suppress(Exception):
        await ctx.session.send_tool_list_changed()
    if shapeshift_resources:
        with contextlib.suppress(Exception):
            await ctx.session.send_resource_list_changed()
    if shapeshift_prompts:
        with contextlib.suppress(Exception):
            await ctx.session.send_prompt_list_changed()

    missing_env: list[str] = []
    with contextlib.suppress(Exception):
        missing_env = _probe_requirements(tool_schemas, "").get("missing_env", [])

    lean = f" (lean: {', '.join(tools)})" if tools else ""
    extras = []
    if shapeshift_resources:
        extras.append(f"{len(shapeshift_resources)} resource(s)")
    if shapeshift_prompts:
        extras.append(f"{len(shapeshift_prompts)} prompt(s)")
    extra_note = f" + {', '.join(extras)}" if extras else ""

    lines = [
        f"Shapeshifted into '{server_id}'{lean} — {len(registered)} tool(s){extra_note} registered:",
        *[f"  {t}" for t in registered],
    ]
    if shapeshift_resources:
        shown = ", ".join(shapeshift_resources[:3]) + (" ..." if len(shapeshift_resources) > 3 else "")
        lines.append(f"Resources ({len(shapeshift_resources)}): {shown}")
    if shapeshift_prompts:
        shown = ", ".join(shapeshift_prompts[:3]) + (" ..." if len(shapeshift_prompts) > 3 else "")
        lines.append(f"Prompts ({len(shapeshift_prompts)}): {shown}")
    lines += ["", "In this session: call('tool_name', arguments={...})"]
    lines.append(trust_note)
    if missing_env:
        lines.append("\n⚠️  Credentials may be required — add to .env:")
        for var in missing_env:
            lines.append(f"  {var}=your-value")
        lines.append(f'  Or: key("{missing_env[0]}", "your-value")')
    if lean_eligible and not tools and len(registered) > 4:
        tool_cost = _estimate_tokens(tool_schemas)
        lines.append(
            f"\n💡 {len(registered)} tools loaded (~{tool_cost:,} tokens). "
            f"For lean mounting: shapeshift(\"{server_id}\", tools=[\"{registered[0]}\"])"
        )
    return "\n".join(lines)


@mcp.tool()
async def shapeshift(
    server_id: str,
    ctx: Context,
    tools: list[str] | None = None,
    confirm: bool = False,
    source: str = "auto",
) -> str:
    """Shapeshift into a server's form. The fox takes on the server's shape — its tools become available natively in the session.

    source: "auto" (default) | "local" (force npx/uvx install) | "smithery" (force HTTP via Smithery) | "official" (official/mcpregistry only)
    tools: load only specific tools instead of everything
    confirm: proceed with community (npm/pypi/github) sources after reviewing
    """
    # Pool connections (from connect()) take priority — user already vetted these, bypass trust gates
    for _pk, conn in session["connections"].items():
        if conn.get("name") == server_id or conn.get("command") == server_id:
            cmd = conn["command"].split()
            tool_names = conn.get("tools", [])
            _do_shed()
            session["current_form_local_install"] = None

            transport: BaseTransport = PersistentStdioTransport(cmd)
            raw_tools = await transport.list_tools()
            if not raw_tools and tool_names:
                raw_tools = [{"name": n, "description": "", "inputSchema": {}} for n in tool_names]

            return await _commit_shapeshift(
                server_id, transport, raw_tools, {}, tools, ctx,
                json.dumps(cmd, sort_keys=True),
                "\n⚠️  Source: pool connection (local — verify command before use)",
            )

    # Registry path — source controls which registries/transports are preferred
    if source == "smithery" and not _smithery_available():
        return (
            f"Cannot use source='smithery' — SMITHERY_API_KEY is not set.\n\n"
            f"Set it: key(\"SMITHERY_API_KEY\", \"your-key\")\n"
            f"Or use: shapeshift(\"{server_id}\", source=\"local\") to install locally."
        )

    reg_source = source if source in ("smithery", "official") else None
    srv = await _registry.get_server(server_id, source_preference=reg_source)
    if srv is None:
        return f"Server '{server_id}' not found. Use search() to find servers, or connect() for local servers."

    srv_source = srv.source

    # Check source constraint first — clearer error than the trust gate when source="official" resolves non-official
    if source == "official" and srv_source not in ("official", "mcpregistry"):
        return (
            f"No official/verified listing found for '{server_id}' (resolved source: {srv_source}).\n"
            f"Try: shapeshift(\"{server_id}\") for auto, or shapeshift(\"{server_id}\", source=\"local\")."
        )

    trust_level = (os.getenv("KITSUNE_TRUST") or "").lower()
    _trust_override = trust_level in ("community", "all", "low")

    if srv_source in TRUST_LOW and not confirm and not _trust_override:
        return (
            f"⚠️  '{server_id}' is from {srv_source} (community — not verified by the official MCP registry).\n\n"
            f"Review before trusting:\n"
            f"  inspect('{server_id}')  — see tools and credentials\n\n"
            f"To proceed: shapeshift('{server_id}', confirm=True)\n"
            f"To always trust community: key(\"KITSUNE_TRUST\", \"community\")"
        )

    if source == "local" and not confirm and not _trust_override:
        install_cmd = srv.install_cmd or _infer_install_cmd(server_id)
        return (
            f"⚠️  source='local' will run: {' '.join(install_cmd)}\n\n"
            f"This downloads and executes the package locally.\n"
            f"Review first: inspect('{server_id}')\n\n"
            f"To proceed: shapeshift('{server_id}', source='local', confirm=True)\n"
            f"To always trust local installs: key(\"KITSUNE_TRUST\", \"community\")"
        )

    # All gates passed — resolve credentials before dropping current form
    resolved_config, missing = _resolve_config(srv.credentials, {})
    if missing:
        creds_msg = _credentials_guide(server_id, srv.credentials, resolved_config)
        return f"Cannot shapeshift into '{server_id}' — missing credentials:\n\n{creds_msg}"

    _do_shed()
    session["current_form_local_install"] = None  # overwritten below for source="local"

    if source == "local":
        install_cmd = srv.install_cmd or _infer_install_cmd(server_id)
        srv = dataclasses.replace(srv, transport="stdio", install_cmd=install_cmd)
        session["current_form_local_install"] = {"cmd": srv.install_cmd, "package": server_id}

    if srv.transport == "stdio":
        cmd = srv.install_cmd or ["npx", "-y", server_id]
        # PersistentStdioTransport keeps the process alive for subsequent tool calls
        transport = PersistentStdioTransport(cmd)
        pool_key: str | None = json.dumps(cmd, sort_keys=True)
        tool_schemas = srv.tools or []
        if not tool_schemas:
            with contextlib.suppress(Exception):
                tool_schemas = await transport.list_tools()
    else:
        transport = _get_transport(server_id, srv)
        pool_key = None
        tool_schemas = srv.tools or []
        if not tool_schemas and hasattr(transport, "list_tools"):
            tool_schemas = await transport.list_tools(resolved_config)

    if not tool_schemas:
        return f"No tools found for '{server_id}'. Try inspect() first."

    transport_label = " via local npx/uvx" if srv.transport == "stdio" else ""
    if srv_source in TRUST_HIGH | TRUST_MEDIUM:
        trust_note = f"\n✓  Source: {srv_source}{transport_label}"
    else:
        trust_note = f"\n⚠️  Source: {srv_source}{transport_label} (community — not verified by official MCP registry)"

    return await _commit_shapeshift(
        server_id, transport, tool_schemas, resolved_config, tools, ctx,
        pool_key, trust_note, lean_eligible=True,
    )


@mcp.tool()
async def shiftback(ctx: Context, kill: bool = False, uninstall: bool = False) -> str:
    """Shift back to Kitsune's true form. Removes all shapeshifted tools.

    kill=True      also terminate the underlying server process
    uninstall=True also uninstall the locally installed package (implies kill=True;
                   only applies when shapeshifted via source='local')
    """
    has_tools = bool(session["shapeshift_tools"])
    has_resources = bool(session.get("shapeshift_resources"))
    has_prompts = bool(session.get("shapeshift_prompts"))
    if not has_tools and not has_resources and not has_prompts:
        return "Already in base form."

    form = session["current_form"]
    local_install = session.pop("current_form_local_install", None)
    # Snapshot counts before _do_shed() clears the lists
    n_res = len(session.get("shapeshift_resources", []))
    n_prompts = len(session.get("shapeshift_prompts", []))
    removed = _do_shed()

    with contextlib.suppress(Exception):
        await ctx.session.send_tool_list_changed()
    if n_res:
        with contextlib.suppress(Exception):
            await ctx.session.send_resource_list_changed()
    if n_prompts:
        with contextlib.suppress(Exception):
            await ctx.session.send_prompt_list_changed()

    extras = []
    if n_res:
        extras.append(f"{n_res} resource(s)")
    if n_prompts:
        extras.append(f"{n_prompts} prompt(s)")
    extra_note = f", {', '.join(extras)}" if extras else ""

    result_lines = [f"Shifted back from '{form}'. Removed: {', '.join(removed)}{extra_note}"]

    if (kill or uninstall) and form:
        # Use the exact pool key stored at shapeshift() time — no fragile string matching needed
        exact_key = session.pop("current_form_pool_key", None)
        killed = []
        keys_to_check = [exact_key] if exact_key else list(_process_pool.keys())
        for pool_key in keys_to_check:
            entry = _process_pool.get(pool_key)
            if entry is None:
                continue
            with contextlib.suppress(Exception):
                entry.proc.kill()
                await asyncio.wait_for(entry.proc.wait(), timeout=TIMEOUT_RESOURCE_LIST)
            _process_pool.pop(pool_key, None)
            killed.append(entry.name or entry.install_cmd[0])
        if killed:
            result_lines.append(f"Released: {', '.join(killed)}")

    if uninstall and local_install:
        uninstall_cmd = _local_uninstall_cmd(local_install["cmd"])
        pkg = local_install["package"]
        if uninstall_cmd:
            try:
                proc = await asyncio.create_subprocess_exec(
                    *uninstall_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
                if proc.returncode == 0:
                    result_lines.append(f"Uninstalled: {pkg}")
                else:
                    err = stderr.decode().strip()[:120]
                    result_lines.append(f"Uninstall failed ({pkg}): {err}")
            except Exception as e:
                result_lines.append(f"Uninstall error ({pkg}): {e}")
        else:
            # npx packages are cached, not permanently installed — no action needed
            result_lines.append(f"Note: '{pkg}' was run via npx (cached, not permanently installed — cache expires automatically)")
    elif local_install and not uninstall:
        pkg = local_install["package"]
        result_lines.append(f"Local package '{pkg}' is still cached. To remove: shiftback(uninstall=True)")

    return "\n".join(result_lines)


@mcp.tool()
async def craft(
    ctx: Context,
    name: str,
    description: str,
    params: dict,
    url: str,
    method: str = "POST",
    headers: dict | None = None,
) -> str:
    """Register a custom tool backed by your HTTP endpoint — live immediately. POST=JSON body, GET=query params. shiftback() removes it."""
    if not name or not name.replace("_", "").isalnum():
        return "name must be alphanumeric (underscores allowed)."
    if not url.startswith(("http://", "https://")):
        return "url must start with http:// or https://"

    _url = url
    _method = method.upper()
    _headers = headers or {}

    # Build Python parameters from JSON Schema properties
    py_params = []
    for pname, pschema in (params or {}).items():
        json_type = pschema.get("type", "string") if isinstance(pschema, dict) else "string"
        ptype = _json_type_to_py(json_type)
        py_params.append(_inspect.Parameter(
            pname, _inspect.Parameter.KEYWORD_ONLY,
            default=_inspect.Parameter.empty, annotation=ptype,
        ))

    async def _endpoint_proxy(**kwargs) -> str:
        try:
            client = _get_http_client()
            if _method == "GET":
                r = await client.get(_url, params=kwargs, headers=_headers, timeout=30.0)
            else:
                r = await client.request(_method, _url, json=kwargs, headers=_headers, timeout=30.0)
            r.raise_for_status()
            return r.text
        except httpx.HTTPStatusError as e:
            return f"HTTP {e.response.status_code} from {_url}: {e.response.text[:200]}"
        except Exception as e:
            return f"Error calling {_url}: {e}"

    _endpoint_proxy.__name__ = name
    _endpoint_proxy.__doc__ = description[:120]
    _endpoint_proxy.__signature__ = _inspect.Signature(py_params, return_annotation=str)

    # Remove previous registration if re-crafting the same name
    if name in session["crafted_tools"]:
        with contextlib.suppress(Exception):
            mcp.remove_tool(name)
        session["shapeshift_tools"] = [t for t in session["shapeshift_tools"] if t != name]

    try:
        mcp.add_tool(_endpoint_proxy)
    except Exception as e:
        return f"Failed to register tool '{name}': {e}"

    session["crafted_tools"][name] = {
        "url": url, "method": _method, "description": description, "params": params or {},
    }
    if name not in session["shapeshift_tools"]:
        session["shapeshift_tools"].append(name)

    with contextlib.suppress(Exception):
        await ctx.session.send_tool_list_changed()

    param_list = ", ".join(params.keys()) if params else "(none)"
    return (
        f"✓ Tool '{name}' registered — {_method} {url}\n"
        f"Params: {param_list}\n\n"
        f"Call it directly, or shiftback() to remove it."
    )


@mcp.tool()
async def connect(command: str, name: str = "", timeout: int = 60, inherit_stderr: bool = True) -> str:
    """Start a persistent server. command: server_id or shell cmd (e.g. 'uvx voice-mode'). name: alias for release()."""
    # Detect server_id vs shell command: if it has no spaces and doesn't start with a
    # known executor, try registry lookup first.
    _EXECUTORS = ("npx", "uvx", "node", "python", "python3", "uv", "deno", "docker")
    looks_like_cmd = " " in command or command.split()[0] in _EXECUTORS
    install_cmd: list[str] | None = None

    if not looks_like_cmd:
        srv = await _registry.get_server(command)
        if srv and srv.install_cmd:
            install_cmd = srv.install_cmd
            if not name:
                name = srv.name or command

    if install_cmd is None:
        install_cmd = shlex.split(command)
    pool_key = json.dumps(install_cmd, sort_keys=True)
    friendly = name or install_cmd[0]

    # Already connected?
    existing = _process_pool.get(pool_key)
    if existing is not None and existing.is_alive():
        uptime = int(existing.uptime_seconds())
        calls = existing.call_count
        label = existing.name or friendly
        return (
            f"Already connected: {label} (PID {existing.pid()}) | "
            f"uptime: {uptime}s | calls: {calls}"
        )

    transport = PersistentStdioTransport(install_cmd, inherit_stderr=inherit_stderr)
    try:
        entry = await asyncio.wait_for(transport._start_process(), timeout=timeout)
    except TimeoutError:
        return f"Timeout starting '{command}' after {timeout}s."
    except RuntimeError as e:
        return str(e)

    entry.name = friendly

    # Fetch tool list from live process
    tools = await transport.list_tools()
    tool_names = [t.get("name", "?") for t in tools]

    resource_text = await _fetch_resource_docs(transport)

    # Update session connections
    session["connections"][pool_key] = {
        "name": friendly,
        "command": command,
        "pid": entry.pid(),
        "started_at": entry.started_at,
        "tools": tool_names,
    }

    tool_summary = f"Tools ({len(tool_names)}): {', '.join(tool_names)}" if tool_names else "Tools: none listed"
    setup_guide = _format_setup_guide(_probe_requirements(tools, resource_text), friendly, tools=tools)

    # Trust / source note — resolve from registry if possible, otherwise flag as local
    _conn_srv = await _registry.get_server(command) if not looks_like_cmd else None
    conn_source = _conn_srv.source if _conn_srv else "local"
    if conn_source in TRUST_HIGH | TRUST_MEDIUM:
        trust_note = f"✓  Source: {conn_source}"
    else:
        trust_note = f"⚠️  Source: {conn_source} (verify command before connecting)"

    parts = [
        f"Connected: {friendly} (PID {entry.pid()})",
        tool_summary,
        f"Release with: release('{friendly}')",
    ]
    if setup_guide:
        parts.append(setup_guide)
        parts.append(f"\nCall setup('{friendly}') for step-by-step guidance.")
    parts.append(trust_note)
    return "\n".join(parts)


@mcp.tool()
async def release(name: str) -> str:
    """Kill a persistent connection by name."""
    # Find entry by name or pool_key
    found_key = None
    found_entry = None

    for pool_key, entry in _process_pool.items():
        if entry.name == name or pool_key == name:
            found_key = pool_key
            found_entry = entry
            break

    if found_key is None or found_entry is None:
        active = [e.name or k for k, e in _process_pool.items()]
        if active:
            return f"No connection named '{name}'. Active: {', '.join(active)}"
        return "No active connections. Use connect() to start one."

    uptime = int(found_entry.uptime_seconds())
    calls = found_entry.call_count
    pid = found_entry.pid()
    label = found_entry.name or found_key

    try:
        found_entry.proc.kill()
        await asyncio.wait_for(found_entry.proc.wait(), timeout=TIMEOUT_RESOURCE_LIST)
    except Exception:
        pass

    _process_pool.pop(found_key, None)
    session["connections"].pop(found_key, None)

    return f"Released: {label} (PID {pid}) | uptime: {uptime}s | calls: {calls}"


@mcp.tool()
async def test(server_id: str, level: str = "basic") -> str:
    """Quality-score a server 0–100. level: 'basic' (schema checks) or 'full' (live calls)."""
    score = 0
    checks = []

    # Check 1: Registry lookup (15 pts)
    srv = await _registry.get_server(server_id)
    if srv is not None:
        score += 15
        checks.append("✅ Registry lookup found server (+15)")
    else:
        checks.append("❌ Server not found in registry (0)")
        return f"Score: {score}/100 (Poor)\n\n" + "\n".join(checks) + "\nGrade: Poor — server not found."

    # Check 2: Known transport type (5 pts)
    if srv.transport in ("http", "stdio"):
        score += 5
        checks.append(f"✅ Transport type known: {srv.transport} (+5)")
    else:
        checks.append(f"❌ Unknown transport: {srv.transport!r} (0)")

    # Check 3: Has description (5 pts)
    if srv.description and len(srv.description) > 10:
        score += 5
        checks.append("✅ Has description (+5)")
    else:
        checks.append("❌ Missing or too-short description (0)")

    # Check 4: tools/list responds (15 pts)
    tools = srv.tools or []
    if not tools and srv.transport == "stdio":
        cmd = srv.install_cmd or ["npx", "-y", server_id]
        try:
            tools = await asyncio.wait_for(
                PersistentStdioTransport(cmd).list_tools(), timeout=TIMEOUT_STDIO_INIT
            )
        except TimeoutError:
            tools = []

    if tools:
        score += 15
        checks.append(f"✅ tools/list responded with {len(tools)} tools (+15)")
    else:
        checks.append("❌ tools/list returned no tools (0)")

    # Check 5: Tool schemas valid (10 pts)
    if tools:
        valid_schemas = sum(
            1 for t in tools
            if t.get("name") and t.get("inputSchema")
        )
        schema_score = min(10, int(10 * valid_schemas / len(tools)))
        score += schema_score
        checks.append(f"✅ Schema quality: {valid_schemas}/{len(tools)} tools valid (+{schema_score})")
    else:
        checks.append("⚠️  No tools to check schemas (0)")

    # Check 6: No collision with base tool names (10 pts)
    collisions = [t.get("name") for t in tools if t.get("name") in _BASE_TOOL_NAMES]
    if not collisions:
        score += 10
        checks.append("✅ No name collisions with Kitsune base tools (+10)")
    else:
        checks.append(f"⚠️  Name collisions: {', '.join(collisions)} (0) — will be prefixed on shapeshift()")

    # Check 7: Live tool calls (full mode only, 10 pts per tool, max 5 tools)
    if level == "full" and tools:
        checks.append("\n--- FULL MODE: live tool calls ---")
        call_score = 0
        resolved_config, _ = _resolve_config(srv.credentials, {})
        # Build one transport for the full-mode run — reuse pool entry across all tool calls
        transport_obj: BaseTransport = _get_transport(server_id, srv)
        for t in tools[:5]:
            tname = t.get("name", "")
            props, required = _extract_tool_schema(t)
            dummy_args = {
                pname: {"string": "test", "integer": 0, "boolean": False, "number": 0.0}.get(
                    pschema.get("type", "string"), "test"
                )
                for pname, pschema in props.items()
                if pname in required
            }

            try:
                result = await asyncio.wait_for(
                    transport_obj.execute(tname, dummy_args, resolved_config), timeout=TIMEOUT_STDIO_TOOL
                )
                if "error" not in result.lower() and "failed" not in result.lower()[:50]:
                    call_score += 10
                    checks.append(f"  ✅ {tname}() callable (+10)")
                else:
                    checks.append(f"  ⚠️  {tname}() returned error (0)")
            except Exception as e:
                checks.append(f"  ❌ {tname}() raised exception: {e!s:.60} (0)")

        score += min(50, call_score)

    # Grade
    if score >= 90:
        grade = "Excellent"
    elif score >= 75:
        grade = "Good"
    elif score >= 50:
        grade = "Fair"
    else:
        grade = "Poor"

    header = f"Score: {score}/100 ({grade}) — {server_id}"
    return header + "\n\n" + "\n".join(checks) + f"\n\nGrade: {grade}"


@mcp.tool()
async def bench(server_id: str, tool_name: str, args: dict | None = None, iterations: int = 5) -> str:
    """Benchmark tool latency — p50, p95, min, max ms. iterations: 1–20."""
    if args is None:
        args = {}
    iterations = max(1, min(20, iterations))

    srv = await _registry.get_server(server_id)
    if srv is None:
        return f"Server '{server_id}' not found. Use search() to find servers."

    transport_obj: BaseTransport = _get_transport(server_id, srv)
    resolved_config, missing = _resolve_config(srv.credentials, {})
    if missing:
        return _credentials_guide(server_id, srv.credentials, resolved_config)

    latencies: list[float] = []
    errors: list[str] = []
    boot_ms: float | None = None  # first call includes process boot — reported separately

    for i in range(iterations):
        t0 = time.monotonic()
        try:
            result = await asyncio.wait_for(
                transport_obj.execute(tool_name, args, resolved_config), timeout=TIMEOUT_STDIO_TOOL
            )
            elapsed_ms = (time.monotonic() - t0) * 1000
            _r = result.lower()
            if any(kw in _r for kw in ("error", "auth failed", "failed to connect", "timeout connecting")):
                errors.append(f"call {i + 1}: tool returned error")
            elif i == 0 and isinstance(transport_obj, PersistentStdioTransport):
                boot_ms = elapsed_ms  # exclude boot from latency stats
            else:
                latencies.append(elapsed_ms)
        except TimeoutError:
            errors.append(f"call {i + 1}: timeout (>30s)")
        except Exception as e:
            errors.append(f"call {i + 1}: {e!s:.60}")

    if not latencies and boot_ms is None:
        return f"All {iterations} calls failed:\n" + "\n".join(errors)

    # If all calls were boot or only one iteration, fall back to including boot_ms
    if not latencies and boot_ms is not None:
        latencies = [boot_ms]
        boot_ms = None

    latencies.sort()
    n = len(latencies)
    p50 = latencies[int(n * 0.50)]
    p95 = latencies[min(n - 1, int(n * 0.95))]
    avg = sum(latencies) / n

    lines = [
        f"Benchmark: {server_id}/{tool_name} ({n}/{iterations} succeeded)",
    ]
    if boot_ms is not None:
        lines.append(f"  boot:  {boot_ms:.0f}ms (process start, excluded from stats)")
    lines += [
        f"  p50: {p50:.0f}ms",
        f"  p95: {p95:.0f}ms",
        f"  min: {latencies[0]:.0f}ms",
        f"  max: {latencies[-1]:.0f}ms",
        f"  avg: {avg:.0f}ms",
    ]
    if errors:
        lines.append(f"  errors ({len(errors)}): " + "; ".join(errors))
    return "\n".join(lines)


@mcp.tool()
async def status() -> str:
    """Show current form, active connections, token stats."""
    explored = session["explored"]
    skills_data = session["skills"]
    grown = session["grown"]
    stats = session["stats"]
    current_form = session["current_form"]
    shapeshifted = session["shapeshift_tools"]

    lines = ["KITSUNE MCP STATUS", ""]

    # First-run onboarding — show once when session is completely clean
    is_first_run = not explored and not grown and stats["total_calls"] == 0
    if is_first_run:
        lines += [
            "Getting started:",
            "  1. search(\"what you need\")              → find servers across 7 registries",
            "  2. inspect(\"server-id\")                 → preview tools & token cost (zero load)",
            "  3. shapeshift(\"server-id\")              → tools appear natively in your session",
            "  4. call tools directly                  → no wrappers, full native speed",
            "  5. shiftback()                          → return to base form",
            "",
            "Example: search(\"web search\") → inspect(\"brave\") → shapeshift(\"brave\")",
            "",
        ]

    if current_form:
        lines.append(f"CURRENT FORM: {current_form}")
        lines.append(f"SHAPESHIFTED TOOLS ({len(shapeshifted)}): {', '.join(shapeshifted)}")
        lines.append("")
    else:
        lines += ["CURRENT FORM: base (no shapeshift active)", ""]

    # Persistent connections — ping all in parallel
    if _process_pool:
        pool_items = list(_process_pool.items())
        ping_results = await asyncio.gather(
            *[_ping(entry) for _, entry in pool_items],
            return_exceptions=True,
        )
        lines.append(f"PERSISTENT CONNECTIONS ({len(pool_items)})")
        for (pool_key, entry), responsive in zip(pool_items, ping_results, strict=False):
            label = entry.name or pool_key
            if not entry.is_alive():
                health = "dead"
            elif responsive is True:
                health = "alive+responsive"
            else:
                health = "alive+unresponsive"
            uptime = int(entry.uptime_seconds())
            mem = _rss_mb(entry.pid())
            mem_str = f" | mem: {mem}" if mem else ""
            conn_info = session["connections"].get(pool_key, {})
            tool_names = conn_info.get("tools", [])
            tool_str = f"Tools: {', '.join(tool_names)}" if tool_names else "Tools: none"
            lines.append(
                f"  {label} | PID {entry.pid()} | {health} | uptime: {uptime}s | calls: {entry.call_count}{mem_str}"
            )
            lines.append(f"    {tool_str}")
        lines.append("")

    if explored:
        lines.append(f"EXPLORED ({len(explored)})")
        for sid, info in explored.items():
            lines.append(f"  {sid} [{info.get('status', '?')}]")
        lines.append("")

    if grown:
        lines.append(f"ACTIVE NODES ({len(grown)})")
        for sid, info in grown.items():
            lines.append(
                f"  {sid} | {info.get('calls', 0)} calls | last: {info.get('last_tool', '—')}"
            )
        lines.append("")

    skill_tokens = 0
    if skills_data:
        lines.append(f"SKILLS ({len(skills_data)})")
        for sid, info in skills_data.items():
            t = info.get("tokens", 0)
            skill_tokens += t
            lines.append(f"  {sid} ~{t:,} tokens")
        lines.append("")

    # Token savings vs always-on: sum measured schema costs for inspected servers
    # that are NOT currently shapeshifted (those would be loaded if always-on).
    not_shapeshifted = {
        sid: info
        for sid, info in explored.items()
        if info.get("token_cost") and sid != current_form
    }
    lazy_saved = sum(info["token_cost"] for info in not_shapeshifted.values())

    lines += [
        "PERFORMANCE STATS",
        f"  Total calls:       {stats['total_calls']}",
        f"  Tokens sent:     ~{stats['tokens_sent']:,}",
        f"  Tokens received: ~{stats['tokens_received']:,}",
        f"  Saved via fetch: ~{stats['tokens_saved_browse']:,}",
        f"  Skill context:   ~{skill_tokens:,} tokens",
    ]
    if stats["total_calls"] > 0:
        avg = stats["tokens_received"] // stats["total_calls"]
        lines.append(f"  Avg response:    ~{avg} tokens")
    if lazy_saved > 0:
        n = len(not_shapeshifted)
        lines.append(
            f"  Saved vs always-on: ~{lazy_saved:,} tokens "
            f"[based on {n} inspected schema(s)]"
        )

    return "\n".join(lines)


@mcp.tool()
async def setup(name: str) -> str:
    """Setup wizard for a connected server. Call repeatedly until all requirements are met."""
    conn = next((c for c in session["connections"].values() if c.get("name") == name), None)
    if conn is None:
        connected = [c.get("name", "?") for c in session["connections"].values()]
        if connected:
            return f"No connection named '{name}'. Connected: {', '.join(connected)}"
        return f"No connection named '{name}'. Use connect() first."

    install_cmd = conn["command"].split()
    transport = PersistentStdioTransport(install_cmd)
    tools = await transport.list_tools()

    resource_text = await _fetch_resource_docs(transport)
    reqs = _probe_requirements(tools, resource_text)
    guide = _format_setup_guide(reqs, name, tools=tools)

    lines = [f"Setup: {name}"]

    if reqs["needs_oauth"]:
        lines.append("⚠️  OAuth flow detected — browser authentication may be required.")

    if reqs["schema_creds"]:
        schema_missing = [c for c in reqs["schema_creds"] if c not in reqs["set_env"]]
        if schema_missing:
            lines.append(f"Required credentials (from schema): {', '.join(schema_missing)}")

    if not guide:
        lines.append("✅ All requirements satisfied — ready to call tools.")
        if tools:
            lines.append(f"\nAvailable tools ({len(tools)}): {', '.join(t.get('name', '?') for t in tools)}")
        return "\n".join(lines)

    lines.append(guide)

    if not reqs["resource_scan"]:
        lines.append("\n(No resource docs found — probe based on tool schemas only.)")

    return "\n".join(lines)
