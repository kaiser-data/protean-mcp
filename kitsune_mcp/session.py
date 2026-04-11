import json
from pathlib import Path

SKILLS_PATH = Path.home() / ".kitsune" / "skills.json"

_session: dict = {
    "explored": {},
    "skills": {},
    "grown": {},
    "shapeshift_tools": [],      # names of dynamically registered proxy tools
    "shapeshift_resources": [],  # normalized URI strings registered via shapeshift()
    "shapeshift_prompts": [],    # prompt names registered via shapeshift()
    "crafted_tools": {},         # name -> {url, method, description, params, headers}
    "current_form": None,        # server_id currently shapeshifted into
    "current_form_pool_key": None,  # exact _process_pool key for shiftback(kill=True)
    "current_form_local_install": None,  # {"cmd": [...], "package": str} when source="local"
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
