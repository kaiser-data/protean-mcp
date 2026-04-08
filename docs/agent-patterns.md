# Agent Patterns

Common patterns for AI agents using Protean MCP.

## Pattern 1: Search → Quality Gate → Mount

Validate a server before committing to it:

```python
# Step 1: Find candidates
search("web scraping", limit=5)

# Step 2: Quality gate
score = test("exa/exa")
# → Score: 85/100 (Good) — proceed

# Step 3: Mount only if quality is acceptable
mount("exa/exa")
web_search_exa(query="latest Python news")
```

## Pattern 2: Chain Morphs

Mount into multiple servers in sequence for a multi-step task:

```python
# Step 1: Research
mount("exa/exa")
results = web_search_exa(query="MCP server list 2025")
unmount()

# Step 2: Fetch and extract
mount("fetch-mcp/fetch-mcp")
content = fetch_page(url="https://example.com/mcp-servers")
unmount()

# Step 3: Write output
mount("@modelcontextprotocol/server-filesystem")
write_file(path="/tmp/report.md", content=f"# Research\n{results}\n\n{content}")
unmount()
```

## Pattern 3: Hardware Pipeline

Audio processing with persistent connections:

```python
# Connect audio server once
connect("uvx voice-mode", name="audio", timeout=30)

# Mounting uses the persistent process
mount("voice-mode")

# Pipeline: listen → process → speak
transcript = listen(duration=10)
# (call other tools to process transcript)
speak(text=f"I heard: {transcript}")

unmount()
release("audio")
```

## Pattern 4: Auto-Discovery with Fallback

Let Chameleon pick the best server, with a manual fallback:

```python
# Try auto-discovery first
result = auto("search for Python packages", "search", {"query": "httpx"})

# If auto fails, fall back to a known server
if "No servers found" in result:
    result = call("mcp-server-npm", "search", {"query": "httpx"})
```

## Pattern 5: Benchmark Before Batch

Benchmark latency before running many calls:

```python
# Check if server is fast enough for batch work
bench("exa/exa", "web_search_exa", {"query": "test"}, iterations=3)
# → p50: 234ms | p95: 891ms

# If p95 < 1000ms, proceed with batch
queries = ["AI news", "Python MCP", "FastAPI tutorial"]
mount("exa/exa")
for q in queries:
    web_search_exa(query=q)
unmount()
```

## Pattern 6: Multi-Registry Discovery

Search both Smithery and npm, compare results:

```python
smithery_results = search("file system", registry="smithery", limit=3)
npm_results = search("file system", registry="npm", limit=3)

# Inspect the top result from each
inspect(smithery_results[0].id)
inspect(npm_results[0].id)

# Pick the one with better tooling
mount("@modelcontextprotocol/server-filesystem")
```

## Anti-Patterns to Avoid

### Don't mount without shedding
```python
mount("server-a")
mount("server-b")  # ✓ Auto-sheds server-a first
# But explicit unmount() is clearer:
mount("server-a")
unmount()
mount("server-b")
```

### Don't use call() for hardware tools
```python
# ❌ Spawns new process every call — audio device disconnects
call("voice-mode", "speak", {"text": "Hello"})
call("voice-mode", "speak", {"text": "World"})

# ✓ Use connect() to keep process alive
connect("uvx voice-mode", name="voice")
call("voice-mode", "speak", {"text": "Hello"})
call("voice-mode", "speak", {"text": "World"})
release("voice")
```

### Don't forget to release() hardware connections
```python
# ❌ Process leaks
connect("uvx voice-mode", name="voice")
# ... work ...
unmount()   # only removes mount, doesn't kill process!

# ✓ Always release hardware connections
connect("uvx voice-mode", name="voice")
# ... work ...
unmount()
release("voice")
```
