<div align="center">
  <img src="chameleon-logo.png" alt="Chameleon MCP" width="200" />
  <h1>🦎 Chameleon MCP</h1>
  <p><strong>Morph into any MCP server — live, no config, minimal tokens.</strong></p>
</div>

[![PyPI](https://img.shields.io/pypi/v/chameleon-mcp?color=blue)](https://pypi.org/project/chameleon-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/chameleon-mcp)](https://pypi.org/project/chameleon-mcp/)
[![CI](https://github.com/kaiser-data/chameleon-mcp/actions/workflows/test.yml/badge.svg)](https://github.com/kaiser-data/chameleon-mcp/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Smithery](https://smithery.ai/badge/@kaiser-data/chameleon-mcp)](https://smithery.ai/server/@kaiser-data/chameleon-mcp)

---

## The core idea

One server in your config. Become any other server on demand.

```
search("web scraping")                            # find it
morph("@modelcontextprotocol/server-puppeteer")   # inject its tools live — no restart
puppeteer_navigate(url="https://example.com")     # call them exactly like native tools
shed()                                            # clean exit
```

**6 tools. ~240 tokens overhead. Zero config edits.**

`morph()` registers a server's tools directly on Chameleon via FastMCP's live API. Claude sees `puppeteer_navigate` natively — no wrapper, no indirection. `shed()` removes them cleanly. The whole session costs less than having one extra server configured permanently.

Need only specific tools? Lean morph keeps token overhead surgical:
```
morph("@modelcontextprotocol/server-filesystem", tools=["read_file", "write_file"])
# only 2 tools appear instead of 10
```

---

## The Problem

There are thousands of MCP servers. Trying even one means: find it, figure out the install command, edit `mcp.json`, restart your client, use it for five minutes, then edit `mcp.json` again to remove it. One server. One at a time. Meanwhile every configured server sends its full tool list on **every single request** — 5 servers × 10 tools × ~250 tokens = 12,500 tokens burned before you've said a word.

So most people configure 2–3 servers once and never explore further.

---

## Two modes

| | `chameleon-mcp` | `chameleon-forge` |
|---|---|---|
| **Purpose** | Everyday morphing | Evaluation + crafting |
| **Tools** | 6 (morph, shed, search, inspect, key, status) | All 17 |
| **Token overhead** | ~240 tokens | ~825 tokens |
| **Use when** | You know what you want, just need to use it | Discovering, benchmarking, prototyping |

Both installed from the same package. Switch anytime with `CHAMELEON_TOOLS`:

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

One entry in your config. `morph()` injects a server's tools directly via FastMCP's live API — added and removed at runtime, not at startup. `shed()` cleans up. Token overhead stays flat regardless of how many servers you explore.

Need the full evaluation suite? `chameleon-forge` adds execution, connection management, benchmarking, and tool crafting:

<div align="center">
  <img src="docs/architecture-forge.svg" alt="Chameleon Forge — extended suite" width="700"/>
</div>

---

## Compatibility

Chameleon is a standard MCP server that speaks the [MCP protocol](https://modelcontextprotocol.io) over stdio. It works with **any AI client that supports MCP** — it is completely independent of which LLM or model backend you use.

### Supported AI clients

| Client | MCP support | Notes |
|--------|-------------|-------|
| [Claude Desktop](https://claude.ai/download) | ✅ Native | Add to `claude_desktop_config.json` |
| [Claude Code](https://github.com/anthropics/claude-code) | ✅ Native | Add to `.claude/mcp.json` |
| [Cursor](https://cursor.sh) | ✅ Native | Add to `.cursor/mcp.json` |
| [Continue.dev](https://continue.dev) | ✅ Native | Works with local Ollama models too |
| [Zed](https://zed.dev) | ✅ Native | Via MCP extension |
| [Open WebUI](https://openwebui.com) | ✅ Supported | Works with Ollama backend |
| Any custom agent | ✅ Via library | Use [`mcp`](https://pypi.org/project/mcp/) Python client or [`@modelcontextprotocol/sdk`](https://www.npmjs.com/package/@modelcontextprotocol/sdk) |

### What about Ollama, LM Studio, vLLM, and other local models?

Chameleon runs on the **tool side** of MCP, not the model side. It doesn't care which LLM is calling it.

- **Ollama** doesn't natively implement an MCP client, but [Continue.dev](https://continue.dev) + Ollama does — and Chameleon works with Continue.dev
- **LM Studio** has an OpenAI-compatible API; pair it with an MCP-capable client layer
- **vLLM / llama.cpp / any OpenAI-compatible server**: same — the client layer handles MCP, the model layer handles inference

If you're building a custom agent with Python, you can connect to Chameleon using the official [`mcp`](https://pypi.org/project/mcp/) library with any LLM backend:

```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Chameleon MCP with any LLM — Ollama, OpenAI, Anthropic, local model
server_params = StdioServerParameters(command="chameleon-mcp")
async with stdio_client(server_params) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
```

---

## Quick Start

### 1. Install

```bash
pip install chameleon-mcp
```

### 2. Add to your MCP client — once, globally

```json
{
  "mcpServers": {
    "chameleon": {
      "command": "chameleon-mcp"
    }
  }
}
```

That's it. No API keys needed. Works with Claude Desktop, Claude Code, Cursor, Continue.dev, Zed.

### 3. Use it

```
morph("@modelcontextprotocol/server-filesystem")
read_file(path="/tmp/notes.txt")
shed()
```

```
search("web scraping")
morph("mcp-server-puppeteer")
puppeteer_navigate(url="https://example.com")
shed()
```

Only need specific tools? Lean morph keeps token cost minimal:
```
morph("@modelcontextprotocol/server-filesystem", tools=["read_file", "write_file"])
```

### Want the full evaluation suite?

Use `chameleon-forge` for benchmarking, testing, and tool prototyping:

```json
{
  "mcpServers": {
    "chameleon": {
      "command": "chameleon-forge"
    }
  }
}
```

---

## Server Sources

Chameleon works with MCP servers from multiple sources — no single registry required.

### GitHub Repositories (recommended starting point)

Run any MCP server directly from a GitHub repository. This is ideal for:
- Official servers from the [`modelcontextprotocol`](https://github.com/modelcontextprotocol/servers) organization
- Community servers that haven't been published to a registry
- Your own servers under active development

```bash
# Via uvx (pip-based servers)
connect("uvx --from git+https://github.com/user/repo server-name", name="myserver")

# Via npx (npm-based servers, supports github: shorthand)
connect("npx github:user/repo", name="myserver")
```

The [official MCP servers repository](https://github.com/modelcontextprotocol/servers) contains reference implementations for filesystem, git, memory, databases, web search, and more — all runnable without a registry.

### npm Registry

Any npm package that follows the MCP server convention is supported natively:

```
morph("@modelcontextprotocol/server-filesystem")
morph("mcp-server-brave-search")
run("@modelcontextprotocol/server-memory", "create_entities", {...})
```

Search the npm registry without any authentication:
```
search("filesystem", registry="npm")
```

### Official MCP Registry (GitHub seed list)

The [modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers) repository contains the reference implementations — always the safest starting point:

```
search("filesystem", registry="official")
morph("@modelcontextprotocol/server-filesystem")
read_file(path="/tmp/notes.txt")
shed()
```

These servers are available instantly without any API key, and Chameleon keeps its list fresh with a 24-hour cache of the GitHub directory.

### Official MCP Protocol Registry

The [registry.modelcontextprotocol.io](https://registry.modelcontextprotocol.io) is the formal registry maintained by the MCP protocol team. Servers here have structured package metadata including exact install commands and required environment variables:

```
search("web search", registry="mcpregistry")
```

No API key required. Results include `source: mcpregistry` in search output.

### Glama Community Directory

[glama.ai](https://glama.ai/mcp/servers) is a large community directory of MCP servers with quality signals and credential schema data:

```
search("database", registry="glama")
```

No API key required. Only `required` environment variables become credentials — optional env vars are excluded.

### PyPI / pip Packages

Any pip-installable MCP server runs via `uvx`:

```
search("git", registry="pypi")
morph("mcp-server-git")
morph("mcp-server-sqlite")
run("uvx:mcp-server-time", "get_current_time", {})
```

### Smithery Registry (optional)

[Smithery](https://smithery.ai) is a curated registry of 3,000+ verified servers, including remotely hosted servers that run in the cloud without local installation.

To enable Smithery, add an API key (free at [smithery.ai/account/api-keys](https://smithery.ai/account/api-keys)):

```json
{
  "mcpServers": {
    "chameleon": {
      "command": "chameleon-mcp",
      "env": {
        "SMITHERY_API_KEY": "your-key-here"
      }
    }
  }
}
```

With Smithery enabled, `search()` includes verified registry results alongside npm results. Remote (cloud-hosted) servers can be called without any local installation.

**Without a Smithery key:** Chameleon is fully functional — you have access to the entire npm ecosystem, PyPI, and any GitHub repository. Smithery is a convenience layer, not a requirement.

---

## How It Works

### The morph pattern

Traditional MCP hubs route calls through a wrapper: `hub.call("exa", "web_search", args)`. Chameleon goes further — it **becomes** the server. After `morph()`, the server's tools are registered directly on Chameleon and callable by name with no extra layers.

```
Before morph():
  Claude → Chameleon (search, inspect, call, morph, shed, ...)

After morph("@modelcontextprotocol/server-filesystem"):
  Claude → Chameleon (search, inspect, call, morph, shed, ...,
                      read_file, write_file, list_directory, ...)
```

Your AI client sees the morphed tools exactly as if the server were configured directly. No prompt overhead, no tool-calling indirection.

### Transport selection

Chameleon picks the right transport automatically:

| Server source | Transport | How it runs |
|---|---|---|
| GitHub repo (npm) | Stdio | `npx github:user/repo` |
| GitHub repo (pip) | Stdio | `uvx --from git+https://github.com/...` |
| npm package | Stdio | Spawned locally via `npx` |
| pip package | Stdio | Spawned locally via `uvx` |
| Persistent server | Persistent Stdio | Long-lived process, reused across calls |
| Docker image | Docker (Persistent Stdio) | `docker run --rm -i --memory 512m <image>` — RAM-capped, easy to destroy |
| Smithery remote server | HTTP+SSE | Remote call via `server.smithery.ai` (requires API key) |

### Persistent connections

Some servers — audio pipelines, hardware interfaces, stateful services — cannot cold-start on every tool call. `connect()` starts the process once and keeps it in a pool. The same process handles all subsequent calls until you explicitly `release()` it.

---

## Why Not Just X?

### "Can't I just add more servers to `mcp.json`?"

Yes — but every configured server starts at launch and exposes all its tools constantly. With 5+ servers you're sending hundreds of tool definitions on every request, which hurts response quality and burns tokens on tools your AI rarely needs. You also can't add or remove a server mid-session without editing the config file and restarting your client.

Chameleon's tool list stays minimal. Morph in what you need, shed it when you're done.

### "What about `mcp-dynamic-proxy`?"

[mcp-dynamic-proxy](https://pypi.org/project/mcp-dynamic-proxy/) solves the context-bloat problem differently: it hides all tools behind 3 meta-tools (`list_servers`, `list_tools`, `call_tool`). The trade-off is that your AI must *always* route calls through the wrapper — it never gets a native `web_search` tool, only ever `call_tool("brave", "web_search", {...})`.

Chameleon's approach is different: `morph()` **injects real tools directly into the session**. After `morph("mcp-server-brave-search")`, the AI sees and calls `brave_web_search` natively, with the actual schema, exactly as if the server were configured directly.

Two other gaps in mcp-dynamic-proxy:
- **Static config** — server list is defined in a JSON file at startup; no runtime discovery
- **No installation** — assumes all servers are already installed; can't resolve npm/PyPI/GitHub packages on demand

### "Can FastMCP do this natively?"

FastMCP provides the right primitives — `mcp.add_tool()`, `mcp.remove_tool()`, `mcp.mount()`, `FastMCPProxy` — but not a finished product. You'd need to wire up the rest yourself:

| | FastMCP native | Chameleon |
|---|:---:|:---:|
| Proxy a known HTTP/SSE server | ✅ | ✅ |
| Mount another server's tools at runtime | ✅ (write code) | ✅ `morph()` |
| Search registries to discover servers | ❌ | ✅ npm + Smithery |
| Install npm / PyPI / GitHub packages on demand | ❌ | ✅ |
| Atomic shed — retract all morphed tools at once | ❌ | ✅ `shed()` |
| Persistent stdio process pool | ❌ | ✅ |
| Zero boilerplate — works after `pip install` | ❌ | ✅ |

You [can build a subset of this](https://dev.to/amartyadev/building-a-dynamic-mcp-proxy-server-in-python-16jf) on top of FastMCP's `mcp.mount()`, but you'll still need to add package installation, registry search, subprocess lifecycle management, and the morph/shed snapshot concept. Chameleon is that work, pre-built and packaged.

---

## Installation Options

### From PyPI

```bash
pip install chameleon-mcp
```

### From source

```bash
git clone https://github.com/kaiser-data/chameleon-mcp
cd chameleon-mcp
pip install -e .
```

### Requirements

- Python 3.12+
- `node` / `npx` — required to run npm-based servers locally
- `uvx` (from [uv](https://github.com/astral-sh/uv)) — required to run pip-based servers locally

---

## Configuration

### Where to put the config

Configure Chameleon **globally** so it's available in every project — you only need to do this once.

| Client | Global config file |
|---|---|
| Claude Desktop (macOS) | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Claude Desktop (Windows) | `%APPDATA%\Claude\claude_desktop_config.json` |
| Claude Code | `~/.claude/mcp.json` |
| Cursor | `~/.cursor/mcp.json` |
| Continue.dev | `~/.continue/config.json` |

For project-specific overrides, place `mcp.json` inside your project's `.claude/` folder — it takes precedence over the global config for that project only.

### Minimal (no API keys)

```json
{
  "mcpServers": {
    "chameleon": {
      "command": "chameleon-mcp"
    }
  }
}
```

Works with all npm packages, pip packages, and GitHub repositories.

### With Smithery (optional)

```json
{
  "mcpServers": {
    "chameleon": {
      "command": "chameleon-mcp",
      "env": {
        "SMITHERY_API_KEY": "your-smithery-key"
      }
    }
  }
}
```

### Environment variables

| Variable | Required | Description |
|---|---|---|
| `SMITHERY_API_KEY` | No | Access to Smithery-hosted and verified servers. Free at [smithery.ai/account/api-keys](https://smithery.ai/account/api-keys). |

### Managing API keys safely

MCP servers run as subprocesses launched by your AI client — they don't inherit your interactive shell environment. This means `~/.zshrc` exports alone won't reach Chameleon. Here's the recommended setup:

**Keys needed at Chameleon startup** (e.g. `SMITHERY_API_KEY`) go in the `env` block of your MCP config — this is the only reliable way to pass them to the subprocess.

**All other keys** are best kept in a `~/.secrets` file and sourced from `~/.zshrc`:

```bash
# ~/.secrets  (chmod 600 — never commit this file)
export SMITHERY_API_KEY="your-key"
export OPENAI_API_KEY="your-key"
export ANTHROPIC_API_KEY="your-key"
```

```bash
# ~/.zshrc
[ -f ~/.secrets ] && source ~/.secrets
```

Add a global gitignore so secrets never accidentally get committed:

```bash
echo '.secrets\n.env\n.envrc' >> ~/.gitignore_global
git config --global core.excludesfile ~/.gitignore_global
```

**Keys for individual MCP servers** (Brave, Exa, etc.) don't need to be pre-configured at all — use the `key()` tool from inside your session:

```
key("EXA_API_KEY", "your-exa-key")
key("BRAVE_API_KEY", "your-brave-key")
```

This writes the value to `.env` in the current directory and loads it into the running process immediately. No restart needed. On the next session in the same project folder, Chameleon picks it up automatically.

---

## All Tools

### `chameleon-mcp` — lean profile (6 tools, ~240 token overhead)

| Tool | Description |
|---|---|
| `morph(server_id, tools)` | Inject a server's tools live. `tools=[...]` for lean morph — only register the tools you need. |
| `shed(release)` | Remove morphed tools. `release=True` kills the process and frees RAM immediately. |
| `search(query, registry)` | Search MCP servers. `registry`: all \| official \| mcpregistry \| glama \| npm \| smithery \| pypi |
| `inspect(server_id)` | Show server tools, schemas, and required credentials. |
| `key(env_var, value)` | Save an API key to `.env` permanently and load it immediately. |
| `status()` | Show current form, active connections (PID + RAM), and token stats. |

### `chameleon-forge` — full suite (all 17 tools, ~825 token overhead)

Everything in the lean profile, plus:

**Execution**

| Tool | Description |
|---|---|
| `call(server_id, tool, args)` | One-shot tool call on any server — no morph needed. |
| `run(package, tool, args)` | Run from npm/pip directly. `uvx:pkg-name` for Python packages. |
| `auto(task, tool, args)` | Search → pick best server → call in one step. |
| `fetch(url, intent)` | Fetch a URL, return compressed text (~17x smaller than raw HTML). |

**Shape-shifting**

| Tool | Description |
|---|---|
| `craft(name, description, params, url)` | Register a custom tool backed by your HTTP endpoint — live immediately. POST=JSON body, GET=query params. `shed()` removes it. |

**Persistent connections**

| Tool | Description |
|---|---|
| `connect(command, name)` | Start a persistent server. `command`: server_id or shell cmd. |
| `release(name)` | Kill a persistent connection by name. |
| `setup(name)` | Setup wizard for a connected server. Call repeatedly until ready. |

**Quality & benchmarking**

| Tool | Description |
|---|---|
| `test(server_id, level)` | Quality-score a server 0–100. `level`: basic or full (live calls). |
| `bench(server_id, tool, args)` | Benchmark tool latency — p50, p95, min, max ms. |

**Skills**

| Tool | Description |
|---|---|
| `skill(qualified_name)` | Load a Smithery skill into context. Persisted across sessions. |

---

## Usage Examples

### Official MCP servers (no API key needed)

```
# Filesystem access
morph("@modelcontextprotocol/server-filesystem")
read_file(path="/tmp/notes.txt")
shed()

# Git operations
morph("@modelcontextprotocol/server-git")
git_log(repo_path="/path/to/repo", max_count=10)
shed()

# SQLite database
morph("mcp-server-sqlite")
read_query(query="SELECT * FROM users LIMIT 10")
shed()
```

### From a GitHub repository

```
# Run a server directly from GitHub (pip-based)
connect("uvx --from git+https://github.com/user/my-mcp-server my-server", name="dev")
setup("dev")            ← check for missing config
call("dev", "tool_name", {"arg": "value"})
release("dev")

# npm-based GitHub server
connect("npx github:user/my-npm-mcp-server", name="dev")
```

### Using the npm registry

```
search("web search", registry="npm")
morph("mcp-server-brave-search")
key("BRAVE_API_KEY", "your-key")    ← saved to .env, never needed again
brave_web_search(query="MCP protocol 2025")
shed()
```

### With Smithery (optional)

```
search("web search")          ← includes Smithery results when key is set
morph("exa/exa")
key("EXA_API_KEY", "your-key")
web_search_exa(query="MCP protocol 2025")
shed()
```

### Persistent server with setup guidance

```
connect("uvx voice-mode", name="voice")
# → ⚠️  Setup required before calling 'voice' tools:
# →   Missing env vars:
# →     key("DEEPGRAM_API_KEY", "<your-value>")
# → Call setup('voice') for step-by-step guidance.

setup("voice")                         ← shows next unresolved step
key("DEEPGRAM_API_KEY", "your-key")
setup("voice")                         ← confirms ready

morph("voice-mode")
speak(text="Hello from Chameleon!")
shed()
release("voice")
```

### Run without morphing

```
call("@modelcontextprotocol/server-filesystem", "read_file", {"path": "/tmp/test.txt"})
run("uvx:mcp-server-time", "get_current_time", {})
```

### Connect by server ID (no install command needed)

```
# Registry ID resolved automatically — no npx/uvx command required
connect("filesystem", name="fs")
connect("@modelcontextprotocol/server-git", name="git")
```

### Docker server (RAM-bounded, easy to destroy)

```
connect("docker run --rm -i --memory 256m mcp-server-image", name="sandboxed")
call("sandboxed", "tool_name", {"arg": "value"})
release("sandboxed")    ← container is killed and removed
```

### shed() with immediate RAM release

```
morph("@modelcontextprotocol/server-puppeteer")
puppeteer_navigate(url="https://example.com")
shed(release=True)   ← kills the Chromium process immediately, frees ~200MB
```

### Lean morph — only the tools you need

```
# A filesystem server has 10+ tools. You only need two.
morph("@modelcontextprotocol/server-filesystem", tools=["read_file", "list_directory"])
# Only those two tools appear — token overhead stays minimal
read_file(path="/tmp/notes.txt")
shed()
```

### craft() — prototype a tool against your own endpoint

```
# Define a tool that calls your local ranking service
craft(
    name="my_ranker",
    description="Rank search results by relevance",
    params={
        "results": {"type": "array", "description": "list of results"},
        "query":   {"type": "string", "description": "original query"}
    },
    url="http://localhost:8080/rank"
)
# my_ranker now appears live — call it directly
my_ranker(results=[...], query="MCP servers")
# Iterate on your endpoint, re-craft to hot-swap, shed() when done
shed()
```

---

## Architecture

```
Claude / AI Agent
       │
       ▼
  Chameleon MCP (server.py — entry point)
       │
       ├── chameleon_mcp/
       │     ├── registry.py         ── MultiRegistry → OfficialMCPRegistry, McpRegistryIO, GlamaRegistry, SmitheryRegistry, NpmRegistry, PyPIRegistry
       │     ├── official_registry.py── reference servers from modelcontextprotocol/servers (seed + GitHub API)
       │     ├── transport.py        ── HTTPSSETransport, StdioTransport, PersistentStdioTransport, DockerTransport, WebSocketTransport
       │     ├── morph.py            ── live tool registration via FastMCP.add_tool / remove_tool
       │     ├── probe.py            ── env var detection, OAuth, schema creds, setup guide generation
       │     ├── credentials.py      ── .env I/O, config resolution
       │     └── tools.py            ── all 17 @mcp.tool() definitions
       │
       ├── OfficialMCPRegistry ──► github.com/modelcontextprotocol/servers  (no auth, 24h cache)
       ├── McpRegistryIO       ──► registry.modelcontextprotocol.io  (no auth, 1h cache)
       ├── GlamaRegistry       ──► glama.ai/mcp/servers  (no auth, 1h cache)
       ├── GitHub repos        ──► npx github:user/repo  /  uvx --from git+https://...
       ├── SmitheryRegistry    ──► registry.smithery.ai  (optional, requires API key)
       ├── NpmRegistry         ──► registry.npmjs.org  (no auth required)
       ├── PyPIRegistry        ──► pypi.org  (no auth required)
       └── craft()             ──► any HTTP/HTTPS endpoint you control (POST or GET)
```

---

## Roadmap

- [x] Search across npm + Smithery
- [x] morph() / shed() — live tool registration
- [x] HTTP+SSE transport for Smithery-hosted servers
- [x] Stdio transport for local npm/pip servers
- [x] Persistent process pool — connect() / release()
- [x] test() quality scoring (0–100)
- [x] bench() latency benchmarking (p50/p95, boot time excluded)
- [x] setup() step-by-step configuration wizard
- [x] Readiness probe: env vars, OAuth, schema credentials, local URL reachability
- [x] Official MCP registry integration ([modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers))
- [x] PyPI registry search (`search(registry="pypi")`)
- [x] Server health monitoring in `status()` (ping + RAM per process)
- [x] GitHub repo as a first-class `server_id` (`github:owner/repo`)
- [x] WebSocket transport (`ws://` / `wss://`)
- [x] Docker transport — RAM-bounded containers, auto-destroyed on release
- [x] connect() accepts registry server IDs (not just shell commands)
- [x] Skill persistence — `skill()` saved to `~/.chameleon/skills.json` across sessions
- [x] Search dedup + relevance ranking across registries
- [x] auto() smart tool selection — search → pick server → pick tool → call in one step
- [x] shed(release=True) — precise pool key tracking, instant RAM release
- [x] inspect() shows live tool schemas from running processes
- [x] craft() — endpoint-backed custom tools, live prototype against any HTTP server
- [x] morph(tools=[...]) — lean morph, register only the tools you need
- [x] lean-by-default — 6-tool profile, ~240 token overhead vs ~825 for full suite
- [x] CHAMELEON_TOOLS env var — surgical tool selection per deployment
- [x] chameleon-forge entry point — full evaluation suite as a separate command

---

## Contributing

```bash
git clone https://github.com/kaiser-data/chameleon-mcp
cd chameleon-mcp
make dev     # install with dev dependencies
make test    # run the test suite (pytest)
make lint    # ruff check
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for tool patterns, commit style, and PR checklist.

Issues and PRs: [github.com/kaiser-data/chameleon-mcp](https://github.com/kaiser-data/chameleon-mcp)

---

*MIT License · Python 3.12+ · Built on [FastMCP](https://github.com/jlowin/fastmcp)*
