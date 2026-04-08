# Client Compatibility

Protean MCP sends MCP notifications when the tool/resource/prompt list changes — allowing clients to refresh without a restart.

## Notification support matrix

| Client | Tool refresh (`mount`) | Tool refresh (`unmount`) | Resource refresh | Prompt refresh | Notes |
|--------|----------------------|-----------------------|-----------------|----------------|-------|
| Claude Code | ✅ tested | ✅ tested | ? | ? | Sessions auto-refresh |
| Claude Desktop | ✅ tested | ✅ tested | ? | ? | May require UI click |
| Cursor | ? | ? | ? | ? | Help wanted |
| Cline | ? | ? | ? | ? | Help wanted |
| OpenClaw | ? | ? | ? | ? | Help wanted |
| Continue | ? | ? | ? | ? | Help wanted |

**Legend:** ✅ tested and working — ❌ tested, not working — ? untested

## What Chameleon sends

| Event | Notification | When |
|-------|-------------|------|
| `mount()` succeeds | `notifications/tools/list_changed` | Always (at least 1 tool registered) |
| `mount()` registers resources | `notifications/resources/list_changed` | Only if ≥1 resource proxied |
| `mount()` registers prompts | `notifications/prompts/list_changed` | Only if ≥1 prompt proxied |
| `unmount()` | `notifications/tools/list_changed` | Always |
| `unmount()` after mounted resources | `notifications/resources/list_changed` | Only if resources were present |
| `unmount()` after mounted prompts | `notifications/prompts/list_changed` | Only if prompts were present |
| `craft()` | `notifications/tools/list_changed` | Always |

Notification failures are silently suppressed — Chameleon continues to work even if the client doesn't support notifications.

## Manual test protocol

To fill in missing rows, run the following steps in your client and record the result:

1. Connect to `protean-mcp` (lean profile)
2. Call `mount("@modelcontextprotocol/server-filesystem")` — verify filesystem tools appear
3. Call any filesystem tool (e.g. `list_directory(path="/tmp")`) — verify it works
4. Call `unmount()` — verify filesystem tools disappear
5. Check whether each step required a manual refresh or happened automatically

Open a PR to update this table with your findings, or file an issue with your test results.

## Fallback behaviour

If a client doesn't support notifications, tools still work correctly — the client just won't auto-refresh its tool list. Users may need to manually restart or refresh to see the updated tool list after `mount()` / `unmount()`.
