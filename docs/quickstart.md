# Quickstart — First Morph in 2 Minutes

## 1. Install

```bash
pip install chameleon-mcp
```

Or from source:
```bash
git clone https://github.com/kaiser-data/chameleon-mcp
cd chameleon-mcp
pip install -e .
```

## 2. Add to Claude Desktop

Add this to your `mcp.json` (usually at `~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "chameleon": {
      "command": "python",
      "args": ["/path/to/chameleon-mcp/server.py"],
      "env": {
        "SMITHERY_API_KEY": "your-key-here"
      }
    }
  }
}
```

Get a free Smithery API key at [smithery.ai/account/api-keys](https://smithery.ai/account/api-keys).

> **No API key?** Chameleon still works — it falls back to npm registry search. You'll have access to hundreds of npm-published MCP servers.

## 3. Restart Claude and try your first morph

In Claude, type:

```
search("web search")
```

Pick a server from the results, then:

```
morph("exa/exa")
```

Now call its tools directly — they appear in your tool list instantly:

```
web_search_exa(query="latest AI news")
```

Done! To go back to base form:

```
shed()
```

## Next Steps

- [Tools Reference](tools.md) — all 15 tools with examples
- [Transports Guide](transports.md) — when to use HTTP vs stdio vs persistent
- [Hardware Setup](hardware.md) — connect audio/hardware servers
- [Agent Patterns](agent-patterns.md) — chain morphs, quality gates, pipelines
