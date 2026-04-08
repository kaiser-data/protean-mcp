# Code Review Request — Protean MCP

Hi,

I'd love a review of a small open source Python project I've been building called **Protean MCP**. It's an MIT-licensed MCP proxy server.

**Repo**: https://github.com/your-org/protean-mcp
**Language**: Python 3.11+, uses FastMCP
**Size**: ~1,500 lines across 7 modules

I'm specifically interested in feedback on three things: **novelty**, **code style**, and **security**.

---

## What it does (30-second summary)

Most AI clients (Claude Desktop, Cursor, etc.) require you to list MCP servers statically in a config file and restart to add new ones. Protean MCP is a single server you register once, and from there you can discover, install, and use any other MCP server at runtime — without touching config files.

```
# From within Claude or any MCP client:
search("web search")                          # find available servers
mount("@modelcontextprotocol/server-brave")   # add their tools instantly
brave_web_search(query="MCP 2025")            # use them natively
unmount()                                         # remove them when done
```

The `mount()` call downloads and starts the target server as a subprocess, then registers its tools into the live MCP session via FastMCP's runtime API. `unmount()` removes them. The running process is pooled and reused across calls.

---

## 1. Novelty — is this actually new?

The core pattern I haven't seen elsewhere:

- **Dynamic MCP tool registration via MCP itself**: using one MCP server to add/remove tools from other MCP servers at runtime, without client restart. FastMCP exposes a `mcp.remove_tool()` / tool registration API that makes this possible.
- **Single-entry-point proxy model**: one server in `mcp.json`, dynamically proxies to N others. Most existing solutions are either static configs or separate processes.
- **Process pool for stdio MCP servers**: `PersistentStdioTransport` keeps the subprocess alive across tool calls (keyed by `json.dumps(install_cmd)`), avoiding the cold-start penalty on each call. I haven't seen this in other MCP client implementations.

Questions I'd appreciate thoughts on:
- Is the `mount/unmount` pattern genuinely novel, or is there prior art I should be aware of?
- Does the process pool approach have known failure modes I should guard against?

---

## 2. Code Style

Key files:

| File | What it does |
|------|-------------|
| `chameleon_mcp/tools.py` | All MCP tool definitions (~900 lines) |
| `chameleon_mcp/transport.py` | StdioTransport, PersistentStdioTransport, HTTPSSETransport |
| `chameleon_mcp/registry.py` | SmitheryRegistry, NpmRegistry, MultiRegistry |
| `chameleon_mcp/credentials.py` | .env read/write, credential resolution |
| `chameleon_mcp/session.py` | Module-level session state dict |
| `chameleon_mcp/utils.py` | Token estimation, content extraction helpers |

Things I'm uncertain about stylistically:

- `tools.py` has one large `_register_tools(mcp)` function that registers all tools. It's long but cohesive — is that acceptable, or should tools be split into sub-modules?
- `session` is a module-level dict (`session = {"stats": {...}, ...}`). Simple, but feels like a smell. Is a singleton dataclass better?
- Exception handling in registries uses broad `except Exception: return []` to fail gracefully — is that the right approach for a proxy that shouldn't crash on partial failures?
- I use `_` prefix throughout for internal helpers (not intended as public API). Is that the right convention for a library that may be imported?

---

## 3. Security

The project's fundamental design is that it executes arbitrary npm/pip packages. `mount("some-package")` runs `npx -y some-package` as a subprocess. This is intentional and the core value proposition — but it means I need to be honest about the threat model.

**Fixed before this review:**

### ~~b) SSRF in `skill()`~~ — fixed
`skill()` previously fetched from a `content_url` returned by the Smithery registry API without validation. A tampered registry response could have pointed to internal services. Fixed by adding `_is_safe_url()` which rejects non-HTTPS schemes and private/loopback IPs (`127.x`, `10.x`, `192.168.x`, `169.254.x`, `::1`, `localhost`) before fetching.

### ~~c) `command.split()` in `connect()`~~ — fixed
```python
# was:
install_cmd = command.split()
# now:
install_cmd = shlex.split(command)
```
Handles quoted arguments and paths with spaces correctly.

### ~~`.env` written to package install directory~~ — fixed
`ENV_PATH` previously resolved relative to the package install location (`site-packages/.env`), meaning `key()` silently wrote credentials to the wrong place on installed builds. Fixed to use `os.getcwd()`, consistent with where `load_dotenv()` reads from.

---

**One remaining known issue (third-party constraint):**

### a) Credentials in URL query string (medium) — cannot fix
`HTTPSSETransport` sends server config base64-encoded in the URL query string:
```python
base_url = f"https://server.smithery.ai/{self.qualified_name}?config={config_b64}"
```
This puts credentials (e.g. `brave_api_key`) in server access logs and CDN logs. However, this is **Smithery's own API protocol** — their server reads configuration from query params by design. We can't move it to the POST body without breaking their transport. Worth flagging to Smithery, but not something we can fix on our side.

---

**Design-level consideration (not a bug, needs documentation):**

### b) Spawned process privileges
Subprocesses inherit the full parent environment (all env vars), unrestricted filesystem access, and network access. This is the correct tradeoff for an MCP proxy — it's literally the point — but it needs a clear security model section in the README so users understand they're running code from the internet.

**Questions for the reviewer:**
- Are there additional attack vectors I'm missing, given that the entry point is an AI model calling tools?
- Any thoughts on whether spawned processes should be sandboxed (e.g., `firejail`, no-network flag) as an opt-in?

---

## What I'm NOT looking for

- Feature requests — I have a roadmap and trying to keep scope tight
- Performance micro-optimizations — happy to discuss architecture-level performance concerns

---

## How to run it

```bash
pip install protean-mcp
# Add to your MCP client config, no API keys required
```

Or clone and run from source:
```bash
git clone https://github.com/your-org/protean-mcp
cd protean-mcp
pip install -e .
protean-mcp
```

Thanks for any time you can give it.
