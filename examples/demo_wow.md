# Protean MCP — 5-Minute Demo

This is the canonical "wow demo" — 8 steps that show every core capability in one session.

No config edits. No restarts. Copy each line into your AI client and run it.

---

## Prerequisites

```bash
pip install protean-mcp
```

Add once to your MCP config and restart your client:

```json
{
  "mcpServers": {
    "chameleon": { "command": "protean-mcp" }
  }
}
```

---

## Step 1 — Check baseline

```
status()
```

Expected output: base Chameleon tools only, 0 mounted tools, token savings = 0.

---

## Step 2 — Discover servers

```
search("web scraping")
```

Returns results from the official registry first, then Smithery (if you have a key), then npm. Each result shows source, transport, and any required credentials.

Want only PyPI-installable servers?

```
search("web scraping", registry="pypi")
```

---

## Step 3 — Inspect before committing

```
inspect("@modelcontextprotocol/server-puppeteer")
```

Shows all tools and their schemas, required credentials, transport type, and an estimated token cost. Use this to decide whether to mount before spending tokens.

---

## Step 4 — Quality-gate with test()

```
test("@modelcontextprotocol/server-puppeteer")
```

Returns a score from 0–100 across: connectivity, tool schema validity, response format, and latency. A score below 60 is a red flag.

---

## Step 5 — The aha moment: mount()

```
mount("@modelcontextprotocol/server-puppeteer")
```

Chameleon fetches the server's tool definitions and registers them **directly onto itself** via FastMCP's live API. After this call:

```
status()
```

You'll see `puppeteer_navigate`, `puppeteer_screenshot`, `puppeteer_click`, etc. listed as active mounted tools. They are callable by name — no wrapper, no indirection.

```
puppeteer_navigate(url="https://example.com")
puppeteer_screenshot(name="homepage")
```

---

## Step 6 — Benchmark before you commit

```
bench("@modelcontextprotocol/server-puppeteer", "puppeteer_navigate", {"url": "https://example.com"}, n=5)
```

Returns p50 and p95 latency across 5 runs. Compare two servers before deciding which to configure permanently.

---

## Step 7 — Chain to a second server without unmounting

```
mount("@modelcontextprotocol/server-filesystem")
```

`mount()` automatically sheds the current form before injecting the new one. Now you have filesystem tools:

```
read_file(path="/tmp/homepage_notes.txt")
write_file(path="/tmp/scraped.txt", content="...")
```

---

## Step 8 — Final status with token savings

```
unmount()
status()
```

With `inspect()` run earlier, the `status()` output now shows:

```
Explored servers: 2
  Saved vs always-on: ~3,200 tokens (2 servers × lazy-load)
```

This is the token cost you would have paid on every request if both servers were configured statically in `mcp.json`. With Chameleon, you only pay context cost when you actually mount in the server.

---

## Full session transcript

```
status()
search("web scraping")
inspect("@modelcontextprotocol/server-puppeteer")
test("@modelcontextprotocol/server-puppeteer")
mount("@modelcontextprotocol/server-puppeteer")
puppeteer_navigate(url="https://example.com")
bench("@modelcontextprotocol/server-puppeteer", "puppeteer_navigate", {"url": "https://example.com"}, n=5)
mount("@modelcontextprotocol/server-filesystem")
read_file(path="/tmp/test.txt")
unmount()
status()
```

---

## What just happened

| Step | What it shows |
|------|--------------|
| `status()` baseline | Clean state, minimal tool count |
| `search()` | Discovery across 4 registries: official, Smithery, npm, PyPI |
| `inspect()` | Schema + token cost preview without spawning anything |
| `test()` | Quality score before you commit |
| `mount()` | Native tools injected live — no restart, no config edit |
| Native tool call | Claude calls `puppeteer_navigate` as if it were always there |
| `bench()` | Measured latency before permanent adoption |
| Second `mount()` | Instant swap to a different server |
| `status()` final | Token savings vs always-on config, health of pool entries |
