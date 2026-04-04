import asyncio
import contextlib
import ipaddress
import json
import shlex
import time
from datetime import datetime
from urllib.parse import urlparse

import httpx
from mcp.server.fastmcp import Context

from chameleon_mcp.app import mcp
from chameleon_mcp.constants import (
    MAX_INSPECT_DESC,
    MAX_RESOURCE_DOCS,
    MAX_RESPONSE_TOKENS,
    RESOURCE_PRIORITY_KEYWORDS,
    TIMEOUT_FETCH_URL,
    TIMEOUT_RESOURCE_LIST,
    TIMEOUT_RESOURCE_READ,
    TIMEOUT_STDIO_INIT,
    TIMEOUT_STDIO_TOOL,
)
from chameleon_mcp.credentials import (
    _credentials_guide,
    _registry_headers,
    _resolve_config,
    _save_to_env,
    _smithery_available,
    _to_env_var,
)
from chameleon_mcp.morph import _do_shed, _fetch_tools_list, _register_proxy_tools
from chameleon_mcp.probe import _doc_uri_priority, _format_setup_guide, _probe_requirements
from chameleon_mcp.registry import (
    REGISTRY_BASE,
    NpmRegistry,
    PyPIRegistry,
    SmitheryRegistry,
    _registry,
)
from chameleon_mcp.session import _save_skills, session
from chameleon_mcp.transport import (
    BaseTransport,
    DockerTransport,
    HTTPSSETransport,
    PersistentStdioTransport,
    StdioTransport,
    WebSocketTransport,
    _ping,
    _process_pool,
)
from chameleon_mcp.utils import (
    _estimate_tokens,
    _get_http_client,
    _strip_html,
    _truncate,
    _try_axonmcp,
)

# Base tool names — used for collision detection in morph()
_BASE_TOOL_NAMES = {
    "search", "inspect", "call", "run", "fetch",
    "skill", "key", "auto", "status", "morph", "shed",
    "connect", "release", "test", "bench", "setup",
}


@mcp.tool()
async def search(query: str, registry: str = "all", limit: int = 5) -> str:
    """Search for MCP servers. registry: 'all'|'smithery'|'npm'|'pypi'."""
    if registry == "smithery":
        reg = SmitheryRegistry()
    elif registry == "npm":
        reg = NpmRegistry()
    elif registry == "pypi":
        reg = PyPIRegistry()
    else:
        reg = _registry

    servers = await reg.search(query, limit)
    if not servers:
        return f"No servers found for '{query}'. Try a different query or registry."

    lines = [f"SERVERS — '{query}' ({len(servers)} found)\n"]
    for s in servers:
        creds = ", ".join(s.credentials.keys()) if s.credentials else "free"
        lines.append(f"{s.id} | {s.name} — {s.description} | {s.source}/{s.transport} | creds: {creds}")
        session["explored"][s.id] = {"name": s.name, "desc": s.description, "status": "explored"}

    lines.append("\ninspect('<id>') for details | call('<id>', '<tool>', args) to call")
    return "\n".join(lines)


@mcp.tool()
async def inspect(server_id: str) -> str:
    """Show a server's tools, credentials, and token cost."""
    srv = await _registry.get_server(server_id)
    if srv is None:
        return f"Server '{server_id}' not found. Use search() to find servers."

    lines = [
        f"{srv.name} ({srv.id})",
        f"Source: {srv.source} | Transport: {srv.transport}",
        f"Description: {srv.description[:200]}",
        "",
    ]

    if srv.credentials:
        lines.append("CREDENTIALS REQUIRED")
        for cred_key, desc in srv.credentials.items():
            lines.append(f"  {cred_key} → {_to_env_var(cred_key)}" + (f": {desc[:80]}" if desc else ""))
        lines.append("")
    else:
        lines += ["CREDENTIALS: none required", ""]

    if srv.transport == "stdio":
        cmd_str = " ".join(srv.install_cmd) if srv.install_cmd else f"npx -y {srv.id}"
        lines += [f"RUN: {cmd_str}", ""]

    if srv.tools:
        lines.append(f"TOOLS ({len(srv.tools)})")
        for t in srv.tools:
            tname = t.get("name", "?")
            tdesc = (t.get("description") or "")[:MAX_INSPECT_DESC]
            params = list((t.get("inputSchema") or {}).get("properties", {}).keys())
            pstr = f"({', '.join(params)})" if params else ""
            lines.append(f"  {tname}{pstr} — {tdesc}")
        lines.append(f"\nToken cost: ~{srv.token_cost} tokens")
    else:
        lines.append("TOOLS: not listed in registry")

    session["explored"][srv.id] = {
        "name": srv.name, "desc": srv.description,
        "status": "inspected", "token_cost": srv.token_cost,
    }
    return "\n".join(lines)


