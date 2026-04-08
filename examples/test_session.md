# Protean MCP — Test Session

Paste the prompt below into a Claude Code session that has Protean MCP configured.
Run tests in order — each one builds on the previous.

---

## Prompt to paste

```
You are running a structured test of Protean MCP v0.6.0.

Work through each test case below in order. For every test:
1. Call the tool(s) listed
2. Check the expected output
3. Report PASS or FAIL with what you actually observed

Do not skip tests. If a test fails, note why and continue to the next one.

---

TEST 1 — Verify Chameleon is running
Call: status()
Expect:
- Output starts with "CHAMELEON MCP STATUS"
- Shows "CURRENT FORM: base (no mount active)"
- Shows PERFORMANCE STATS section

---

TEST 2 — Search works across registries
Call: search("filesystem")
Expect:
- At least one result returned
- Each result shows source/transport (e.g. "official/stdio")
- Result includes @modelcontextprotocol/server-filesystem

---

TEST 3 — Inspect fetches live schemas
Call: inspect("@modelcontextprotocol/server-filesystem")
Expect:
- Shows "Source: official | Transport: stdio"
- TOOLS section lists read_file, write_file, list_directory (and others)
- Each tool shows its parameters in parentheses e.g. read_file(path)
- Shows "Token cost: ~XXX tokens (measured)" — note the number
- Shows "CREDENTIALS: none required"

---

TEST 4 — Full mount injects tools natively
Call: mount("@modelcontextprotocol/server-filesystem")
Expect:
- Output says "Morphed into '@modelcontextprotocol/server-filesystem'"
- Lists registered tools: read_file, write_file, list_directory etc
- Shows "✓  Source: official" (high-trust source)
- No credential warning (filesystem needs none)
- The filesystem tools are now visible in your tool list

---

TEST 5 — Morphed tool actually executes
Call: list_directory(path="/tmp")
Expect:
- Returns a real directory listing (not an error)
- Content looks like a file list

---

TEST 6 — Unmount removes all mounted tools
Call: unmount()
Expect:
- Output says "Unmount '@modelcontextprotocol/server-filesystem'. Removed: read_file, write_file, ..."
- Filesystem tools are gone from your tool list

---

TEST 7 — Lean mount filters to specific tools
Call: mount("@modelcontextprotocol/server-filesystem", tools=["read_file", "list_directory"])
Expect:
- Output says "(lean: read_file, list_directory)"
- Only 2 tools registered — NOT write_file, create_directory, delete_file etc
- Output count matches: "2 tool(s) registered"
Then call: unmount()

---

TEST 8 — Status shows token savings after inspection
Call: status()
Expect:
- EXPLORED section shows @modelcontextprotocol/server-filesystem [inspected]
- PERFORMANCE STATS shows "Saved vs always-on: ~XXX tokens [based on 1 inspected schema(s)]"
  (This confirms inspect() stored the measured token cost)

---

TEST 9 — Trust warning for community server
Call: mount("mcp-server-brave-search")
Expect:
- Output shows "⚠️  Source: npm (community — not verified by official MCP registry)"
- Output shows credential warning: '⚠️  Credentials may be required' with key("BRAVE_API_KEY", ...)
- Tools ARE registered despite the warning (warning is informational, not blocking)
Then call: unmount()

---

TEST 10 — inspect() is cheaper than mount()
Call: inspect("@modelcontextprotocol/server-memory")
Expect:
- Shows tool schemas with parameters
- Shows token cost
- Critically: no memory tools appear in your tool list — inspect() registers NOTHING
  (Verify by checking — you should still only see Chameleon's base tools)

---

TEST 11 — status() full picture
Call: status()
Expect:
- EXPLORED section shows both servers inspected/used so far
- If any servers were mounted and unmount, those appear in ACTIVE NODES
- PERFORMANCE STATS shows cumulative token savings from all inspected servers
  (Should now be higher than after TEST 8)

---

SUMMARY
Report:
- How many tests passed / failed
- The token cost shown by inspect() in TEST 3 (should be around 300-500 tokens)
- The savings shown by status() in TEST 11
- Any unexpected behaviour
```

---

## Expected token numbers (reference)

| Tool | Expected tokens |
|---|---|
| Chameleon lean (6 tools) | ~450 |
| filesystem server (10 tools) | ~300–400 |
| brave-search (3 tools) | ~100–150 |
| memory server (varies) | ~100–300 |

Run `python examples/benchmark.py` to see Chameleon's own schema costs measured exactly.

---

## Checklist — what each test validates

| Test | What it proves |
|---|---|
| 1 | Chameleon is connected and responding |
| 2 | Registry fan-out works (official + fallbacks) |
| 3 | inspect() fetches live schemas, measures token cost, stores in session |
| 4 | mount() registers tools natively, trust tier shown |
| 5 | Proxy execution works — call actually reaches the target server |
| 6 | unmount() removes all mounted tools cleanly |
| 7 | Lean mount (tools=[...]) filters correctly |
| 8 | status() uses measured token costs, not heuristics (v0.6.0) |
| 9 | Trust warnings and credential warnings fire for community sources |
| 10 | inspect() has zero tool-registration side effects |
| 11 | Session accumulates state correctly across multiple operations |

---

## Troubleshooting

**"Server not found"** — run `search("filesystem")` first to confirm registry is reachable.

**Mount takes a long time** — first run downloads the npm package via npx. Subsequent calls use the process pool and are instant.

**No trust warning on TEST 9** — check that mcp-server-brave-search resolves from npm (source should be "npm", not "official").

**Token savings is 0 in TEST 8** — make sure you called `inspect()` in TEST 3 before `mount()` in TEST 4. inspect() is what stores the measured cost; mount() alone does not.
