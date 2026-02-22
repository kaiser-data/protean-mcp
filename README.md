# 🦎 Chameleon MCP

**The shape-shifting MCP hub — morph() into any server at runtime. 3,000+ servers. No config. No restart.**

[![PyPI](https://img.shields.io/pypi/v/chameleon-mcp?color=blue)](https://pypi.org/project/chameleon-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/chameleon-mcp)](https://pypi.org/project/chameleon-mcp/)
[![CI](https://github.com/kaiser-data/chameleon-mcp/actions/workflows/test.yml/badge.svg)](https://github.com/kaiser-data/chameleon-mcp/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Smithery](https://smithery.ai/badge/@kaiser-data/chameleon-mcp)](https://smithery.ai/server/@kaiser-data/chameleon-mcp)

**[Install](#install)** · **[Demo](#demo)** · **[All Tools](#all-tools)** · **[Hardware](#hardware)** · **[Contributing](#contributing)**

---

## Demo

```
Claude: search("web search")

┌─ SERVERS — 'web search' (3 found)
│  exa/exa           | Exa — AI-powered web search         | smithery/http | creds: free
│  tavily/tavily-ai  | Tavily — Search for AI agents       | smithery/http | creds: free
│  brave-search/...  | Brave Search — Privacy-first search | smithery/http | creds: apiKey

Claude: morph("exa/exa")

Morphed into 'exa/exa' — 3 tool(s) registered:
  web_search_exa
  find_similar_exa
  get_contents_exa

Call them directly, or use shed() to return to base form.

Claude: web_search_exa(query="Model Context Protocol 2025")

Top results for "Model Context Protocol 2025":
1. Anthropic announces MCP 1.0 ...
2. 3,000+ MCP servers now available ...

Claude: shed()

Shed 'exa/exa'. Removed: web_search_exa, find_similar_exa, get_contents_exa

Claude: morph("@modelcontextprotocol/server-filesystem")

Morphed into '@modelcontextprotocol/server-filesystem' — 5 tool(s) registered:
  read_file, write_file, list_directory, create_directory, move_file
```

**One Chameleon. Every server. Zero config files.**

---

## Why Chameleon?

| | Traditional MCP Hub | Chameleon MCP |
|---|---|---|
| **Call a tool** | `hub.server_name.tool_name(args)` — one indirection level | Direct native call: `tool_name(args)` |
| **Add a server** | Edit config file, restart Claude | `morph("server-id")` — live |
| **Switch servers** | Restart required | `shed()` then `morph()` — instant |
| **Hardware/audio** | Process dies between calls | `connect()` keeps it alive |
| **Validate quality** | Manual testing | `test("server-id")` → score 0-100 |
| **No API key** | Often required | Works with npm fallback |
| **Discovery** | Know the server name | `search("task description")` |

---

## Install

```bash
pip install chameleon-mcp
```

Add to your `mcp.json`:

```json
{
  "mcpServers": {
    "chameleon": {
      "command": "python",
      "args": ["/path/to/server.py"],
      "env": {
        "SMITHERY_API_KEY": "your-key-here"
      }
    }
  }
}
```

Get a free Smithery API key at [smithery.ai/account/api-keys](https://smithery.ai/account/api-keys) — unlocks 3,000+ verified servers. Works without a key too (npm fallback).

**From source:**
```bash
git clone https://github.com/kaiser-data/chameleon-mcp
cd chameleon-mcp && pip install -e .
```

---

## All Tools

| Tool | What it does |
|------|-------------|
| `search(query, registry, limit)` | Search 3,000+ servers across Smithery + npm |
| `inspect(server_id)` | Show tools, credentials, token cost |
| `call(server_id, tool, args)` | Call any tool on any server |
| `run(package, tool, args)` | Direct npm/pip package execution |
| `morph(server_id)` | Take a server's form — tools appear natively |
| `shed()` | Drop form, return to base Chameleon |
| `auto(task, tool, args)` | Full auto-discovery pipeline in one call |
| `fetch(url, intent)` | Fetch URL with ~17x compression |
| `connect(command, name)` | Connect persistent hardware/audio server |
| `release(name)` | Kill persistent connection, free resources |
| `test(server_id, level)` | Quality score 0-100 with pass/fail checks |
| `bench(server_id, tool, args)` | Latency benchmark: p50, p95, min, max |
| `status()` | Current form, connections, token stats |
| `key(env_var, value)` | Save API key to .env permanently |
| `skill(qualified_name)` | Inject Smithery skill prompt into context |

---

## Hardware

Some MCP servers — audio, camera, hardware interfaces — can't cold-start per call. `connect()` keeps them alive:

```python
# Connect once — process stays alive
connect("uvx voice-mode", name="voice")
# → Connected: voice (PID 12345)
# → Tools (4): speak, transcribe, listen, get_voices

# Tools are reusable across calls
morph("voice-mode")
speak(text="Hello from Chameleon!")
listen(duration=5)

# Release when done
shed()
release("voice")
```

**Key behaviors:**
- `stderr=None` — hardware errors surface to your terminal
- Single `asyncio.Lock` per process — serialized calls, no JSON-RPC collision
- Auto-reconnect if process dies during a call
- `shed()` does NOT kill the process — only `release()` does

See [docs/hardware.md](docs/hardware.md) for the full guide.

---

## Architecture

```
Claude / AI Agent
       │
       ▼
  Chameleon MCP (server.py)
       │
       ├── MultiRegistry
       │     ├── SmitheryRegistry  ──► smithery.ai/api (3,000+ servers)
       │     └── NpmRegistry       ──► registry.npmjs.org
       │
       ├── Transports
       │     ├── HTTPSSETransport           (remote smithery servers)
       │     ├── StdioTransport             (one-shot npm/pip subprocess)
       │     └── PersistentStdioTransport   (hardware — process stays alive)
       │
       └── morph() / shed()
             └── FastMCP.add_tool() / remove_tool() — live tool registration
```

---

## Built With Chameleon

| Project | What it does | Author |
|---------|-------------|--------|
| *(your project here)* | *(description)* | [Open a PR](https://github.com/kaiser-data/chameleon-mcp/pulls) |

Built something with Chameleon? Add it to the table — open a PR.

---

## Roadmap

- [x] Search (Smithery + npm multi-registry)
- [x] morph() / shed() with live tool registration
- [x] HTTP+SSE transport for remote servers
- [x] Stdio transport for local npm/pip servers
- [x] Persistent process pool for hardware tools
- [x] connect() / release() for audio servers
- [x] test() quality scoring (0-100)
- [x] bench() latency benchmarking
- [ ] WebSocket transport support
- [ ] Server health monitoring in status()
- [ ] `morph --persist` flag to keep process after shed()
- [ ] Smithery registry submission and approval

---

## Contributing

```bash
git clone https://github.com/kaiser-data/chameleon-mcp
cd chameleon-mcp
make dev     # install + dev deps
make test    # pytest
make lint    # ruff check
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for tool patterns, commit style, and PR checklist.

Issues: [github.com/kaiser-data/chameleon-mcp/issues](https://github.com/kaiser-data/chameleon-mcp/issues)

---

*MIT License · Python 3.12+ · Powered by [FastMCP](https://github.com/jlowin/fastmcp) + [Smithery](https://smithery.ai)*
