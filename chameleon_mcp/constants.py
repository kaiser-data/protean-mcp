MCP_PROTOCOL_VERSION = "2024-11-05"
MCP_CLIENT_INFO = {"name": "chameleon", "version": "1.0.0"}

TIMEOUT_STDIO_INIT    = 60.0
TIMEOUT_STDIO_TOOL    = 30.0
TIMEOUT_HTTP_TOOL     = 30.0
TIMEOUT_RESOURCE_LIST = 5.0
TIMEOUT_RESOURCE_READ = 5.0
TIMEOUT_TCP_PROBE     = 0.5
TIMEOUT_FETCH_URL     = 15.0

MAX_RESPONSE_TOKENS = 1500
MAX_EXPLORE_DESC    = 80
MAX_INSPECT_DESC    = 120

CRED_SUFFIXES = (
    "_KEY", "_TOKEN", "_SECRET", "_API_KEY", "_PASSWORD",
    "_APIKEY", "_ACCESS_KEY", "_CLIENT_ID", "_CLIENT_SECRET",
)

RESOURCE_PRIORITY_KEYWORDS = [["env"], ["param"], ["auth", "key"], ["quick", "setup"], ["config"]]
MAX_RESOURCE_DOCS = 4

POOL_MAX_IDLE_SECONDS = 3600   # evict processes idle for longer than 1 hour
POOL_MAX_PROCESSES    = 10     # hard cap on concurrent pool entries

OFFICIAL_REGISTRY_URL       = "https://raw.githubusercontent.com/modelcontextprotocol/servers/main/servers.json"
OFFICIAL_REGISTRY_CACHE_TTL = 86400  # 24 hours — list rarely changes

MCP_REGISTRY_IO_URL   = "https://registry.modelcontextprotocol.io/v0/servers"
MCP_REGISTRY_IO_TTL   = 3600   # 1 hour — entries are published formally, stable
GLAMA_REGISTRY_URL    = "https://glama.ai/api/mcp/v1/servers"
GLAMA_REGISTRY_TTL    = 3600   # 1 hour

PROVIDER_PARAM_SUFFIXES = ("provider", "engine", "backend", "service", "mode")