@mcp.tool()
async def call(
    server_id: str,
    tool_name: str,
    arguments: dict | None = None,
    config: dict | None = None,
) -> str:
    """Call a tool on an MCP server (remote HTTP/WS or local stdio). Creds auto-loaded from env."""
    if arguments is None:
        arguments = {}
    if config is None:
        config = {}
    srv = await _registry.get_server(server_id)
    credentials = srv.credentials if srv else {}

    resolved_config, missing = _resolve_config(credentials, config)
    if missing:
        return _credentials_guide(server_id, credentials, resolved_config)

    if server_id.startswith("docker:"):
        transport: BaseTransport = DockerTransport(server_id[len("docker:"):])
    elif server_id.startswith(("ws://", "wss://")):
        transport = WebSocketTransport(server_id)
    elif srv and srv.transport == "websocket":
        transport = WebSocketTransport(srv.url)
    elif srv and srv.transport == "stdio":
        cmd = srv.install_cmd or ["npx", "-y", server_id]
        transport = StdioTransport(cmd)
    else:
        transport = HTTPSSETransport(server_id)

    result = await transport.execute(tool_name, arguments, resolved_config)

    prior = session["grown"].get(server_id, {"calls": 0})
    session["grown"][server_id] = {
        "last_tool": tool_name,
        "calls": prior["calls"] + 1,
        "status": "active",
    }
    return result


@mcp.tool()
async def run(
    package: str,
    tool_name: str,
    arguments: dict | None = None,
) -> str:
    """Run a tool from a local npm/pip package directly (no registry lookup).

    package: npm name (npx) or 'uvx:package-name' for Python uv packages.
    """
    if arguments is None:
        arguments = {}
    cmd = ["uvx", package[4:]] if package.startswith("uvx:") else ["npx", "-y", package]

    transport = StdioTransport(cmd)
    result = await transport.execute(tool_name, arguments, {})

    prior = session["grown"].get(package, {"calls": 0})
    session["grown"][package] = {
        "last_tool": tool_name,
        "calls": prior["calls"] + 1,
        "status": "active",
    }
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
    """Inject a Smithery skill into context. Skills are persisted across sessions.

    qualified_name: Smithery skill ID (e.g. 'org/skill-name')
    forget: if True, remove the skill from context and disk instead of injecting it
    """
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
    """Auto-discover and call the best server for a task. Full pipeline in one call."""
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
        if _smithery_available():
            servers = await SmitheryRegistry().search(task, limit=3)
        else:
            servers = await NpmRegistry().search(task, limit=3)
        if not servers:
            note = "" if _smithery_available() else " (npm-only — set SMITHERY_API_KEY for Smithery results)"
            return f"No servers found for '{task}'{note}. Use search() or provide server_hint."
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
        if tools:
            tool_lines = [f"  {t['name']} — {(t.get('description') or '')[:80]}" for t in tools]
            return "\n".join([
                f"{server_name} ({server_id}) ready. Available tools:",
                "",
                *tool_lines,
                "",
                f'Call: auto("{task}", "<tool>", args, server_hint="{server_id}")',
            ])
        return f"{server_id} ready (no tools listed). Use call() to call tools directly."

    srv = await _registry.get_server(server_id)
    if srv and srv.transport == "stdio":
        cmd = srv.install_cmd or ["npx", "-y", server_id]
        transport: BaseTransport = StdioTransport(cmd)
    else:
        transport = HTTPSSETransport(server_id)

    result = await transport.execute(tool_name, arguments, resolved_config)

    prior = session["grown"].get(server_id, {"calls": 0})
    session["grown"][server_id] = {
        "last_tool": tool_name,
        "calls": prior["calls"] + 1,
        "status": "active",
    }
    return result


