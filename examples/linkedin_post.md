# LinkedIn Post — Protean MCP

**Most AI agents load every tool upfront. That's the wrong model.**

Your agent should only see what it needs — right now, for this task.

One MCP hub. 10,000+ servers. Mount what you need, unmount when done. Switch between any server mid-session without touching a config or restarting anything.

```
mount("brave-search", tools=["web_search"])
# task done
unmount()
mount("supabase")  # instantly
```

Lean agent. Focused context. Endless reach.

`pip install protean-mcp`
