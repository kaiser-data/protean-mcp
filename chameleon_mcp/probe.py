import json
import os
import re

from chameleon_mcp.constants import (
    CRED_SUFFIXES,
    PROVIDER_PARAM_SUFFIXES,
    RESOURCE_PRIORITY_KEYWORDS,
    TIMEOUT_TCP_PROBE,
)

_ENV_VAR_RE = re.compile(r'\b([A-Z][A-Z0-9_]{3,})\b')
_LOCAL_URL_RE = re.compile(r'https?://(?:127\.0\.0\.1|localhost)(?::\d+)?(?:/[^\s,)"\']*)?')
_OAUTH_KEYWORDS = ("oauth", "authorize", "authorization_url", "callback", "redirect_uri")


def _doc_uri_priority(uri: str) -> int:
    """Rank a resource URI by how likely it is to contain setup/config documentation."""
    u = uri.lower()
    for rank, keywords in enumerate(RESOURCE_PRIORITY_KEYWORDS):
        if any(kw in u for kw in keywords):
            return rank
    return len(RESOURCE_PRIORITY_KEYWORDS)


def _probe_requirements(tools: list[dict], extra_text: str = "") -> dict:
    """Scan tool schemas, descriptions, and resource docs for missing env vars and unreachable local services."""
    import socket as _socket

    all_text = " ".join(
        (t.get("description") or "") + " " + json.dumps(t.get("inputSchema", {}))
        for t in tools
    )
    if extra_text:
        all_text += " " + extra_text

    # Structured env-var resource format: "VAR_NAME\n  Environment: [not set]"
    # Parse these first — they are authoritative (server's own view of its config)
    _structured_missing: set[str] = set()
    _structured_set: set[str] = set()
    _env_block_re = re.compile(
        r'^([A-Z][A-Z0-9_]{2,})\s*\n\s+Environment:\s*(\[not set\]|.+)', re.MULTILINE
    )
    for m in _env_block_re.finditer(extra_text):
        var, val = m.group(1), m.group(2).strip()
        if val == "[not set]":
            _structured_missing.add(var)
        else:
            _structured_set.add(var)

    # Regex scan for credential env vars mentioned in descriptions/schemas (supplemental)
    found_vars = {
        m for m in _ENV_VAR_RE.findall(all_text)
        if any(m.endswith(sfx) for sfx in CRED_SUFFIXES)
    }
    structured_creds_missing = {v for v in _structured_missing if any(v.endswith(sfx) for sfx in CRED_SUFFIXES)}
    structured_creds_set = {v for v in _structured_set if any(v.endswith(sfx) for sfx in CRED_SUFFIXES)}

    regex_missing = {v for v in found_vars if not os.environ.get(v)} - structured_creds_set
    regex_set = {v for v in found_vars if os.environ.get(v)} - structured_creds_missing

    missing_env = sorted(structured_creds_missing | regex_missing)
    set_env = sorted(structured_creds_set | regex_set)

    # Schema-declared required params that look like credentials
    schema_creds = sorted({
        p for tool in tools
        for p in (tool.get("inputSchema") or {}).get("required", [])
        if any(p.lower().endswith(sfx.lower().lstrip("_")) for sfx in CRED_SUFFIXES)
    })

    # OAuth detection
    needs_oauth = any(kw in all_text.lower() for kw in _OAUTH_KEYWORDS)

    # Local URLs: probe with a short TCP connect
    local_urls = sorted(set(_LOCAL_URL_RE.findall(all_text)))
    reachable, unreachable = [], []
    for url in local_urls:
        try:
            from urllib.parse import urlparse as _urlparse
            p = _urlparse(url)
            host = p.hostname or "127.0.0.1"
            port = p.port or (443 if p.scheme == "https" else 80)
            sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
            sock.settimeout(TIMEOUT_TCP_PROBE)
            ok = sock.connect_ex((host, port)) == 0
            sock.close()
            (reachable if ok else unreachable).append(url)
        except Exception:
            unreachable.append(url)

    # Provider-style enums: params whose name ends with provider/engine/backend/service/mode
    providers: dict[str, list[str]] = {}
    for tool in tools:
        props = (tool.get("inputSchema") or {}).get("properties", {})
        for param, pdef in props.items():
            if not any(param.endswith(sfx) for sfx in PROVIDER_PARAM_SUFFIXES):
                continue
            enum_vals = pdef.get("enum") or next(
                (x.get("enum") for x in pdef.get("anyOf", []) if isinstance(x, dict) and "enum" in x),
                None,
            )
            if enum_vals and len(enum_vals) > 1:
                providers[param] = list(enum_vals)

    return {
        "missing_env": missing_env,
        "set_env": set_env,
        "schema_creds": schema_creds,
        "needs_oauth": needs_oauth,
        "unreachable": unreachable,
        "reachable": reachable,
        "providers": providers,
        "resource_text": extra_text,
        "resource_scan": bool(extra_text),
    }