@mcp.tool()
async def morph(server_id: str, ctx: Context) -> str:
    """Take a server's form — register its tools directly."""
    # 1. Check pool connections first (friendly names from connect() take priority)
    pool_conn = None
    for _pk, conn in session["connections"].items():
        if conn.get("name") == server_id or conn.get("command") == server_id:
            pool_conn = conn
            break

    if pool_conn is None:
        # Fall back to registry lookup
        srv = await _registry.get_server(server_id)
    else:
        srv = None  # use pool path below

    if srv is None and pool_conn is None:
        return f"Server '{server_id}' not found. Use search() to find servers, or connect() for local servers."

    if pool_conn is not None:

        # Morph from pool connection
        cmd = pool_conn["command"].split()
        tool_names = pool_conn.get("tools", [])

        _do_shed()

        transport: BaseTransport = PersistentStdioTransport(cmd)
        # Fetch full schemas from the live process
        raw_tools = await transport.list_tools()
        if not raw_tools and tool_names:
            raw_tools = [{"name": n, "description": "", "inputSchema": {}} for n in tool_names]

        registered = _register_proxy_tools(server_id, raw_tools, transport, {}, _BASE_TOOL_NAMES)

        if not registered:
            return f"No tools could be registered from '{server_id}'."

        session["morphed_tools"] = registered
        session["current_form"] = server_id

        with contextlib.suppress(Exception):
            await ctx.session.send_tool_list_changed()

        lines = [
            f"Morphed into '{server_id}' (pool connection) — {len(registered)} tool(s) registered:",
            *[f"  {t}" for t in registered],
            "",
            "Call them directly, or use shed() to return to base form.",
        ]
        return "\n".join(lines)

    # 2. Get tool list — use registry data if available, else fetch via stdio
    tools = srv.tools or []
    if not tools:
        if srv.transport == "stdio":
            cmd = srv.install_cmd or ["npx", "-y", server_id]
            tools = await _fetch_tools_list(cmd)
        if not tools:
            return f"No tools found for '{server_id}'. Try inspect('{server_id}') first."

    # 3. Drop previous form
    _do_shed()

    # 4. Resolve credentials
    resolved_config, missing = _resolve_config(srv.credentials, {})
    if missing:
        creds_msg = _credentials_guide(server_id, srv.credentials, resolved_config)
        return f"Cannot morph into '{server_id}' — missing credentials:\n\n{creds_msg}"

    # 5. Build transport — use persistent if process already in pool
    if srv.transport == "stdio":
        cmd = srv.install_cmd or ["npx", "-y", server_id]
        pool_key = json.dumps(cmd, sort_keys=True)
        if pool_key in _process_pool and _process_pool[pool_key].is_alive():
            transport = PersistentStdioTransport(cmd)
        else:
            transport = StdioTransport(cmd)
    else:
        transport = HTTPSSETransport(server_id)

    # 6. Register proxy tools, handling name collisions with base tools
    registered = _register_proxy_tools(server_id, tools, transport, resolved_config, _BASE_TOOL_NAMES)

    if not registered:
        return f"No tools could be registered from '{server_id}'."

    session["morphed_tools"] = registered
    session["current_form"] = server_id

    # 7. Notify client that tool list has changed
    with contextlib.suppress(Exception):
        await ctx.session.send_tool_list_changed()

    lines = [
        f"Morphed into '{server_id}' — {len(registered)} tool(s) registered:",
        *[f"  {t}" for t in registered],
        "",
        "Call them directly, or use shed() to return to base form.",
    ]
    return "\n".join(lines)


