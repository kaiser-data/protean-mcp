# Chameleon MCP — 7.5 → 9.0 Roadmap

---

## Assessment

**What is strong:**
- Core MCP tool proxying via `morph()` / `shed()` — sound and well-tested
- Registry fan-out (official, mcpregistry, glama, npm, pypi, github, smithery)
- Lean profile + forge profile split — good token cost story
- `bench()`, `test()`, `setup()` — real developer value

**What is missing for 9/10:**
- MCP is tools + **resources** + **prompts** — morph() only proxies tools today
- No safety model for spawning arbitrary npm/pip/GitHub/Docker processes
- Missing credentials surface as cryptic runtime errors instead of upfront warnings
- Token savings claims are unverified — no runnable benchmark
- `send_tool_list_changed()` is called but client compatibility is untested and undocumented

---

## Roadmap

| # | Item | Phase | Effort |
|---|------|-------|--------|
| 1 | Full MCP proxying: resources + prompts in morph() | 1 | medium |
| 2 | Install command validation + source trust warnings | 1 | small |
| 3 | Proactive credential warning at morph() time | 1 | small |
| 4 | Reproducible benchmark script (`examples/benchmark.py`) | 2 | medium |
| 5 | Notification call tests + compatibility matrix | 2 | small |
| 6 | Provenance in search/inspect/morph/call output | 2 | small |
| 7 | `status()` measured token savings (not estimated) | 3 | small |
| 8 | README claims cleanup + benchmark link | 3 | small |

---

## Phase 1 — Highest-impact fixes

### 1. Full MCP proxying: resources + prompts in morph()

MCP exposes three first-class concepts — tools, resources, prompts. After `morph()`, the AI should have access to all three. `shed()` cleans up all three.

**Verified FastMCP 3.0.1 API (tested):**
```python
from fastmcp.resources import FunctionResource
from fastmcp.prompts import FunctionPrompt

# Resources
r = FunctionResource.from_function(fn, uri="data://srv/x", name="X", mime_type="text/plain")
mcp.add_resource(r)
mcp._local_provider.remove_resource(str(r.uri))   # use str(r.uri) — normalized AnyUrl

# Prompts
p = FunctionPrompt.from_function(fn, name="my_prompt", description="...")
mcp.add_prompt(p)
mcp._local_provider.remove_prompt(p.name)

# Notifications
await ctx.session.send_resource_list_changed()
await ctx.session.send_prompt_list_changed()
```

**Files to change:**

`chameleon_mcp/constants.py`
```python
TIMEOUT_PROMPT_LIST = 5.0
```

`chameleon_mcp/transport.py` — add to `PersistentStdioTransport` (after `read_resource()`, line ~451):
```python
async def list_prompts(self) -> list[dict]:
    entry = await self._get_or_start()
    async with entry.lock:
        msg_id = entry.next_id; entry.next_id += 1
        entry.proc.stdin.write(self._frame(
            {"jsonrpc": "2.0", "id": msg_id, "method": "prompts/list", "params": {}}
        ))
        await entry.proc.stdin.drain()
        resp = await StdioTransport._read_response(entry.proc.stdout, expected_id=msg_id, timeout=10.0)
        if not resp or "error" in resp:
            return []
        return resp.get("result", {}).get("prompts", [])

async def get_prompt(self, name: str, arguments: dict) -> list[dict]:
    entry = await self._get_or_start()
    async with entry.lock:
        msg_id = entry.next_id; entry.next_id += 1
        entry.proc.stdin.write(self._frame(
            {"jsonrpc": "2.0", "id": msg_id, "method": "prompts/get",
             "params": {"name": name, "arguments": arguments}}
        ))
        await entry.proc.stdin.drain()
        resp = await StdioTransport._read_response(entry.proc.stdout, expected_id=msg_id, timeout=10.0)
        if not resp or "error" in resp:
            return []
        return resp.get("result", {}).get("messages", [])
```

`chameleon_mcp/session.py` — add after `"morphed_tools"`:
```python
"morphed_resources": [],    # normalized URI strings
"morphed_prompts": [],      # prompt names
```

`chameleon_mcp/morph.py` — new imports + two new functions + extend `_do_shed()`:

