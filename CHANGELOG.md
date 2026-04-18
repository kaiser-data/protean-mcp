# Changelog

All notable changes to this project are documented here.

---

## [0.9.0] — 2026-04-12

### Added
- **`source=` parameter on `shapeshift()`** — `"local"` forces npx/uvx install (no Smithery key); `"smithery"` forces HTTP; `"official"` requires verified registry listing; `"auto"` (default) keeps current behavior
- **`shiftback(uninstall=True)`** — optionally uninstalls the locally installed package; uvx packages fully removed (`uv tool uninstall`), npx cache auto-expires
- **`KITSUNE_TRUST` env var** — set `"community"` to permanently bypass the community/local confirmation gate for trusted users and agents (`key("KITSUNE_TRUST", "community")`)
- **Credential status in `search()` results** — each row now shows `✅ ready` or `✗ needs API_KEY`
- **`inspect()` next-step CTA** — ends with `Next: key("VAR", "...") then shapeshift("id")` or `Next: shapeshift("id")` based on credential state
- **Lean hint after `shapeshift()`** — servers with >4 tools loaded without a filter show `💡 N tools loaded (~X tokens). For lean mounting: shapeshift("id", tools=[...])`
- **First-run onboarding in `status()`** — clean sessions show a 5-step guide with example flow
- **Registry failure reporting in `search()`** — timed-out registries shown as `⚠️ Skipped: name (timeout)` so partial results are visible

### Fixed
- **Credential check before `_do_shed()`** — missing credentials no longer drop your active form before returning the error
- **`bust_cache(server_id)` now works** — cache uses `(id, source_preference)` tuple keys; old `pop(str)` silently missed every entry
- **`source="official"` gate ordering** — official-source check fires before the trust gate, giving the right error for non-official servers
- **Pool path `current_form_local_install` leak** — pool shapeshift clears local install record so stale data can't trigger `uninstall=True` on the wrong package

### Changed
- `shapeshift()` pool-path and registry-path share a single `_commit_shapeshift()` helper — ~70 lines of duplication removed
- `_credentials_ready()` calls `_to_env_var(k)` once per key instead of three times
- `MultiRegistry._reg_names` precomputed at init instead of on every `search()` call

---

## [0.8.5] — 2026-04-11

### Fixed
- **Circular import** between `registry.py` and `official_registry.py` — `_registry` is now
  a lazy proxy; `MultiRegistry()` is deferred until first use
- **Ruff lint** — 64 errors resolved (import ordering, unused vars, SIM105, B023, UP046);
  CI pipeline is now fully green on Python 3.12 and 3.13

### Added
- Codecov coverage reporting (badge in README, uploads on every CI run)
- Automated GitHub Releases with CHANGELOG excerpt on tag push
- Glama registry listing (`glama.json`)
- Dependabot for weekly pip + GitHub Actions updates
- SECURITY.md and PR template

---

## [0.8.2] — 2026-04-11

### Added
- npm wrapper package — `npx kitsune-mcp` delegates to `uvx kitsune-mcp` (Python)
- Official MCP registry listing (`server.json` for `mcp-publisher`)
- `mcp-name` ownership tag in README for registry verification

---

## [0.8.1] — 2026-04-11

### Fixed
- **Smithery transport rewritten** — replaced dead `server.smithery.ai/{name}/mcp?config=b64` URL
  with the new Smithery Connect API: namespace → service token → connection upsert →
  `api.smithery.ai/connect/{ns}/{id}/mcp`. Fixes 400 "Server configuration is incomplete"
  and "Invalid token" errors from `run.tools`.
- **Registry** now reads `deploymentUrl` from Smithery API response instead of reconstructing stale URLs
- **`_resolve_config`** always writes all credential keys (`None` → JSON `null`) so Smithery's
  schema validator sees all expected keys even when optional vars are unset

### Changed
- `morph.py` → `shapeshift.py` (rename complete; `morph.py` deleted)
- Session keys: `morphed_tools/resources/prompts` → `shapeshift_tools/resources/prompts`
- `.chameleon` directory references → `.kitsune` in `credentials.py`, `session.py`, `transport.py`
- Docker label: `chameleon-mcp=1` → `kitsune-mcp=1`

---

## [0.8.0] — 2026-04-10

### Breaking Changes
- **Package renamed** `protean-mcp` → `kitsune-mcp` — update `pip install` and client configs
- **Package directory renamed** `chameleon_mcp/` → `kitsune_mcp/` — update any direct imports
- **Env var renamed** `CHAMELEON_TOOLS` → `KITSUNE_TOOLS` — update any custom tool filters
- **FastMCP server name** `"protean"` → `"kitsune"` — affects MCP client display name