def _classify_provider(
    opt: str, missing_creds: list, set_creds: list, unreachable: list
) -> str:
    linked_creds = [v for v in missing_creds if opt.upper() in v and any(v.endswith(s) for s in CRED_SUFFIXES)]
    cred_ok = any(opt.upper() in v for v in set_creds)
    linked_urls = [u for u in unreachable if opt in u.lower()]
    if cred_ok:
        return "cloud-ready"
    if linked_creds:
        return "cloud-needs-key"
    if linked_urls or (unreachable and not linked_creds and not cred_ok):
        return "local"
    return "unknown"


def _format_setup_guide(reqs: dict, name: str, tools: list | None = None) -> str:
    """Format a human-readable setup guide from probed requirements."""
    missing = reqs["missing_env"]
    unreachable = reqs["unreachable"]
    providers = reqs["providers"]

    if not missing and not unreachable:
        checks = reqs["set_env"] + reqs["reachable"]
        if checks:
            return "✅ All detected requirements satisfied — ready to call."
        return ""

    lines = [f"\n⚠️  Setup required before calling '{name}' tools:"]

    has_service_tool = bool(tools) and any(
        any(p.endswith(sfx) for sfx in PROVIDER_PARAM_SUFFIXES)
        for t in tools
        for p in (t.get("inputSchema") or {}).get("properties", {})
    )

    _letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

    if providers:
        for param, opts in providers.items():
            cloud_opts, local_opts, other_opts = [], [], []
            for opt in opts:
                linked_creds = [v for v in missing if opt.upper() in v and any(v.endswith(s) for s in CRED_SUFFIXES)]
                cred_ok = any(opt.upper() in v for v in reqs["set_env"])
                is_cloud = bool(linked_creds or cred_ok)
                linked_urls = [u for u in unreachable if opt in u.lower()]

                if is_cloud:
                    cloud_opts.append((opt, linked_creds, cred_ok))
                elif linked_urls:
                    local_opts.append((opt, linked_urls, []))
                elif unreachable and not is_cloud:
                    local_opts.append((opt, [], []))
                else:
                    other_opts.append((opt, []))

            if cloud_opts or local_opts:
                lines.append(f"\n{param} — pick one:")
                idx = 0
                for opt, creds, ok in cloud_opts:
                    status = "✅ ready" if ok else "needs API key"
                    label = _letters[idx] if idx < len(_letters) else str(idx + 1)
                    lines.append(f"  [{label}] {opt}  (cloud — {status})")
                    for v in creds:
                        lines.append(f"      key(\"{v}\", \"<your-value>\")")
                    idx += 1
                for opt, urls, _creds in local_opts:
                    label = _letters[idx] if idx < len(_letters) else str(idx + 1)
                    lines.append(f"  [{label}] {opt}  (local — not running)")
                    for u in urls:
                        lines.append(f"      {u}  ← not reachable")
                    if has_service_tool:
                        lines.append(f"      service(\"{opt}\", \"start\")")
                    idx += 1
                for opt, _ in other_opts:
                    label = _letters[idx] if idx < len(_letters) else str(idx + 1)
                    lines.append(f"  [{label}] {opt}")
                    idx += 1
                continue

    # Env vars not covered by provider grouping
    ungrouped_vars = set(missing)
    for opts_list in providers.values():
        for opt in opts_list:
            for v in missing:
                if opt.upper() in v:
                    ungrouped_vars.discard(v)
    if ungrouped_vars:
        lines.append("\nMissing env vars:")
        for v in sorted(ungrouped_vars):
            lines.append(f"  key(\"{v}\", \"<your-value>\")")

    # Local URLs not already shown inside a provider option
    urls_shown = {u for opt_list in providers.values() for u in unreachable if any(o in u.lower() for o in opt_list)}
    ungrouped_urls = set(unreachable) - urls_shown
    if ungrouped_urls:
        label = "\nLocal services not reachable:" if not providers else "\nAdditional local services not reachable:"
        lines.append(label)
        for u in sorted(ungrouped_urls):
            lines.append(f"  {u}  ← not running")

    return "\n".join(lines)