```python
from fastmcp.resources import FunctionResource
from fastmcp.prompts import FunctionPrompt

_URI_TEMPLATE_RE = re.compile(r'\{[a-zA-Z_][a-zA-Z0-9_]*\}')  # detect {param} patterns

def _register_proxy_resources(transport, resources: list[dict]) -> list[str]:
    """Proxy static resources. Returns normalized URI strings registered."""
    registered = []
    for res in resources:
        uri = res.get("uri", "")
        if not uri or _URI_TEMPLATE_RE.search(uri):
            continue   # skip missing or template URIs
        name = res.get("name") or uri
        description = (res.get("description") or "")[:120]
        mime_type = res.get("mimeType") or "text/plain"
        _uri, _t = uri, transport

        async def _proxy(_u=_uri, _tr=_t) -> str:
            try:
                return await _tr.read_resource(_u)
            except Exception as e:
                return f"[Resource unavailable: {e}]"

        _proxy.__name__ = name
        try:
            r = FunctionResource.from_function(
                fn=_proxy, uri=_uri, name=name, description=description, mime_type=mime_type,
            )
            mcp.add_resource(r)
            registered.append(str(r.uri))
        except Exception:
            pass
    return registered

def _register_proxy_prompts(transport, prompts: list[dict]) -> list[str]:
    """Proxy prompts. Returns list of registered names."""
    import inspect as _inspect
    registered = []
    for prompt_schema in prompts:
        name = prompt_schema.get("name", "")
        if not name:
            continue
        description = (prompt_schema.get("description") or "")[:120]
        args_schema = prompt_schema.get("arguments", [])
        _name, _t = name, transport

        async def _proxy(**kwargs):
            messages = await _t.get_prompt(_name, kwargs)
            return "\n---\n".join(
                f"[{m.get('role','user')}]: {m.get('content', {}).get('text', '')}"
                for m in messages if isinstance(m, dict)
            )

        # Build named parameter signature so FunctionPrompt sees correct arguments
        params = []
        for arg in args_schema:
            arg_name = arg.get("name", "")
            if not arg_name:
                continue
            default = _inspect.Parameter.empty if arg.get("required") else ""
            params.append(_inspect.Parameter(
                arg_name, _inspect.Parameter.POSITIONAL_OR_KEYWORD,
                default=default, annotation=str,
            ))
        _proxy.__signature__ = _inspect.Signature(params)
        _proxy.__name__ = name
        _proxy.__doc__ = description

        try:
            p = FunctionPrompt.from_function(fn=_proxy, name=name, description=description)
            mcp.add_prompt(p)
            registered.append(name)
        except Exception:
            pass
    return registered
```

Extend `_do_shed()` — add after tool removal loop:
```python
for uri in session.get("morphed_resources", []):
    try:
        mcp._local_provider.remove_resource(uri)
    except Exception:
        pass
session["morphed_resources"] = []

for pname in session.get("morphed_prompts", []):
    try:
        mcp._local_provider.remove_prompt(pname)
    except Exception:
        pass
session["morphed_prompts"] = []
```

`chameleon_mcp/tools.py` — update import + both morph() paths + shed():

Add to import: `_register_proxy_resources, _register_proxy_prompts`

In both morph() code paths, after `session["morphed_tools"] = registered`:
```python
morphed_resources, morphed_prompts = [], []
if hasattr(transport, "list_resources"):
    try:
        raw_res = await asyncio.wait_for(transport.list_resources(), timeout=TIMEOUT_RESOURCE_LIST)
        morphed_resources = _register_proxy_resources(transport, raw_res)
    except Exception:
        pass
if hasattr(transport, "list_prompts"):
    try:
        raw_prompts = await asyncio.wait_for(transport.list_prompts(), timeout=TIMEOUT_PROMPT_LIST)
        morphed_prompts = _register_proxy_prompts(transport, raw_prompts)
    except Exception:
        pass
session["morphed_resources"] = morphed_resources
session["morphed_prompts"] = morphed_prompts

with contextlib.suppress(Exception):
    await ctx.session.send_tool_list_changed()
if morphed_resources:
    with contextlib.suppress(Exception):
        await ctx.session.send_resource_list_changed()
if morphed_prompts:
    with contextlib.suppress(Exception):
        await ctx.session.send_prompt_list_changed()
```

Extend morph() output:
```python
extras = []
if morphed_resources: extras.append(f"{len(morphed_resources)} resource(s)")
if morphed_prompts:   extras.append(f"{len(morphed_prompts)} prompt(s)")
extra_note = f" + {', '.join(extras)}" if extras else ""
# "Morphed into 'X' — 10 tool(s) + 3 resource(s), 1 prompt(s):"
```

