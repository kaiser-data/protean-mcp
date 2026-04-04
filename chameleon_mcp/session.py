import json
from pathlib import Path

SKILLS_PATH = Path.home() / ".chameleon" / "skills.json"

_session: dict = {
    "explored": {},
    "skills": {},
    "grown": {},
    "morphed_tools": [],      # names of dynamically registered proxy tools
    "current_form": None,     # server_id currently morphed into
    "connections": {},        # persistent connections: {pool_key: {name, command, pid, ...}}
    "stats": {
        "total_calls": 0,
        "tokens_sent": 0,
        "tokens_received": 0,
        "tokens_saved_browse": 0,
    },
}

session = _session


def _load_skills() -> None:
    """Populate session['skills'] from disk on startup."""
    try:
        with open(SKILLS_PATH) as f:
            data = json.load(f)
        if isinstance(data, dict):
            session["skills"].update(data)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass


def _save_skills() -> None:
    """Persist session['skills'] to disk."""
    try:
        SKILLS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(SKILLS_PATH, "w") as f:
            json.dump(session["skills"], f, indent=2)
    except OSError:
        pass


_load_skills()
