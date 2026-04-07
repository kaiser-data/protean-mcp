import os
import re
from pathlib import Path

from dotenv import load_dotenv

# Read at import time (load_dotenv() must be called by entry point first)
SMITHERY_API_KEY = os.getenv("SMITHERY_API_KEY", "")
# Write .env to the user's working directory (same location load_dotenv() reads from).
ENV_PATH = os.path.join(os.getcwd(), ".env")

# .env search order — CWD wins (loaded last with override=True)
_DOTENV_PATHS = [
    Path.home() / ".chameleon" / ".env",
    Path.home() / ".env",
    Path(ENV_PATH),
]

# Revision counter — increments whenever any .env file changes on disk.
# Pool entries store their revision at spawn time; stale entries are evicted
# and respawned so they pick up new credentials automatically.
_dotenv_revision: int = 0
_last_dotenv_mtimes: tuple = ()


def _dotenv_mtimes() -> tuple:
    """Return mtime tuple for all .env paths (None if absent)."""
    result = []
    for p in _DOTENV_PATHS:
        try:
            result.append(p.stat().st_mtime)
        except OSError:
            result.append(None)
    return tuple(result)


def _reload_dotenv() -> None:
    """Re-read all .env locations. CWD wins. Increments _dotenv_revision when files change."""
    global _dotenv_revision, _last_dotenv_mtimes
    current_mtimes = _dotenv_mtimes()
    for p in _DOTENV_PATHS[:-1]:
        if p.exists():
            load_dotenv(p, override=False)
    load_dotenv(_DOTENV_PATHS[-1], override=True)  # CWD .env wins
    if current_mtimes != _last_dotenv_mtimes:
        _dotenv_revision += 1
        _last_dotenv_mtimes = current_mtimes


def _registry_headers():
    api_key = os.getenv("SMITHERY_API_KEY") or SMITHERY_API_KEY
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _smithery_available() -> bool:
    return bool(os.getenv("SMITHERY_API_KEY") or SMITHERY_API_KEY)


def _to_env_var(k: str) -> str:
    s = re.sub(r'([a-z])([A-Z])', r'\1_\2', k)
    s = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1_\2', s)
    return s.upper()


def _save_to_env(env_var: str, value: str) -> None:
    try:
        try:
            with open(ENV_PATH) as f:
                lines = f.readlines()
        except FileNotFoundError:
            lines = []
        found = False
        for i, line in enumerate(lines):
            if line.startswith(f"{env_var}="):
                lines[i] = f"{env_var}={value}\n"
                found = True
                break
        if not found:
            if lines and not lines[-1].endswith('\n'):
                lines.append('\n')
            lines.append(f"{env_var}={value}\n")
        with open(ENV_PATH, 'w') as f:
            f.writelines(lines)
    except OSError:
        pass
    os.environ[env_var] = value


def _resolve_config(credentials: dict, user_config: dict) -> tuple:
    _reload_dotenv()  # re-read .env on every check — picks up mid-session edits
    resolved = dict(user_config)
    for cred_key in credentials:
        if not resolved.get(cred_key):
            val = os.getenv(_to_env_var(cred_key))
            if val:
                resolved[cred_key] = val
    missing = {k: v for k, v in credentials.items() if not resolved.get(k)}
    return resolved, missing


def _credentials_guide(server_id: str, credentials: dict, resolved: dict) -> str:
    """Credential status with actionable .env lines for missing ones."""
    missing = {k: v for k, v in credentials.items() if not resolved.get(k)}
    if not missing:
        return ""
    lines = [f"Server '{server_id}' needs credentials:"]
    for cred_key, desc in credentials.items():
        env = _to_env_var(cred_key)
        found = bool(resolved.get(cred_key))
        status = "✓" if found else "✗"
        desc_str = f" — {desc[:60]}" if desc else ""
        lines.append(f"  {status} {env}{desc_str}")
    first_var = _to_env_var(next(iter(missing)))
    lines += [
        "",
        "Add to .env:",
        *[f"  {_to_env_var(k)}=your-value" for k in missing],
        f"Or: key('{first_var}', 'your-value')",
    ]
    return "\n".join(lines)


def _credentials_inspect_block(credentials: dict, resolved: dict) -> list[str]:
    """CREDENTIALS section lines for inspect() — shows ✓/✗ per key with .env hints."""
    if not credentials:
        return ["CREDENTIALS: none required", ""]
    lines = ["CREDENTIALS"]
    for cred_key, desc in credentials.items():
        env = _to_env_var(cred_key)
        found = bool(resolved.get(cred_key))
        status = "✓ found" if found else "✗ missing"
        desc_str = f" — {desc[:60]}" if desc else ""
        lines.append(f"  {status}  {env}{desc_str}")
    missing_envs = [_to_env_var(k) for k in credentials if not resolved.get(k)]
    if missing_envs:
        lines += ["", "  Add to .env:"] + [f"    {e}=your-value" for e in missing_envs]
    lines.append("")
    return lines
