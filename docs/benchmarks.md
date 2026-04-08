# Token Benchmark Methodology

## How to run

```bash
python examples/benchmark.py
```

No network access required. All measurements use actual registered tool schemas from the running package.

## What it measures

| Section | What |
|---------|------|
| **Profile sizes** | Token cost of the lean (6-tool) and forge (17-tool) profiles as registered by FastMCP |
| **Savings vs always-on** | Chameleon's total cost vs loading N servers permanently |
| **Per-tool breakdown** | Token cost of each individual tool schema |

## Token count formula

```python
token_count = len(json.dumps(schema)) // 4
```

This matches `_estimate_tokens()` in `chameleon_mcp/utils.py` — the same heuristic used throughout the codebase. It approximates the common 4 chars/token rule of thumb used for Claude/GPT models.

**Caveats:**
- Actual token counts vary slightly by model and tokenizer (±10–20%)
- The "always-on baseline" uses a representative 8-tool server (97 tokens/tool avg)
- Real savings depend on the actual servers in your use case

## Interpreting the savings table

The comparison shows chameleon's total overhead **including one active mounted server** vs loading N servers all at once:

- **Chameleon lean** = 6 lean tools + 1 mounted server (best case per task)
- **Chameleon forge** = 17 full tools + 1 mounted server
- **Always-on baseline** = N × 8 tools × 97 tokens permanently in context

Lean mode is more cost-effective than always-on once you have 2+ servers. Forge becomes cost-effective at 3+ servers.

## Reference output (v0.5.6)

```
==============================================================
  Protean MCP — Token Overhead Benchmark
==============================================================

=== Profile sizes (actual registered schemas) ===
  lean  ( 6 tools / default):    451 tokens
  forge (17 tools / full):     1694 tokens

=== Savings: chameleon vs always-on N servers ===
  Baseline: 8 tools/server × 97 tokens/tool (representative avg)

  2 servers — always-on baseline:  1552 tokens
    chameleon lean:    1227 tokens  (saves 20%)
    chameleon forge:   2470 tokens  (costs 59% more)

  5 servers — always-on baseline:  3880 tokens
    chameleon lean:    1227 tokens  (saves 68%)
    chameleon forge:   2470 tokens  (saves 36%)

  10 servers — always-on baseline:  7760 tokens
    chameleon lean:    1227 tokens  (saves 84%)
    chameleon forge:   2470 tokens  (saves 68%)

=== Per-tool breakdown ===
  Tool                         Tokens  Profile
  --------------------------------------------
  craft                           180  forge only
  auto                            159  forge only
  call                            152  forge only
  bench                           133  forge only
  connect                         128  forge only
  run                             116  forge only
  mount                           101  lean + forge
  search                           99  lean + forge
  test                             87  forge only
  skill                            84  forge only
  key                              79  lean + forge
  fetch                            78  forge only
  setup                            66  forge only
  unmount                             65  lean + forge
  inspect                          63  lean + forge
  release                          55  forge only
  status                           42  lean + forge
```
