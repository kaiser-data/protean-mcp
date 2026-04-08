<div align="center">
  <img src="https://raw.githubusercontent.com/kaiser-data/protean-mcp/main/logo_protean-mcp.png" alt="Protean MCP" width="160" />
  <h1>🌊 Protean MCP</h1>
  <p><strong>The shape-shifting MCP hub — mount into any server at runtime.<br/>Fluid. Adaptive. Built for agents that change form.</strong></p>
</div>

[![PyPI](https://img.shields.io/pypi/v/protean-mcp?color=blue)](https://pypi.org/project/protean-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/protean-mcp)](https://pypi.org/project/protean-mcp/)
[![CI](https://github.com/kaiser-data/protean-mcp/actions/workflows/test.yml/badge.svg)](https://github.com/kaiser-data/protean-mcp/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Smithery](https://smithery.ai/badge/@kaiser-data/protean-mcp)](https://smithery.ai/server/@kaiser-data/protean-mcp)

---

## What Protean MCP does

MCP servers are typically configured at startup — all tools loaded forever, restart required for any change. Protean MCP takes a different approach.

**One entry in your config. Any server, on demand, at runtime.**

```
search("web scraping")                            # discover
mount("@modelcontextprotocol/server-puppeteer")   # inject tools live — no restart
puppeteer_navigate(url="https://example.com")     # call them natively
unmount()                                            # clean exit
```

`mount()` registers a server's tools directly via FastMCP's live API — no wrapper, no indirection, no config edit. `unmount()` removes them cleanly. The whole session costs **7 tools and ~650 tokens overhead** ([measured](examples/benchmark.py)).

Need only specific tools? Lean mount keeps overhead surgical:
```
mount("@modelcontextprotocol/server-filesystem", tools=["read_file", "write_file"])
# only 2 tools appear instead of 10
```

---

## Built for two audiences

### Adaptive agents

An agent that loads all tools upfront burns tokens and flexibility. An agent that mounts on demand stays lean and adaptable:

- `mount()` switches the entire capability set in one call — ~650 tokens, no restart
- Acquire a tool for the current task, unmount it, acquire the next
- Chain across multiple servers in one session without touching config
- `mount(server_id, tools=[...])` for surgical selection — only the tools actually needed

Protean MCP is designed around the token budget of a real agent loop.

### MCP developers

Beyond MCP Inspector's basic schema viewer, Protean MCP gives you a full development workflow inside your actual AI client:

| Need | Tool |
|---|---|
| Explore a server's tools and schemas | `inspect(server_id)` |
| Quality-score your server end-to-end | `test(server_id)` → score 0–100 |
| Benchmark tool latency | `bench(server_id, tool, args)` → p50, p95, min, max |
| Prototype endpoint-backed tools live | `craft(name, description, params, url)` |
| Test inside real Claude/Cursor workflows | `mount()` → call tools natively → `unmount()` |
| Compare two servers side by side | mount one, test, unmount, mount the other |

No separate web UI. No isolated test environment. Test how your server actually behaves when an AI uses it.

---

## Two modes

| | `protean-mcp` | `protean-forge` |
|---|---|---|
| **Purpose** | Adaptive agents, everyday mounting | MCP evaluation, benchmarking, crafting |
| **Tools** | 7 (mount, unmount, search, inspect, call, key, status) | All 17 |
| **Token overhead** | ~650 tokens | ~1,700 tokens |
| **Use when** | Agents mounting per task, minimal token budget | Discovering, testing, benchmarking, prototyping |

> Token numbers are measured from actual registered schemas — see [examples/benchmark.py](examples/benchmark.py).

Both modes from the same package:

```json
{ "command": "protean-mcp" }                        ← lean (default)
{ "command": "protean-forge" }                      ← full suite
{ "command": "protean-mcp",
  "env": { "CHAMELEON_TOOLS": "mount,unmount,key" } }    ← custom
```

---

## How It Fits Together

<div align="center">
  <img src="https://raw.githubusercontent.com/kaiser-data/protean-mcp/main/docs/architecture.svg" alt="Protean MCP — lean profile" width="700"/>
</div>

`mount()` injects tools directly at runtime via FastMCP's live API. Token overhead stays flat regardless of how many servers you explore.

Need the full evaluation suite? `protean-forge` adds execution, connection management, benchmarking, and tool crafting:

<div align="center">
  <img src="https://raw.githubusercontent.com/kaiser-data/protean-mcp/main/docs/architecture-forge.svg" alt="Protean Forge — extended suite" width="700"/>
</div>

---

## Quick Start

```bash
pip install protean-mcp
```

Add to your MCP client config — **once, globally**:

```json
{
  "mcpServers": {
    "protean": {
      "command": "protean-mcp"
    }
  }
}
```

Works with Claude Desktop, Claude Code, Cursor, Cline, OpenClaw, Continue.dev, Zed, and any MCP-compatible client. No API keys needed.

| Client | Global config file |
|---|---|
| Claude Desktop (macOS) | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Claude Desktop (Windows) | `%APPDATA%\Claude\claude_desktop_config.json` |
| Claude Code | `~/.claude/mcp.json` |
| Cursor / Windsurf | `~/.cursor/mcp.json` |
| Cline / Continue.dev | VS Code settings / `~/.continue/config.json` |
| OpenClaw | MCP config in OpenClaw settings |

---

## Server Sources

Protean MCP searches across multiple registries — no single one required.

| Registry | Auth | `registry=` value |
|---|---|---|
| [modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers) | None | `official` |
| [registry.modelcontextprotocol.io](https://registry.modelcontextprotocol.io) | None | `mcpregistry` |
| [Glama](https://glama.ai/mcp/servers) | None | `glama` |
| [npm](https://npmjs.com) | None | `npm` |
| [PyPI](https://pypi.org) | None | `pypi` |
| GitHub repos | None | `github:owner/repo` |
| [Smithery](https://smithery.ai) | Free API key | `smithery` |

Default `search()` fans out across all no-auth registries automatically. Add a `SMITHERY_API_KEY` to extend discovery with Smithery's hosted server catalog (HTTP servers, no local install required).

---

## How It Works

### The proxy model

Protean MCP is a **dynamic MCP proxy**. It sits between your AI client and any number of other MCP servers, connecting to them on demand:

```
Your AI client
    │
    ▼
Protean MCP          ← the one entry in your config
    │
    ├── (on mount) ──► filesystem server   (spawned subprocess)
    ├── (on mount) ──► brave-search server (spawned subprocess)
    └── (on mount) ──► remote HTTP server  (HTTP+SSE connection)
```

**Nothing is copied.** When you call a mounted tool, Protean MCP forwards the call to the original server via JSON-RPC and returns the result. The server's logic always runs on the server — Protean MCP only relays the schema and the call.

### What mount() does, step by step

1. **Connects** to the target server via the right transport (stdio subprocess, HTTP, WebSocket)
2. **Handshakes** — sends MCP `initialize` / `notifications/initialized`
3. **Fetches** `tools/list`, `resources/list`, `prompts/list` from the server
4. **Registers** each tool as a native FastMCP tool — a proxy closure with the exact signature from the schema
5. **Notifies** the AI client (`notifications/tools/list_changed`) so the new tools appear immediately

The AI sees `read_file`, `write_file`, `list_directory` as if they were always there. There's no wrapper or `call_tool("filesystem", ...)` indirection — the tools are first-class.

`unmount()` reverses all of it: deregisters the proxy closures, clears resources and prompts, notifies the client.

### Resources and prompts

`mount()` proxies all three MCP primitives, not just tools:

| Primitive | What gets proxied |
|---|---|
| **Tools** | Every tool from `tools/list`, registered with its exact parameter schema |
| **Resources** | Static resources from `resources/list` — readable via the MCP resources API |
| **Prompts** | Every prompt from `prompts/list`, with its argument signature |

Template URIs (e.g. `file:///{path}`) are skipped — they require parameter binding that adds complexity with little practical gain. Everything else is proxied.

### Transport is automatic

| Server source | How it runs |
|---|---|
| npm package | `npx <package>` — spawned locally |
| pip package | `uvx <package>` — spawned locally |
| GitHub repo | `npx github:user/repo` or `uvx --from git+https://...` |
| Docker image | `docker run --rm -i --memory 512m <image>` |
| Smithery hosted | HTTP+SSE (requires `SMITHERY_API_KEY`) |
| WebSocket server | `ws://` / `wss://` |

### Why inspect() before mount()

`inspect()` connects to the server and fetches its schemas — but does **not** register anything. Zero tools added to context, zero tokens consumed by the AI.

Use it to:
- See exact parameter names and types before committing
- Check credential requirements upfront (avoid a cryptic error mid-task)
- Get the measured token cost of the mount so you can budget
- Verify the server actually starts and responds before a live session

```
inspect("mcp-server-brave-search")
# → CREDENTIALS
# →   ✗ missing  BRAVE_API_KEY — Brave Search API key
# →   Add to .env:  BRAVE_API_KEY=your-value
# → Token cost: ~99 tokens (measured)

# Add the key to .env — picked up immediately, no restart needed
# Then mount and use in the same session:
mount("mcp-server-brave-search")
call("brave_web_search", arguments={"query": "MCP protocol 2025"})
```

---

## Security

Protean MCP introduces a trust model for servers you haven't personally audited.

### Trust tiers

Every `mount()`, `call()`, and `connect()` result shows where the server comes from:

| Tier | Sources | Indicator |
|---|---|---|
| High | `official` (modelcontextprotocol/servers) | `✓ Source: official` |
| Medium | `mcpregistry`, `glama`, `smithery` | `✓ Source: smithery` |
| Community | `npm`, `pypi`, `github` | `⚠️ Source: npm (community — not verified)` |

### Install command validation

Before spawning any subprocess, Protean MCP validates the executable name:
- Blocks shell metacharacters (`&`, `;`, `|`, `` ` ``, `$`) — prevents injection via a crafted server ID
- Blocks path traversal (`../`) — prevents escaping to arbitrary binaries

Arguments are passed directly to `asyncio.create_subprocess_exec` (never a shell), so they are not subject to shell interpretation.

### Credential warnings

`mount()` probes tool descriptions for unreferenced environment variable patterns. If a tool mentions `BRAVE_API_KEY` and that variable isn't set, you get a warning immediately — before you call anything:

```
⚠️  Credentials may be required — add to .env:
  BRAVE_API_KEY=your-value
  Or: key("BRAVE_API_KEY", "your-value")
```

### Process isolation and sandboxing

- stdio servers run as separate OS processes — no shared memory with Protean MCP
- Docker servers run with `--rm -i --memory 512m --label protean-mcp=1`
- `fetch()` blocks private IPs, loopback, and non-HTTPS URLs (SSRF protection)
- The process pool has a hard cap of 10 concurrent processes and evicts idle ones after 1 hour

---

## What You Can Access

One `protean-mcp` entry unlocks any of these on demand — no config changes, no restart:

| Category | Servers | Key needed | Lean tokens |
|---|---|---|---|
| **Web search** | Brave Search, Exa, Linkup, Parallel | Free API keys | ~150–993 |
| **Web scraping** | Firecrawl, ScrapeGraph AI | Free tiers | ~400 (lean) |
| **Code & repos** | GitHub (official, 26 tools) | Free GitHub token | ~500 (lean) |
| **Productivity** | Notion, Linear, Slack | Free workspace keys | ~400 (lean) |
| **Google** | Maps, Calendar, Gmail, Drive | Free GCP key / OAuth | varies |
| **Memory** | Mem0, knowledge graphs | Free tiers | ~300 |
| **No key required** | Filesystem, Git, weather, Yahoo Finance | — | ~300–1,000 |

The same pattern works for all of them:
```
mount("brave")                                    # web search in 2 tools
call("brave_web_search", arguments={"query": "…"})

mount("firecrawl-mcp", tools=["scrape","search"]) # scraping, lean (2 of 9 tools)
call("scrape", arguments={"url": "https://…"})

mount("@modelcontextprotocol/server-github", tools=["create_issue","search_repositories"])
call("create_issue", arguments={"owner": "…", "repo": "…", "title": "…"})
```

**Token cost scales with what you load**, not what exists. A 26-tool GitHub server costs ~500 tokens if you only mount 3 tools. See [.env.example](.env.example) for the full key catalog with lean mount hints.

### Security note on `.env`

Protean MCP re-reads `.env` on every call — which means adding a key instantly activates it. That convenience comes with a responsibility: **`.env` is the single place all your API keys live**. A few practices worth following:

- Add `.env` to `.gitignore` — never commit real keys
- Use project-level `.env` for project-specific keys; `~/.chameleon/.env` for personal global keys
- Prefer minimal OAuth scopes and fine-grained tokens (e.g. GitHub fine-grained tokens with per-repo permissions)
- Rotate keys that get exposed; Protean MCP picks up the new value immediately without restart

---

## Why Not Just X?

**"Can't I just add more servers to `mcp.json`?"** — Every configured server starts at launch and exposes all tools constantly. You can't add or remove mid-session without a restart. With 5+ servers you're burning thousands of tokens on every request for tools rarely needed. Protean MCP keeps the tool list minimal — mount what you need, unmount it when done.

**"What about MCP Inspector?"** — MCP Inspector is a standalone web UI that connects to one server and lets you inspect schemas and call tools manually. It's useful for basic debugging but isolated from real AI workflows. Protean MCP tests servers inside actual Claude or Cursor sessions — how an AI really uses them. It adds `test()` scoring, `bench()` latency numbers, side-by-side server comparison, and `craft()` for live endpoint prototyping. It also discovers and installs servers on demand; Inspector requires you to already have one running.

**"What about `mcp-dynamic-proxy`?"** — It hides tools behind `call_tool("brave", "web_search", {...})` — always a wrapper. After `mount("mcp-server-brave-search")`, Protean MCP gives you a real native `brave_web_search` with the actual schema. It also can't discover or install packages at runtime.

**"Can FastMCP do this natively?"**

| | FastMCP native | Protean MCP |
|---|:---:|:---:|
| Proxy a known HTTP/SSE server | ✅ | ✅ |
| Mount tools at runtime | ✅ (write code) | ✅ `mount()` |
| Search registries to discover servers | ❌ | ✅ npm · official · Glama · Smithery |
| Install npm / PyPI / GitHub packages on demand | ❌ | ✅ |
| Atomic shed — retract all morphed tools at once | ❌ | ✅ `unmount()` |
| Persistent stdio process pool | ❌ | ✅ |
| Zero boilerplate — works after `pip install` | ❌ | ✅ |

---

## Configuration

### Minimal (no API keys)

```json
{
  "mcpServers": {
    "chameleon": { "command": "protean-mcp" }
  }
}
```

### Optional integrations

```json
{
  "mcpServers": {
    "chameleon": {
      "command": "protean-mcp",
      "env": { "SMITHERY_API_KEY": "your-key" }
    }
  }
}
```

Get a free key at [smithery.ai/account/api-keys](https://smithery.ai/account/api-keys). Without it, Protean MCP is fully functional via npm, PyPI, official registries, and GitHub.

**Frictionless credentials** — Protean MCP re-reads `.env` on every `inspect()`, `mount()`, and `call()`. Add a key mid-session and it takes effect immediately — no restart:

```
# .env (CWD, ~/.env, or ~/.chameleon/.env — all checked, CWD wins)
BRAVE_API_KEY=your-key
GITHUB_TOKEN=ghp_...
```

Or use `key()` to write to `.env` and activate in one step:

```
key("BRAVE_API_KEY", "your-key")   # writes to .env, active immediately
```

---

## All Tools

### `protean-mcp` — lean profile (7 tools, ~650 token overhead)

| Tool | Description |
|---|---|
| `mount(server_id, tools)` | Inject a server's tools live. `tools=[...]` for lean morph. |
| `unmount(release)` | Remove morphed tools. `release=True` kills the process immediately. |
| `search(query, registry)` | Search MCP servers across registries. |
| `inspect(server_id)` | Show tools, schemas, and live credential status (✓/✗ per key). |
| `call(tool_name, server_id, args)` | Call a tool. `server_id` optional when mounted — current form used. |
| `key(env_var, value)` | Save an API key to `.env` and load it immediately. |
| `status()` | Show current form, active connections (PID + RAM), token stats. |

### `protean-forge` — full suite (all 17 tools, ~1,700 token overhead)

Everything above, plus:

| Tool | Description |
|---|---|
| `call(tool_name, server_id, args)` | Already in lean profile — listed here for completeness. |
| `run(package, tool, args)` | Run from npm/pip directly. `uvx:pkg-name` for Python. |
| `auto(task, tool, args)` | Search → pick best server → call in one step. |
| `fetch(url, intent)` | Fetch a URL, return compressed text (~17x smaller than raw HTML). |
| `craft(name, description, params, url)` | Register a custom tool backed by your HTTP endpoint. `unmount()` removes it. |
| `connect(command, name)` | Start a persistent server. Accepts server_id or shell command. |
| `release(name)` | Kill a persistent connection by name. |
| `setup(name)` | Step-by-step setup wizard for a connected server. |
| `test(server_id, level)` | Quality-score a server 0–100. |
| `bench(server_id, tool, args)` | Benchmark tool latency — p50, p95, min, max. |
| `skill(qualified_name)` | Load a skill into context. Persisted across sessions. |

---

## Usage Examples

### Adaptive agent — multi-server session, zero config

```
# Task 1: read some files
mount("@modelcontextprotocol/server-filesystem", tools=["read_file"])
read_file(path="/tmp/data.csv")
unmount()

# Task 2: search the web
mount("mcp-server-brave-search")
brave_web_search(query="latest MCP servers 2025")
unmount()

# Task 3: run a git query
mount("@modelcontextprotocol/server-git", tools=["git_log"])
git_log(repo_path=".", max_count=5)
unmount()
# Three different servers. One session. Zero config edits.
```

### MCP developer workflow — test your server

```
# Evaluate your server before publishing
inspect("my-server")               # review schemas and credentials
test("my-server")                  # quality score 0–100
bench("my-server", "my_tool", {})  # p50, p95 latency

# Prototype a tool backed by your local endpoint
craft(
    name="my_tool",
    description="Calls my ranking service",
    params={"query": {"type": "string"}},
    url="http://localhost:8080/rank"
)
my_tool(query="test")   # call it natively inside Claude
unmount()
```

### Same-session usage with call()

After `mount()`, use `call()` immediately — no restart, no server_id needed:

```
mount("@modelcontextprotocol/server-filesystem")
# → "In this session: call('tool_name', arguments={...})"

call("list_directory", arguments={"path": "/Users/me/project"})
call("read_file", arguments={"path": "/Users/me/project/README.md"})
unmount()
```

### Search, mount, use, unmount

```
search("web search")
mount("mcp-server-brave-search")
key("BRAVE_API_KEY", "your-key")   # picked up immediately
call("brave_web_search", arguments={"query": "MCP protocol 2025"})
unmount()
```

### Persistent server with setup guidance

```
connect("uvx voice-mode", name="voice")
setup("voice")                      # shows missing env vars
key("DEEPGRAM_API_KEY", "your-key")
setup("voice")                      # confirms ready
mount("voice-mode")
speak(text="Hello from Protean MCP!")
unmount(release=True)                  # kills process, frees RAM
```

---

## Installation

```bash
pip install protean-mcp        # from PyPI
# or
git clone https://github.com/kaiser-data/protean-mcp && pip install -e .
```

**Requirements:** Python 3.12+ · `node`/`npx` (for npm servers) · `uvx` from [uv](https://github.com/astral-sh/uv) (for pip servers)

---

## Contributing

```bash
make dev     # install with dev dependencies
make test    # pytest
make lint    # ruff
```

Issues and PRs: [github.com/kaiser-data/protean-mcp](https://github.com/kaiser-data/protean-mcp)

---

*MIT License · Python 3.12+ · Built on [FastMCP](https://github.com/jlowin/fastmcp)*