@mcp.tool()
async def shed(ctx: Context) -> str:
    """Drop current form and remove morphed tools. NOTE: Does NOT kill persistent connections. Use release(name) for that."""
    if not session["morphed_tools"]:
        return "Already in base form."
    form = session["current_form"]
    removed = _do_shed()
    with contextlib.suppress(Exception):
        await ctx.session.send_tool_list_changed()
    return f"Shed '{form}'. Removed: {', '.join(removed)}"


@mcp.tool()
async def connect(command: str, name: str = "", timeout: int = 60, inherit_stderr: bool = True) -> str:
    """Connect a persistent MCP server. Process stays alive between calls.

    command: shell command string, e.g. 'uvx voice-mode' or 'npx -y mcp-server-xyz'
    name: friendly name for release(), e.g. 'voice'
    timeout: startup timeout in seconds (default 60)
    inherit_stderr: forward subprocess stderr to terminal (default True)
    """
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

    # Fetch resource docs to enrich requirement probing (best-effort, short timeout)
    resource_text = ""
    try:
        resources = await asyncio.wait_for(transport.list_resources(), timeout=TIMEOUT_RESOURCE_LIST)
        all_doc_uris = [r["uri"] for r in resources]
        doc_uris = sorted(
            (u for u in all_doc_uris if _doc_uri_priority(u) < len(RESOURCE_PRIORITY_KEYWORDS)),
            key=_doc_uri_priority,
        )[:MAX_RESOURCE_DOCS]
        parts = await asyncio.gather(
            *[asyncio.wait_for(transport.read_resource(u), timeout=TIMEOUT_RESOURCE_READ) for u in doc_uris],
            return_exceptions=True,
        )
        resource_text = "\n".join(p for p in parts if isinstance(p, str))
    except Exception:
        pass

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
    parts = [
        f"Connected: {friendly} (PID {entry.pid()})",
        tool_summary,
        f"Release with: release('{friendly}')",
    ]
    if setup_guide:
        parts.append(setup_guide)
        parts.append(f"\nCall setup('{friendly}') for step-by-step guidance.")
    return "\n".join(parts)


