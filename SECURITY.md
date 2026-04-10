# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.8.x   | ✅ Yes    |
| < 0.8   | ❌ No     |

## Reporting a Vulnerability

Please **do not** open a public GitHub issue for security vulnerabilities.

Report privately via [GitHub Security Advisories](https://github.com/kaiser-data/kitsune-mcp/security/advisories/new).

Include:
- Description of the vulnerability
- Steps to reproduce
- Affected versions
- Suggested fix (if any)

You can expect an acknowledgement within 48 hours and a fix or mitigation within 7 days for confirmed critical issues.

## Scope

In scope:
- Credential exposure or leakage through transport layer
- Command injection via `shapeshift()` install commands
- Path traversal in file-based transports
- Token/key exposure in logs or error messages

Out of scope:
- Vulnerabilities in third-party MCP servers accessed via Kitsune
- Issues requiring physical access to the machine
