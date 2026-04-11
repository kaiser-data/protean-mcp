# Quickstart — First Shapeshift in 2 Minutes

## 1. Install

```bash
# Recommended — no pip needed, runs in an isolated env:
uvx kitsune-mcp

# Or install globally:
pip install kitsune-mcp

# Or via npm:
npx kitsune-mcp
```

## 2. Add to Claude Desktop

Add this to your `claude_desktop_config.json`
(usually at `~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "kitsune": {
      "command": "uvx",
      "args": ["kitsune-mcp"],
      "env": {
        "SMITHERY_API_KEY": "your-key-here"
      }
    }
  }
}
```

Get a free Smithery API key at [smithery.ai/account/api-keys](https://smithery.ai/account/api-keys).

> **No API key?** Kitsune still works — it falls back to npm registry search. You'll have access to hundreds of npm-published MCP servers.

## 3. Restart Claude and try your first shapeshift

In Claude, type:

```
search("web search")
```

Pick a server from the results, then:

```
shapeshift("exa/exa")
```

Now call its tools directly — they appear in your tool list instantly:

```
web_search_exa(query="latest AI news")
```

Done! To return to base form:

```
shiftback()
```

## Next Steps

- [Tools Reference](tools.md) — all tools with examples
- [Transports Guide](transports.md) — when to use HTTP vs stdio vs persistent
- [Agent Patterns](agent-patterns.md) — chain shapeshifts, quality gates, pipelines