@mcp.tool()
async def release(name: str) -> str:
    """Kill a persistent connection and remove it from the pool.

    name: friendly name passed to connect(), or the pool key
    """
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
    """Validate an MCP server and return a quality score 0-100.

    level: 'basic' (registry + schema checks) or 'full' (includes live tool calls)
    """
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
            tools = await asyncio.wait_for(_fetch_tools_list(cmd), timeout=TIMEOUT_STDIO_INIT)
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
        checks.append("✅ No name collisions with Chameleon base tools (+10)")
    else:
        checks.append(f"⚠️  Name collisions: {', '.join(collisions)} (0) — will be prefixed on morph()")

    # Check 7: Live tool calls (full mode only, 10 pts per tool, max 5 tools)
    if level == "full" and tools:
        checks.append("\n--- FULL MODE: live tool calls ---")
        call_score = 0
        for t in tools[:5]:
            tname = t.get("name", "")
            # Build minimal dummy args
            props = (t.get("inputSchema") or {}).get("properties", {})
            required = set((t.get("inputSchema") or {}).get("required", []))
            dummy_args = {}
            for pname, pschema in props.items():
                if pname in required:
                    ptype = pschema.get("type", "string")
                    dummy_args[pname] = {"string": "test", "integer": 0, "boolean": False, "number": 0.0}.get(ptype, "test")

            try:
                if srv.transport == "stdio":
                    cmd = srv.install_cmd or ["npx", "-y", server_id]
                    transport_obj: BaseTransport = StdioTransport(cmd)
                else:
                    transport_obj = HTTPSSETransport(server_id)
                resolved_config, _ = _resolve_config(srv.credentials, {})
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
    """Benchmark a tool's latency. Returns p50, p95, min, max, avg in ms.

    iterations: number of calls (1-20, default 5)
    """
    if args is None:
        args = {}
    iterations = max(1, min(20, iterations))

    srv = await _registry.get_server(server_id)
    if srv is None:
        return f"Server '{server_id}' not found. Use search() to find servers."

    if srv.transport == "stdio":
        cmd = srv.install_cmd or ["npx", "-y", server_id]
        transport_obj: BaseTransport = StdioTransport(cmd)
    else:
        transport_obj = HTTPSSETransport(server_id)

    resolved_config, missing = _resolve_config(srv.credentials, {})
    if missing:
        return _credentials_guide(server_id, srv.credentials, resolved_config)

    latencies: list[float] = []
    errors: list[str] = []

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
            else:
                latencies.append(elapsed_ms)
        except TimeoutError:
            errors.append(f"call {i + 1}: timeout (>30s)")
        except Exception as e:
            errors.append(f"call {i + 1}: {e!s:.60}")

    if not latencies:
        return f"All {iterations} calls failed:\n" + "\n".join(errors)

    latencies.sort()
    n = len(latencies)
    p50 = latencies[int(n * 0.50)]
    p95 = latencies[min(n - 1, int(n * 0.95))]
    avg = sum(latencies) / n

    lines = [
        f"Benchmark: {server_id}/{tool_name} ({n}/{iterations} succeeded)",
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
    morphed = session["morphed_tools"]

    lines = ["CHAMELEON MCP STATUS", ""]

    if current_form:
        lines.append(f"CURRENT FORM: {current_form}")
        lines.append(f"MORPHED TOOLS ({len(morphed)}): {', '.join(morphed)}")
        lines.append("")
    else:
        lines += ["CURRENT FORM: base (no morph active)", ""]

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
            conn_info = session["connections"].get(pool_key, {})
            tool_names = conn_info.get("tools", [])
            tool_str = f"Tools: {', '.join(tool_names)}" if tool_names else "Tools: none"
            lines.append(
                f"  {label} | PID {entry.pid()} | {health} | uptime: {uptime}s | calls: {entry.call_count}"
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

    # Token savings vs always-on: compare what context cost would be if all explored
    # servers were loaded at startup vs what we actually used
    always_on_cost = sum(info.get("token_cost", 500) for info in explored.values())
    actual_used = stats["tokens_sent"] + stats["tokens_received"]
    lazy_saved = max(0, always_on_cost - actual_used)

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
        lines.append(f"  Saved vs always-on: ~{lazy_saved:,} tokens ({len(explored)} servers × lazy-load)")

    return "\n".join(lines)


@mcp.tool()
async def setup(name: str) -> str:
    """Step-by-step setup wizard for a connected server. Call repeatedly until all requirements are met.

    name: friendly name used in connect(), e.g. 'voice'
    Probes current state and shows the next unresolved step.
    """
    conn = next((c for c in session["connections"].values() if c.get("name") == name), None)
    if conn is None:
        connected = [c.get("name", "?") for c in session["connections"].values()]
        if connected:
            return f"No connection named '{name}'. Connected: {', '.join(connected)}"
        return f"No connection named '{name}'. Use connect() first."

    install_cmd = conn["command"].split()
    transport = PersistentStdioTransport(install_cmd)
    tools = await transport.list_tools()

    resource_text = ""
    try:
        resources = await asyncio.wait_for(transport.list_resources(), timeout=TIMEOUT_RESOURCE_LIST)
        all_doc_uris = [r["uri"] for r in resources]
        doc_uris = sorted(
            (u for u in all_doc_uris if _doc_uri_priority(u) < len(RESOURCE_PRIORITY_KEYWORDS)),
            key=_doc_uri_priority,
        )[:MAX_RESOURCE_DOCS]
        parts = await asyncio.gather(
            *[asyncio.wait_for(transport.read_resource(u), timeout=TIMEOUT_RESOURCE_READ) for u in doc_uris],
            return_exceptions=True,
        )
        resource_text = "\n".join(p for p in parts if isinstance(p, str))
    except Exception:
        pass

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
