import os
import re

# Read at import time (load_dotenv() must be called by entry point first)
SMITHERY_API_KEY = os.getenv("SMITHERY_API_KEY", "")
# Write .env to the user's working directory (same location load_dotenv() reads from).
# Using the package install directory was incorrect for installed packages.
ENV_PATH = os.path.join(os.getcwd(), ".env")


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
    resolved = dict(user_config)
    for cred_key in credentials:
        if not resolved.get(cred_key):
            val = os.getenv(_to_env_var(cred_key))
            if val:
                resolved[cred_key] = val
    missing = {k: v for k, v in credentials.items() if not resolved.get(k)}
    return resolved, missing


def _credentials_guide(server_id: str, credentials: dict, resolved: dict) -> str:
    missing = {k: v for k, v in credentials.items() if not resolved.get(k)}
    if not missing:
        return ""
    first_var = _to_env_var(next(iter(missing)))
    lines = [f"Server '{server_id}' needs credentials:"]
    for cred_key, desc in missing.items():
        env = _to_env_var(cred_key)
        lines.append(f"  {cred_key} → {env}" + (f"  ({desc[:80]})" if desc else ""))
    example = "{" + ", ".join(f'"{k}": "val"' for k in missing) + "}"
    lines += [
        "",
        f"Save permanently:  key('{first_var}', 'your-value')",
        f"Or inline:  call('{server_id}', '<tool>', {{...}}, {example})",
    ]
    return "\n".join(lines)