In shed(): read counts before `_do_shed()`, send notifications, extend output:
```python
n_res = len(session.get("morphed_resources", []))
n_prompts = len(session.get("morphed_prompts", []))
removed = _do_shed()
with contextlib.suppress(Exception):
    await ctx.session.send_tool_list_changed()
if n_res:
    with contextlib.suppress(Exception):
        await ctx.session.send_resource_list_changed()
if n_prompts:
    with contextlib.suppress(Exception):
        await ctx.session.send_prompt_list_changed()
```

**Tests to add (`tests/test_morph.py`)** — ~13 new tests:
- `TestRegisterProxyResources`: registers resource, skips URI templates (regex), skips empty URI, read failure returns error string, proxy calls transport
- `TestRegisterProxyPrompts`: registers prompt with args in signature, no-arg prompt, skips empty name, proxy calls transport, message format
- `TestDoShedAll`: removes tools + resources + prompts from FastMCP, tolerates already-removed items
- `TestMorphRegistersAll`: resources registered when transport supports it, skipped for HTTP transport, graceful on list_resources exception

**Edge cases / API notes:**
- Use `str(r.uri)` (Pydantic AnyUrl normalized) for resource removal key, not raw input string
- `mcp._local_provider` is private — wrap in `getattr(mcp, '_local_provider', None)` defensively
- URI template regex `\{[a-zA-Z_][a-zA-Z0-9_]*\}` — more precise than checking `{` alone
- Prompt proxy message format: convert to string via join — loses multi-turn structure but is reliable across FastMCP versions

---

### 2. Install command validation + source trust warnings

**Why it matters:** `transport.py` calls `asyncio.create_subprocess_exec(*install_cmd)` with zero validation. Shell injection and path traversal are real risks for team deployments.

**Files to change:**

`chameleon_mcp/constants.py`:
```python
TRUST_HIGH   = {"official"}
TRUST_MEDIUM = {"mcpregistry", "glama", "smithery"}
TRUST_LOW    = {"npm", "pypi", "github"}
```

`chameleon_mcp/transport.py` — add before any subprocess spawn:
```python
_SHELL_METACHAR_RE = re.compile(r'[&;|$`\n]')
_PATH_TRAVERSAL_RE = re.compile(r'\.\.[/\\]')

def _validate_install_cmd(cmd: list[str]) -> None:
    if not cmd:
        raise ValueError("Empty install command")
    argv0 = cmd[0]
    if _SHELL_METACHAR_RE.search(argv0):
        raise ValueError(f"Shell metacharacter in command: {argv0!r}")
    if _PATH_TRAVERSAL_RE.search(argv0):
        raise ValueError(f"Path traversal in command: {argv0!r}")
```

Call `_validate_install_cmd(install_cmd)` in `StdioTransport.execute()`, `PersistentStdioTransport._get_or_start()`, and `DockerTransport.execute()` before subprocess creation.

`chameleon_mcp/tools.py` — in `morph()`, `call()`, `connect()` output: append trust note:
```python
from chameleon_mcp.constants import TRUST_HIGH, TRUST_MEDIUM
source = srv.source if srv else "unknown"
if source not in TRUST_HIGH and source not in TRUST_MEDIUM:
    trust_note = f"\n⚠️  Source: {source} (community — not verified by official MCP registry)"
else:
    trust_note = f"\n✓  Source: {source}"
```

**Tests (`tests/test_transports.py`):**
- `test_validate_install_cmd_rejects_shell_injection`
- `test_validate_install_cmd_rejects_path_traversal`
- `test_validate_install_cmd_accepts_valid_npx`
- `test_validate_install_cmd_rejects_empty`

---

### 3. Proactive credential warning at morph() time

**Why it matters:** Missing credentials cause cryptic runtime errors. `_probe_requirements()` and `_credentials_guide()` already exist but are only called by `setup()` and `inspect()`. Surface them in `morph()` output.

**Files to change:**

`chameleon_mcp/tools.py` — in morph(), after tool registration (best-effort, non-blocking):
```python
try:
    reqs = _probe_requirements(raw_tools, resource_text or "")
    cred_guide = _credentials_guide(srv.credentials or {})
    missing_env = reqs.get("missing_env", {})
    if cred_guide or missing_env:
        lines.append("\n⚠️  Credentials may be required before calling tools:")
        if cred_guide:
            lines.append(cred_guide)
        for var in missing_env:
            if var not in (cred_guide or ""):
                lines.append(f'  key("{var}", "your-value")')
