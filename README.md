# Chameleon MCP

**The shape-shifting MCP hub — become any server at runtime**

Chameleon MCP is the first MCP server that can *become* any other MCP server. `morph(server_id)` dynamically registers a target server's tools as first-class tools, letting Claude call them directly without extra indirection. No config file. No restart. The hub reshapes itself.

Works standalone with just npm packages — Smithery API key optional for richer discovery.

---

## What It Does

3,000+ MCP servers exist. Connecting to them still required humans to configure each one by hand.

Chameleon changes that. It's the intelligence layer that discovers servers, understands what credentials they need, and — unlike any other hub — *morphs into them*, exposing their tools as if they were native.

---

## Tools

| Tool | What it does |
|------|-------------|
| `search(query, registry, limit)` | Search for MCP servers. registry: 'all'\|'smithery'\|'npm' |
| `inspect(server_id)` | Show a server's tools, credentials, and token cost |
| `call(server_id, tool_name, arguments, config)` | Call a tool on any MCP server. Creds auto-loaded from env |
| `run(package, tool_name, arguments)` | Run a tool from a local npm/pip package directly (no registry lookup) |
| `fetch(url, intent)` | Fetch a URL and return compressed content (~500 tokens vs ~25K raw) |
| `auto(task, tool_name, arguments, server_hint, keys)` | Auto-discover and call the best server for a task |
| `key(env_var, value)` | Save an API key to .env for persistent use |
| `skill(qualified_name)` | Inject a Smithery skill into Claude's context |
| `morph(server_id)` | Take a server's form — register its tools directly |
| `shed()` | Drop current form and remove morphed tools |
| `status()` | Show current form, active connections, token stats |

---

## Setup

### 1. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Add to Claude Code

Edit `~/.claude/mcp.json`:

```json
{
  "mcpServers": {
    "smithery-lattice": {
      "command": "/path/to/smithery-lattice/.venv/bin/python",
      "args": ["/path/to/smithery-lattice/server.py"]
    }
  }
}
```

Restart Claude Code to load the server.

### 3. (Optional) Get a Smithery API key

Go to [smithery.ai/account/api-keys](https://smithery.ai/account/api-keys) and create a key.

```
key("SMITHERY_API_KEY", "your-key")
```

Enables Smithery registry search (3,000+ verified servers). Without it, npm search still works.

### 4. Save additional credentials (optional)

```
key("BRAVE_API_KEY", "your-key")
```

Saved to `.env` and active immediately — auto-loaded on every future call.

---

## Demo

### Basic usage

```
search("web search")
→ Exa, Brave, Linkup — Smithery + npm results

inspect("exa")
→ 3 tools, no key required, ~623 tokens context cost

call("exa", "web_search_exa", {"query": "shape-shifting AI networks"})
→ live results from Exa

fetch("https://news.ycombinator.com", "top stories")
→ ~500 tokens of clean text instead of ~25,000 tokens of raw HTML

run("@modelcontextprotocol/server-everything", "echo", {"message": "hi"})
→ runs local npm MCP package directly, no registry needed
```

### Morph — the signature feature

```
morph("exa")
→ Morphed into 'exa' — 3 tool(s) registered:
    web_search_exa, find_similar, get_contents

web_search_exa(query="test")   ← called directly, no indirection
→ live search results

shed()
→ Shed 'exa'. Removed: web_search_exa, find_similar, get_contents
```

---

## Architecture

```
Claude Code (CLI)
  └── chameleon (this server, Python MCP, stdio)
        ├── MultiRegistry
        │     ├── SmitheryRegistry  → GET registry.smithery.ai/servers
        │     └── NpmRegistry       → GET registry.npmjs.org/-/v1/search
        ├── HTTPSSETransport  → server.smithery.ai/{name} (remote servers)
        ├── StdioTransport    → npx/uvx subprocess + JSON-RPC (local servers)
        └── Tools
              ├── search / inspect / call / run / fetch
              ├── auto        → full auto-pipeline
              ├── morph / shed → dynamic shape-shifting
              ├── key / skill / status
```

---

## Token Efficiency

Chameleon MCP is built to minimize context pressure:

- All responses capped at ~1,500 tokens
- `fetch()` compresses web pages from ~25,000 → ~500 tokens using HTML stripping
- `search()` uses dense single-line output (5 results ≈ 200 tokens, not 800)
- Tool schemas loaded lazily — only fetched when needed
- `status()` tracks cumulative tokens sent, received, and saved

---

## Smithery API Key — Optional

Without a Smithery API key:

| Tool | Without key |
|------|------------|
| `search` | Falls back to npm-only |
| `inspect` | Works for npm packages |
| `call` / `run` / `fetch` | Work fully |
| `morph` | Works for npm/stdio servers |
| `skill` | Requires key (Smithery-specific) |
| `auto` | Falls back to npm with a note |

---

## Built On

- [FastMCP](https://github.com/jlowin/fastmcp) — Python MCP server framework
- [Smithery Registry API](https://smithery.ai) — 3,000+ verified MCP servers
- [Smithery Skills Registry](https://smithery.ai/skills) — markdown skill injections
- [httpx](https://www.python-httpx.org/) — async HTTP client
- [AxonMCP](https://github.com/AxonMCP/axon-mcp) — optional: enhanced web compression for `fetch()` (install separately for best results)

---

*Chameleon MCP — take any form*