### Deprecated (remove in v0.9)
- `protean-mcp`, `protean-forge` executables (kept as aliases)
- `chameleon-mcp`, `chameleon-forge` executables (kept as aliases)

### Migration
```bash
pip install kitsune-mcp
# update mcp.json: "command": "kitsune-mcp"
# update env: KITSUNE_TOOLS=... (was CHAMELEON_TOOLS)
```

---

## [0.7.3] — 2026-04-08

### Fixed
- `status()` output header: "CHAMELEON MCP STATUS" → "KITSUNE MCP STATUS"

---

## [0.7.2] — 2026-04-08

### Fixed
- README: absolute image URLs so logo and diagrams render on PyPI

---

## [0.7.1] — 2026-04-08

### Changed
- New logo (`logo_kitsune-mcp.png`) replacing placeholder SVG
- README: removed "a new way" framing; architecture diagrams cleaned of chameleon references
- `docs/architecture.svg`: removed 🦎 emoji from Kitsune MCP label
- `docs/architecture-forge.svg`: "chameleon-forge" → "kitsune-forge"

---

## [0.7.0] — 2026-04-08

### Breaking Changes

- **`morph()` renamed to `receive()`** — update any prompts or scripts that call `morph(...)`
- **`shed()` renamed to `cast_off()`** — update any prompts or scripts that call `shed()`
- **Package renamed from `chameleon-mcp` to `kitsune-mcp`** — update `pip install` and `pyproject.toml` references
- **Executables renamed**: `chameleon-mcp` → `kitsune-mcp`, `chameleon-forge` → `kitsune-forge`

### Migration Guide

| Before | After |
|---|---|
| `pip install chameleon-mcp` | `pip install kitsune-mcp` |
| `"command": "chameleon-mcp"` | `"command": "kitsune-mcp"` |
| `receive("exa")` | `receive("exa")` ← no change |
| `morph("exa")` | `receive("exa")` |
| `shed()` | `cast_off()` |

**Deprecated executables** (`chameleon-mcp`, `chameleon-forge`) are kept as aliases in v0.7.x for backward compatibility and will be removed in v0.8.0.

### Added
- `kitsune-mcp` and `kitsune-forge` as primary entry point executables
- `chameleon-mcp` and `chameleon-forge` kept as deprecated backward-compat aliases

### Changed
- MCP server display name: `"chameleon"` → `"protean"`
- `pyproject.toml` keywords: removed `"smithery"`, added `"mcp-registry"`
- Package description updated to reflect 7-registry architecture

---

## [0.6.2] — 2026-04-08

### Fixed
- `receive()` cold-start: prefer registry results with cached tool schemas over those without (fixes Exa cold-start failure)
- Live `tools/list` HTTP fetch fallback when registry cache is cold
- Smithery URL format: `/mcp` suffix + `api_key` query param (was using wrong format)
- Doubled Smithery URL when `srv.url` was already a full URL
- Pool staleness: auto-evict subprocesses when `.env` changes mid-session

---

## [0.6.1] — 2026-04-07

### Added
- Frictionless credentials: `.env` auto-reload without restart (tracks mtime changes)
- `call()` is mount-aware: `server_id` optional after `receive()`
- `call()` added to lean profile (7 tools total)
- WebSocket transport support (`ws://`, `wss://`)

---

## [0.6.0] — 2026-04-07

### Added
- `receive()` proxies resources + prompts in addition to tools
- Install command validation (shell injection and path traversal blocked)
- Trust tier warnings in `receive()` output
- Credential warnings at mount-time (not just at `call()`-time)
- `examples/benchmark.py` — reproducible token overhead measurement
- Notification compatibility testing
- Provenance shown in all `search()`/`inspect()`/`receive()`/`call()` output

---

## [0.5.9] — 2026-04-06

### Added
- Refactored into `kitsune_mcp/` package structure
- `OfficialMCPRegistry` — seeds from `modelcontextprotocol/servers` GitHub repo
- `inspect()` stores measured `token_cost` from actual tool schemas
- `status()` sums measured costs for inspected-but-not-mounted servers
- Per-server trust tier tracking

### Fixed
- Registry fan-out priority: official > mcpregistry > glama > github > smithery > npm
- PyPI registry is opt-in only (not in default fan-out — too slow)