except Exception:
    pass
```

**Tests (`tests/test_tools.py`):**
- `test_morph_warns_on_missing_credentials`
- `test_morph_no_warning_when_credentials_set`
- `test_morph_still_succeeds_when_credential_probe_fails`

---

## Phase 2 — Credibility and trust upgrades

### 4. Reproducible benchmark script

**Why it matters:** README claims "~240 tokens overhead", "~825 tokens", "65% reduction" — unverified. One runnable script turns marketing into engineering.

**New file: `examples/benchmark.py`**

Measures (no network needed):
- Token overhead: load actual tool schemas via `server.py` imports, run `_estimate_tokens()` on lean vs forge tool lists
- Token savings: compare `_estimate_tokens(tools_for_N_servers)` vs always-on baseline
- Latency: mock transport timing for morph()/shed() cycle

Output:
```
=== Token overhead (measured from actual schemas) ===
chameleon-mcp lean (6 tools):      XXX tokens
chameleon-forge full (17 tools):   XXX tokens
static config 5 servers avg:       XXX tokens

=== Savings: lazy morph vs always-on ===
2 servers lazy:   saves ~X tokens/request
5 servers lazy:   saves ~X tokens/request
```

Also add `docs/benchmarks.md` with methodology and a reference run output.

Update README to link: `> See [examples/benchmark.py](examples/benchmark.py) for methodology.`

---

### 5. Notification tests + compatibility matrix

**New file: `tests/test_notifications.py`**
- Mock `ctx.session` with `AsyncMock`
- Verify `send_tool_list_changed()` called exactly once per morph, once per shed
- Verify `send_resource_list_changed()` called iff `morphed_resources` non-empty
- Verify `send_prompt_list_changed()` called iff `morphed_prompts` non-empty
- Verify no notification sent if morph fails

**New file: `docs/compatibility.md`**

| Client | Tool refresh on morph | Tool refresh on shed | Resource refresh | Notes |
|--------|----------------------|---------------------|-----------------|-------|
| Claude Code | ✅ tested | ✅ tested | ? | |
| Claude Desktop | ✅ tested | ✅ tested | ? | |
| Cursor | ? | ? | ? | help wanted |
| Cline | ? | ? | ? | help wanted |
| OpenClaw | ? | ? | ? | help wanted |

Include manual test protocol so contributors can fill in rows.

---

### 6. Provenance in search/inspect/morph/call output

**Why it matters:** Users need to know where a server comes from before running it.

**Files to change (`chameleon_mcp/tools.py` output formatting only):**
- `search()`: ensure `source:` appears on every result line (audit current format)
- `inspect()`: add `Source: {srv.source}` as first line of output
- `morph()`: source note already added in step 2 — verify it appears
- `call()`: add `(source: {source})` when server is resolved from registry

---

## Phase 3 — Proof, adoption, and polish ✅ COMPLETE (2026-04-07)

### 7. `status()` measured token savings ✅

- `inspect()` now stores `token_cost = _estimate_tokens(tools)` (measured, not registry estimate)
- `status()` sums stored costs for inspected servers NOT currently morphed
- Output: `Saved vs always-on: ~X tokens [based on N inspected schema(s)]`

### 8. README claims cleanup ✅

- Token numbers updated to measured values (~450 lean, ~1,700 forge)
- Added benchmark link note: `> Token numbers measured — see examples/benchmark.py`
- Removed "first MCP hub" overstatement
- Tool counts verified: 6 lean tools, 17 forge tools ✓

---

## Phase 4 — Agent Specialization & Minimal Profiles

**Core insight:** Agents running in production don't need dynamic discovery — they need exactly the tools for their task, nothing more. Token overhead should be a known constant, not a variable. An agent that always uses `read_file` + `web_search` should pay for exactly those two tools, not a general-purpose hub.

Pattern: **observe → profile → specialize → production**

| # | Item | Effort |
|---|------|--------|
| 9  | Tool usage tracking — persist call frequency per tool across sessions | small |
| 10 | Profile format — YAML/JSON declaring Chameleon tools + per-server tool lists | small |
| 11 | Profile-aware morph — auto-apply tool filter from active profile | medium |
| 12 | Profile generation — suggest minimal profile from observed usage | small |
| 13 | `chameleon-light` entry point — minimal server from a profile file | medium |

---

### 9. Tool usage tracking

**Why:** To know which tools an agent actually uses, you need data across sessions — not just within one.

`session["grown"]` already tracks calls per server. Extend to per-tool granularity and persist to `.chameleon_usage.json` alongside `.env`.

```json
{
  "@modelcontextprotocol/server-filesystem": {
    "read_file": 47,
    "write_file": 12,
    "list_directory": 8,
    "create_directory": 0,
    "delete_file": 0
  }
}
```

`status()` shows top tools per server. After N sessions, the data speaks for itself.

---

### 10. Profile format

A profile is a YAML file declaring exactly which tools an agent needs:

```yaml
# profiles/code_reviewer.yaml
chameleon_tools: [morph, shed, key]   # only 3 of 6 lean tools
servers:
  "@modelcontextprotocol/server-filesystem":
    tools: [read_file, list_directory]
  "@modelcontextprotocol/server-github":
    tools: [get_file_contents, list_pull_requests, get_pull_request]
