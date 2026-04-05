<div align="center">
  <img src="chameleon-logo.png" alt="Chameleon MCP" width="200" />
  <h1>🦎 Chameleon MCP</h1>
  <p><strong>The dynamic MCP hub — morph into any server at runtime.<br/>Built for adaptive agents and MCP developers alike.</strong></p>
</div>

[![PyPI](https://img.shields.io/pypi/v/chameleon-mcp?color=blue)](https://pypi.org/project/chameleon-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/chameleon-mcp)](https://pypi.org/project/chameleon-mcp/)
[![CI](https://github.com/kaiser-data/chameleon-mcp/actions/workflows/test.yml/badge.svg)](https://github.com/kaiser-data/chameleon-mcp/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Smithery](https://smithery.ai/badge/@kaiser-data/chameleon-mcp)](https://smithery.ai/server/@kaiser-data/chameleon-mcp)

---

## A new way to use MCP

MCP has so far been mostly static — configure servers at startup, all tools loaded forever, restart required for any change. Chameleon changes that.

**One entry in your config. Any server, on demand, at runtime.**

```
search("web scraping")                            # discover
morph("@modelcontextprotocol/server-puppeteer")   # inject tools live — no restart
puppeteer_navigate(url="https://example.com")     # call them natively
shed()                                            # clean exit
```

`morph()` registers a server's tools directly via FastMCP's live API — no wrapper, no indirection, no config edit. `shed()` removes them cleanly. The whole session costs **6 tools and ~240 tokens overhead**.

Need only specific tools? Lean morph keeps overhead surgical:
```
morph("@modelcontextprotocol/server-filesystem", tools=["read_file", "write_file"])
# only 2 tools appear instead of 10
```

---

## Built for two audiences

### Adaptive agents

An agent that loads all tools upfront burns tokens and flexibility. An agent that morphs on demand stays lean and adaptable:

- `morph()` switches the entire capability set in one call — ~240 tokens, no restart
- Acquire a tool for the current task, shed it, acquire the next
- Chain across multiple servers in one session without touching config
- `morph(server_id, tools=[...])` for surgical selection — only the tools actually needed

This is the first MCP hub designed around the token budget of a real agent loop.

### MCP developers

Beyond MCP Inspector's basic schema viewer, Chameleon gives you a full development workflow inside your actual AI client:

| Need | Tool |
|---|---|
| Explore a server's tools and schemas | `inspect(server_id)` |
| Quality-score your server end-to-end | `test(server_id)` → score 0–100 |
| Benchmark tool latency | `bench(server_id, tool, args)` → p50, p95, min, max |
| Prototype endpoint-backed tools live | `craft(name, description, params, url)` |
| Test inside real Claude/Cursor workflows | `morph()` → call tools natively → `shed()` |
| Compare two servers side by side | morph one, test, shed, morph the other |

No separate web UI. No isolated test environment. Test how your server actually behaves when an AI uses it.

---

## Two modes

| | `chameleon-mcp` | `chameleon-forge` |
|---|---|---|
| **Purpose** | Adaptive agents, everyday morphing | MCP evaluation, benchmarking, crafting |
| **Tools** | 6 (morph, shed, search, inspect, key, status) | All 17 |
| **Token overhead** | ~240 tokens | ~825 tokens |
| **Use when** | Agents morphing per task, minimal token budget | Discovering, testing, benchmarking, prototyping |

Both modes from the same package:

```json
{ "command": "chameleon-mcp" }                        ← lean (default)
{ "command": "chameleon-forge" }                      ← full suite
{ "command": "chameleon-mcp",
  "env": { "CHAMELEON_TOOLS": "morph,shed,key" } }    ← custom
```

---

## How It Fits Together

<div align="center">
  <img src="docs/architecture.svg" alt="Chameleon MCP — lean profile" width="700"/>
</div>

`morph()` injects tools directly at runtime via FastMCP's live API. Token overhead stays flat regardless of how many servers you explore.

Need the full evaluation suite? `chameleon-forge` adds execution, connection management, benchmarking, and tool crafting:

<div align="center">
  <img src="docs/architecture-forge.svg" alt="Chameleon Forge — extended suite" width="700"/>
</div>

---

## Quick Start

```bash
pip install chameleon-mcp
```

Add to your MCP client config — **once, globally**:

```json
{
  "mcpServers": {
    "chameleon": {
      "command": "chameleon-mcp"
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

Chameleon searches across multiple registries — no single one required.

| Registry | Auth | `registry=` value |
|---|---|---|
| [modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers) | None | `official` |
| [registry.modelcontextprotocol.io](https://registry.modelcontextprotocol.io) | None | `mcpregistry` |
| [Glama](https://glama.ai/mcp/servers) | None | `glama` |
| [npm](https://npmjs.com) | None | `npm` |
| [PyPI](https://pypi.org) | None | `pypi` |
| GitHub repos | None | `github:owner/repo` |
| [Smithery](https://smithery.ai) | Free API key | `smithery` |

Default `search()` fans out across all no-auth registries automatically. Add a `SMITHERY_API_KEY` to include Smithery's 3,000+ verified servers.

---

## How It Works

Traditional MCP hubs route calls through a wrapper: `hub.call("exa", "web_search", args)`. Chameleon goes further — it **becomes** the server:

```
Before morph():
  Claude → Chameleon (search, inspect, morph, shed, ...)

After morph("@modelcontextprotocol/server-filesystem"):
  Claude → Chameleon (..., read_file, write_file, list_directory, ...)
```

The morphed tools appear natively — no extra prompt overhead, no indirection.

**Transport is automatic:**

| Server source | How it runs |
|---|---|
| npm package | `npx <package>` — spawned locally |
| pip package | `uvx <package>` — spawned locally |
| GitHub repo | `npx github:user/repo` or `uvx --from git+https://...` |
| Docker image | `docker run --rm -i --memory 512m <image>` |
| Smithery remote | HTTP+SSE via `server.smithery.ai` (requires API key) |
| WebSocket server | `ws://` / `wss://` |

---

## Why Not Just X?

**"Can't I just add more servers to `mcp.json`?"** — Every configured server starts at launch and exposes all tools constantly. You can't add or remove mid-session without a restart. With 5+ servers you're burning thousands of tokens on every request for tools rarely needed. Chameleon keeps the tool list minimal — morph in what you need, shed it when done.

**"What about MCP Inspector?"** — MCP Inspector is a standalone web UI that connects to one server and lets you inspect schemas and call tools manually. It's useful for basic debugging but isolated from real AI workflows. Chameleon tests servers inside actual Claude or Cursor sessions — how an AI really uses them. It adds `test()` scoring, `bench()` latency numbers, side-by-side server comparison, and `craft()` for live endpoint prototyping. It also discovers and installs servers on demand; Inspector requires you to already have one running.

**"What about `mcp-dynamic-proxy`?"** — It hides tools behind `call_tool("brave", "web_search", {...})` — always a wrapper. After `morph("mcp-server-brave-search")`, Chameleon gives you a real native `brave_web_search` with the actual schema. It also can't discover or install packages at runtime.

**"Can FastMCP do this natively?"**

| | FastMCP native | Chameleon |
|---|:---:|:---:|
| Proxy a known HTTP/SSE server | ✅ | ✅ |
| Mount tools at runtime | ✅ (write code) | ✅ `morph()` |
| Search registries to discover servers | ❌ | ✅ npm · official · Glama · Smithery |
| Install npm / PyPI / GitHub packages on demand | ❌ | ✅ |
| Atomic shed — retract all morphed tools at once | ❌ | ✅ `shed()` |
| Persistent stdio process pool | ❌ | ✅ |
| Zero boilerplate — works after `pip install` | ❌ | ✅ |

---

## Configuration

### Minimal (no API keys)

```json
{
  "mcpServers": {
    "chameleon": { "command": "chameleon-mcp" }
  }
}
```

### With Smithery (optional)

```json
{
  "mcpServers": {
    "chameleon": {
      "command": "chameleon-mcp",
      "env": { "SMITHERY_API_KEY": "your-key" }
    }
  }
}
```

Get a free key at [smithery.ai/account/api-keys](https://smithery.ai/account/api-keys). Without it, Chameleon is fully functional via npm, PyPI, official registries, and GitHub.

**Per-session API keys** — use `key()` instead of pre-configuring everything:

```
key("BRAVE_API_KEY", "your-key")   # saved to .env, auto-loaded next session
```

---

## All Tools

### `chameleon-mcp` — lean profile (6 tools, ~240 token overhead)

| Tool | Description |
|---|---|
| `morph(server_id, tools)` | Inject a server's tools live. `tools=[...]` for lean morph. |
| `shed(release)` | Remove morphed tools. `release=True` kills the process immediately. |
| `search(query, registry)` | Search MCP servers across registries. |
| `inspect(server_id)` | Show server tools, schemas, and required credentials. |
| `key(env_var, value)` | Save an API key to `.env` and load it immediately. |
| `status()` | Show current form, active connections (PID + RAM), token stats. |

### `chameleon-forge` — full suite (all 17 tools, ~825 token overhead)

Everything above, plus:

| Tool | Description |
|---|---|
| `call(server_id, tool, args)` | One-shot tool call — no morph needed. |
| `run(package, tool, args)` | Run from npm/pip directly. `uvx:pkg-name` for Python. |
| `auto(task, tool, args)` | Search → pick best server → call in one step. |
| `fetch(url, intent)` | Fetch a URL, return compressed text (~17x smaller than raw HTML). |
| `craft(name, description, params, url)` | Register a custom tool backed by your HTTP endpoint. `shed()` removes it. |
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
morph("@modelcontextprotocol/server-filesystem", tools=["read_file"])
read_file(path="/tmp/data.csv")
shed()

# Task 2: search the web
morph("mcp-server-brave-search")
brave_web_search(query="latest MCP servers 2025")
shed()

# Task 3: run a git query
morph("@modelcontextprotocol/server-git", tools=["git_log"])
git_log(repo_path=".", max_count=5)
shed()
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
shed()
```

### Search, morph, use, shed

```
search("web search")
morph("mcp-server-brave-search")
key("BRAVE_API_KEY", "your-key")
brave_web_search(query="MCP protocol 2025")
shed()
```

### Persistent server with setup guidance

```
connect("uvx voice-mode", name="voice")
setup("voice")                      # shows missing env vars
key("DEEPGRAM_API_KEY", "your-key")
setup("voice")                      # confirms ready
morph("voice-mode")
speak(text="Hello from Chameleon!")
shed(release=True)                  # kills process, frees RAM
```

---

## Installation

```bash
pip install chameleon-mcp        # from PyPI
# or
git clone https://github.com/kaiser-data/chameleon-mcp && pip install -e .
```

**Requirements:** Python 3.12+ · `node`/`npx` (for npm servers) · `uvx` from [uv](https://github.com/astral-sh/uv) (for pip servers)

---

## Contributing

```bash
make dev     # install with dev dependencies
make test    # pytest
make lint    # ruff
```

Issues and PRs: [github.com/kaiser-data/chameleon-mcp](https://github.com/kaiser-data/chameleon-mcp)

---

*MIT License · Python 3.12+ · Built on [FastMCP](https://github.com/jlowin/fastmcp)*
