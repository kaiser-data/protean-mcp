# Hardware & Persistent Connections

Chameleon's `connect()` / `release()` pattern keeps MCP server processes alive between calls — essential for audio, camera, and other hardware tools that can't cold-start per-call.

## The Problem with StdioTransport

Standard `call()` spawns a new process, makes one call, then kills it. For audio:
- `npx voice-mode speak "hello"` → 3-5s startup every time
- Audio devices disconnected between calls
- State lost (e.g., conversation context)

## The Solution: PersistentStdioTransport

`connect()` starts the process once and keeps it in `_process_pool`:

```
connect("uvx voice-mode", name="voice")
│
├── Spawns: uvx voice-mode (PID 12345)
├── Runs MCP initialize handshake
├── Stores in _process_pool["uvx voice-mode"]
└── Returns: tool list

# Now call tools — process stays alive:
call("voice-mode", "speak", {"text": "Hello!"})   # reuses PID 12345
call("voice-mode", "speak", {"text": "World!"})   # reuses PID 12345

release("voice")
└── Kills PID 12345, removes from pool
```

## Voice Mode Example

```python
# Step 1: Connect
connect("uvx voice-mode", name="voice", timeout=30)
# → Connected: voice (PID 89234)
# → Tools (4): speak, transcribe, listen, get_voices
# → Release with: release('voice')

# Step 2: Use tools directly via call() or morph()
morph("voice-mode")        # registers speak, transcribe, etc. directly
speak(text="Starting up!")
listen(duration=5)

# Step 3: Release when done
shed()                     # remove morphed tools
release("voice")           # kill process
```

## Key Behaviors

### stderr inheritance
`PersistentStdioTransport` uses `stderr=None`, which inherits parent stderr. This means audio errors, device warnings, and debug output from the hardware server surface directly to your terminal — essential for debugging hardware issues.

### Serialized calls
Each pool entry has an `asyncio.Lock`. Only one call runs at a time per process. This prevents JSON-RPC message interleaving on hardware servers that aren't designed for concurrent access.

### Auto-reconnect
If the process dies during a call (e.g., audio device disconnected), `PersistentStdioTransport` attempts to restart it once automatically before returning an error.

### shed() does NOT kill persistent connections
`shed()` only removes morphed proxy tools from your tool list. The underlying process stays alive. Use `release()` to kill it:

```python
shed()          # removes morphed tools — process still running
release("voice") # kills the process
```

## Checking Connection Status

```python
status()
# →
# PERSISTENT CONNECTIONS (1)
#   voice | PID 89234 | alive | uptime: 142s | calls: 7
#   Tools: speak, transcribe, listen, get_voices
```

## Multiple Hardware Servers

```python
connect("uvx voice-mode", name="voice")
connect("uvx camera-mcp", name="camera")

# Both run simultaneously
status()
# → PERSISTENT CONNECTIONS (2)
#     voice  | PID 89234 | alive | uptime: 45s  | calls: 3
#     camera | PID 89301 | alive | uptime: 12s  | calls: 1

# Release individually
release("voice")
release("camera")
```

## Error: Already Connected

If you call `connect()` on an already-connected server, Chameleon returns the current status instead of starting a duplicate:

```python
connect("uvx voice-mode", name="voice")
# → Already connected: voice (PID 89234) | uptime: 30s | calls: 2
```