```

Token cost for this profile: ~245 (Chameleon) + ~150 (5 tools) = **~395 tokens** — known before the session starts.

---

### 11. Profile-aware morph

When a profile is active, `morph("filesystem")` automatically applies `tools=["read_file", "list_directory"]` from the profile — no manual lean filter needed. The agent just calls `morph()` and gets exactly what the profile allows.

```python
CHAMELEON_PROFILE=profiles/code_reviewer.yaml chameleon-mcp
```

`morph()` output shows: `Morphed into 'filesystem' [profile: code_reviewer] — 2 tool(s) registered`

---

### 12. Profile generation from usage data

After N sessions with tracking enabled:

```
status()
→ Suggested profile (based on 12 sessions):
    filesystem: read_file (47 calls), write_file (12 calls), list_directory (8 calls)
    github: get_file_contents (31 calls), list_pull_requests (9 calls)
    Unused: create_directory, delete_file, move_file (0 calls each)
    → Lean morph would save ~620 tokens/request vs full morph

  profile("my_agent")   ← saves suggested profile to profiles/my_agent.yaml
```

---

### 13. `chameleon-light` entry point

A minimal server that reads a profile and exposes only what's declared:

```json
{
  "mcpServers": {
    "agent": {
      "command": "chameleon-light",
      "args": ["--profile", "profiles/code_reviewer.yaml"]
    }
  }
}
```

Token overhead: as low as **200–400 tokens** depending on the profile. Fixed, predictable, auditable.

The permission boundary is structural — a code review agent with this profile physically cannot call `delete_file` or `send_email` because those tools are never registered.

---

## What to defer

- URI template resource proxying (`file:///{path}`) — complex parameter binding, low adoption
- `resources/subscribe` change notifications — very few servers implement this
- Multi-turn prompt message structure — v2 of prompt proxying
- Blocking spawns from untrusted sources (vs warning) — too disruptive for current users
- WebSocket resource/prompt support — negligible current usage

---

## Critical files summary

| File | Changes |
|------|---------|
| `chameleon_mcp/constants.py` | `TIMEOUT_PROMPT_LIST`, trust tier sets |
| `chameleon_mcp/transport.py` | `list_prompts()`, `get_prompt()`, `_validate_install_cmd()` |
| `chameleon_mcp/morph.py` | `_register_proxy_resources()`, `_register_proxy_prompts()`, extend `_do_shed()` |
| `chameleon_mcp/tools.py` | morph() + shed() resource/prompt blocks, trust warning, cred warning, provenance |
| `chameleon_mcp/session.py` | `morphed_resources`, `morphed_prompts` keys |
| `server.py` | re-export new functions |
| `examples/benchmark.py` | new — reproducible token/latency measurements |
| `docs/benchmarks.md` | new — benchmark methodology + reference output |
| `docs/compatibility.md` | new — client matrix + manual test protocol |
| `README.md` | claims cleanup, benchmark link |
| `tests/test_morph.py` | ~13 new tests for resources + prompts |
| `tests/test_transports.py` | ~4 new tests for install command validation |
| `tests/test_tools.py` | ~3 new tests for credential warning |
| `tests/test_notifications.py` | new — notification call count tests |
