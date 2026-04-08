# New Session Prompt: Decouple from Smithery / Open Source Hardening

Copy and paste this into a new Claude Code session opened in the `Protean MCP` project directory.

---

## Prompt

```
I need you to review the Protean MCP codebase and README, then produce a concrete implementation plan to make this open source project less dependent on Smithery (a commercial platform).

Context:
- Protean MCP is an open source MIT-licensed MCP proxy tool
- It currently treats Smithery as the primary registry, but that's a commercial service
- The goal: GitHub repos and npm/PyPI packages should be the primary path, Smithery is one optional registry among several
- The project should work fully without any commercial API keys

Please:

1. Read the README.md and understand the current state
2. Read chameleon_mcp/registry.py — especially MultiRegistry
3. Read chameleon_mcp/tools.py — find every place that hard-requires or prioritizes Smithery
4. Read chameleon_mcp/transport.py — understand current transports
5. Read chameleon_mcp/credentials.py — understand _smithery_available()

Then produce a prioritized plan covering:

A. Code changes needed to make Smithery truly optional (not just documented as optional):
   - Result ordering in MultiRegistry (npm should lead when no Smithery key)
   - Any tool that returns an error or degrades when Smithery is absent
   - The skill() tool — hard-requires Smithery API key, document as Smithery-only
   - test() and bench() — currently says "not found in registry" for GitHub paths, needs fix

B. GitHub as a first-class server source:
   - Add `github:user/repo` as a recognized server_id prefix in mount(), call(), inspect()
   - Detect whether the repo is npm or pip based (check for package.json vs pyproject.toml)
   - Route to `npx github:user/repo` or `uvx --from git+https://github.com/...` accordingly
   - Add a GitHubRegistry that searches GitHub's repo API (topic: mcp-server)

C. Additional registries to implement (in priority order):
   - PyPI registry search (search packages with mcp-server prefix/keyword)
   - Official MCP servers list (parse modelcontextprotocol/servers README or registry)
   - GitHub registry (search repos by topic)
   - mcp.so / Glama.ai (evaluate feasibility)

D. README changes still needed after initial update:
   - Verify Quick Start works truly without any key
   - Add community/contribution section with Discord/GitHub Discussions link
   - Ensure architecture diagram reflects real priority order

For each item, provide: what file to change, what the change is, and rough complexity (S/M/L).
```
