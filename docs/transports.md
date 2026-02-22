# Transports Guide

Chameleon supports three transport types. Here's when to use each.

## Decision Tree

```
Does the server need to stay alive between calls?
├── Yes → PersistentStdioTransport  (use connect() / release())
└── No → Is it hosted on smithery.ai?
          ├── Yes → HTTPSSETransport  (automatic for remote servers)
          └── No → StdioTransport    (automatic for stdio servers)
```

## HTTPSSETransport

**When:** Smithery-hosted remote servers (`remote: true` in registry).

**How it works:**
1. Sends MCP initialize request over HTTPS
2. Receives session ID from server
3. Sends tool call with session ID
4. Parses SSE (Server-Sent Events) response

**Config:** Requires `SMITHERY_API_KEY`. Config passed as base64 in URL params.

**Example:**
```python
call("exa/exa", "web_search_exa", {"query": "AI news"})
# or
morph("exa/exa")  # auto-selects HTTPSSETransport
```

**Timeout:** 30s per call. Server may be cold-starting — retry once if timeout.

## StdioTransport

**When:** Local npm/pip packages, stdio-mode Smithery servers.

**How it works:**
1. Spawns subprocess: `npx -y package-name` or `uvx package-name`
2. Sends MCP initialize + notifications/initialized
3. Calls tool via JSON-RPC
4. Kills process when done

**Latency:** 3-30s startup (first run downloads package). Subsequent calls reuse cache.

**Example:**
```python
call("@modelcontextprotocol/server-filesystem", "read_file", {"path": "/tmp/test.txt"})
run("mcp-server-fetch", "fetch", {"url": "https://example.com"})
```

**Limitation:** Each call spawns a new process. Not suitable for hardware/audio servers.

## PersistentStdioTransport

**When:** Hardware servers (audio, camera, etc.) that must stay alive between calls.

**How it works:**
1. First call: spawns process, runs MCP handshake, stores in `_process_pool`
2. Subsequent calls: reuses existing process (serialized with asyncio.Lock)
3. Auto-reconnects once if process dies
4. `stderr=None` — inherits parent stderr so audio errors surface

**Example:**
```python
connect("uvx voice-mode", name="voice")
# Now use morph() or call voice-mode tools directly
release("voice")  # kills process, removes from pool
```

**Key difference from StdioTransport:** Process stays alive. Use `release()` when done.

## Choosing the Right Transport

| Scenario | Transport | Command |
|----------|-----------|---------|
| Smithery hosted API | HTTPSSETransport | `call()` / `morph()` automatic |
| One-shot npm tool | StdioTransport | `call()` / `run()` / `morph()` automatic |
| Audio/hardware tool | PersistentStdioTransport | `connect()` then `release()` |
| Unknown server | Auto-detected | `call()` detects from registry |
