# Tools Reference

All Kitsune MCP tools with parameters, return format, and examples.

---

## Discovery Tools

### `search(query, registry="all", limit=5)`

Search for MCP servers across registries.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| query | str | required | Search term |
| registry | str | "all" | "all" \| "smithery" \| "npm" |
| limit | int | 5 | Max results (1-20) |

**Returns:** Formatted list of servers with ID, name, description, source, transport, credentials.

```python
search("web search")
search("filesystem", registry="npm", limit=10)
search("exa", registry="smithery")
```

---

### `inspect(server_id)`

Show a server's full details: tools, credentials, install command, token cost.

```python
inspect("exa/exa")
inspect("@modelcontextprotocol/server-filesystem")
```

---

### `auto(task, tool_name="", arguments={}, server_hint="", keys={})`

Full auto-discovery pipeline in one call. Finds best server, resolves credentials, calls tool.

```python
auto("search the web for AI news", "web_search_exa", {"query": "AI news"})
auto("read a file", "read_file", {"path": "/tmp/test.txt"})
# With keys:
auto("search", "web_search", {"q": "test"}, keys={"EXA_API_KEY": "sk-..."})
```

---

## Execution Tools

### `call(server_id, tool_name, arguments={}, config={})`

Call any tool on any MCP server. Transport auto-detected from registry.

```python
call("exa/exa", "web_search_exa", {"query": "Python MCP"})
call("@modelcontextprotocol/server-filesystem", "read_file", {"path": "/tmp/test.txt"})
# With inline credentials:
call("my-server", "tool", {}, {"apiKey": "sk-abc123"})
```

---

### `run(package, tool_name, arguments={})`

Run a tool from a local package directly (no registry lookup).

```python
run("mcp-server-fetch", "fetch", {"url": "https://example.com"})
run("uvx:voice-mode", "speak", {"text": "Hello!"})  # uvx: prefix for Python packages
```

---

### `fetch(url, intent="")`

Fetch a URL with ~17x compression (strips HTML, collapses whitespace).

```python
fetch("https://docs.python.org/3/library/asyncio.html")
fetch("https://news.ycombinator.com", intent="top AI stories today")
```

---

## Mounting Tools

### `shapeshift(server_id)`

Take a server's form — register its tools directly in your tool list. Requires FastMCP context.

```python
shapeshift("exa/exa")
# → Tools appear: web_search_exa, find_similar_exa, ...
# Call them directly now
web_search_exa(query="MCP servers")
```

**Note:** Automatically reverts previous form before shapeshifting.

---

### `shiftback()`

Drop current form, remove all mounted tools, return to base Kitsune MCP.

```python
shiftback()
# → Mounted tools removed from tool list
```

**Note:** Does NOT kill persistent connections. Use `release(name)` for that.

---

## Hardware / Persistent Tools

### `connect(command, name="", timeout=60)`

Connect a persistent hardware/audio MCP server. Process stays alive between calls.

```python
connect("uvx voice-mode", name="voice")
# → Connected: voice (PID 12345)
# → Tools (3): speak, transcribe, listen
# → Release with: release('voice')
```

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| command | str | required | Shell command, e.g. "uvx voice-mode" |
| name | str | "" | Friendly name for release() |
| timeout | int | 60 | Startup timeout in seconds |

---

### `release(name)`

Kill a persistent connection and remove it from the pool.

```python
release("voice")
# → Released: voice (PID 12345) | uptime: 142s | calls: 7
```

---

## Quality Tools

### `test(server_id, level="basic")`

Validate an MCP server and return a quality score 0-100.

| Check | Points | Level |
|-------|--------|-------|
| Registry lookup found server | 15 | basic |
| Transport type known | 5 | basic |
| Has description (>10 chars) | 5 | basic |
| tools/list responds | 15 | basic |
| Tool schemas have name + inputSchema | 10 | basic |
| No collision with base tool names | 10 | basic |
| Each tool callable (dummy args) | 10/tool (max 5) | full |

Grade: ≥90 Excellent · ≥75 Good · ≥50 Fair · <50 Poor

```python
test("exa/exa")
test("@modelcontextprotocol/server-filesystem", level="full")
```

---

### `bench(server_id, tool_name, args, iterations=5)`

Benchmark a tool's latency.

```python
bench("exa/exa", "web_search_exa", {"query": "test"}, iterations=10)
# → p50: 234ms | p95: 891ms | min: 198ms | max: 1203ms | avg: 312ms | errors: 0
```

---

## Management Tools

### `status()`

Show current form, persistent connections, token stats, session activity.

```python
status()
```

---

### `key(env_var, value)`

Save an API key to `.env` for persistent use.

```python
key("SMITHERY_API_KEY", "sk-abc123")
key("EXA_API_KEY", "exa-xyz...")
```

---

### `skill(qualified_name)`

Inject a skill prompt into context. Requires API key.

```python
skill("smithery/web-research")
```

---

## Token Limits

All tools cap responses at ~1,500 tokens (~6,000 chars). Long responses are truncated with a note.
Use `fetch()` for web content — it compresses ~17x vs raw HTML.
