"""Local settings for the navigator (stored beside the data, never tracked).

BYOK: keys and endpoints live in ``<store>/settings.json`` on this machine
only. Without any provider configured the app is fully functional as a
library; the LLM layer is an optional deepening, never a requirement.
"""
from __future__ import annotations

import json
import secrets
import threading
from typing import Any

from akousmata_app.paths import settings_path

DEFAULTS: dict[str, Any] = {
    "germ_url": "",
    "oida_url": "http://127.0.0.1:8765",
    "human_profile": {
        # Generated once in the local, ignored settings.json. This is an
        # ownership handle, not a global identity or an authentication token.
        "listener_id": "",
        "display_name": "",
        "privacy": "private",
    },
    "llm": {
        # provider: "none" | "openai_compatible" | "anthropic" | "cli"
        "provider": "none",
        # openai_compatible covers OpenAI, xAI/Grok, OpenRouter, Ollama,
        # llama.cpp — anything speaking /v1/chat/completions.
        "base_url": "",
        "model": "",
        "api_key": "",
        # cli: a local executable plus arguments that reads the prompt on stdin
        # and prints the answer (e.g. `codex exec -`, `opencode run`).
        "command": "",
    },
    "watcher": {
        # the background maintainer: auto-ingest fresh records into the wiki,
        # refresh diary digests, and lint on an interval.
        "enabled": True,
        "ingest_seconds": 60,
        "lint_minutes": 30,
    },
}
_NESTED = ("human_profile", "llm", "watcher")
PROFILE_PRIVACY_VALUES = {"private", "shared"}
_PROFILE_LOCK = threading.RLock()


def load() -> dict[str, Any]:
    path = settings_path()
    data: dict[str, Any] = json.loads(json.dumps(DEFAULTS))
    if path.exists():
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
            for key, value in stored.items():
                if key in _NESTED and isinstance(value, dict):
                    data[key].update(value)
                else:
                    data[key] = value
        except (OSError, json.JSONDecodeError):
            pass
    return data


def save(patch: dict[str, Any]) -> dict[str, Any]:
    data = load()
    for key, value in patch.items():
        if key in _NESTED and isinstance(value, dict):
            data[key].update(value)
        elif key in DEFAULTS:
            data[key] = value
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return data


def public_view(data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Settings with the key masked for the UI."""
    data = data or load()
    view = json.loads(json.dumps(data))
    key = view.get("llm", {}).get("api_key") or ""
    view["llm"]["api_key"] = ("•" * 8 + key[-4:]) if key else ""
    view["llm"]["configured"] = bool(
        (data["llm"]["provider"] == "openai_compatible" and data["llm"]["api_key"] and data["llm"]["model"])
        or (data["llm"]["provider"] == "anthropic" and data["llm"]["api_key"])
        or (data["llm"]["provider"] == "cli" and data["llm"]["command"])
    )
    return view


def ensure_human_profile() -> dict[str, str]:
    """Return the stable local human profile, creating its id once.

    The profile stays beside the store in ignored local settings. Records use
    the id to prove local ownership; a display name enters a record only when
    the profile is explicitly marked ``shared``.
    """
    with _PROFILE_LOCK:
        data = load()
        profile = data.setdefault("human_profile", {})
        listener_id = str(profile.get("listener_id") or "").strip()
        if not listener_id:
            listener_id = f"human_local_{secrets.token_hex(12)}"
            profile["listener_id"] = listener_id
            save({"human_profile": profile})
        privacy = str(profile.get("privacy") or "private")
        if privacy not in PROFILE_PRIVACY_VALUES:
            privacy = "private"
        return {
            "listener_id": listener_id,
            "display_name": str(profile.get("display_name") or "").strip(),
            "privacy": privacy,
        }


def update_human_profile(*, display_name: str = "", privacy: str = "private") -> dict[str, str]:
    if privacy not in PROFILE_PRIVACY_VALUES:
        raise ValueError(f"privacy must be one of {sorted(PROFILE_PRIVACY_VALUES)}")
    with _PROFILE_LOCK:
        profile = ensure_human_profile()
        profile["display_name"] = display_name.strip()
        profile["privacy"] = privacy
        save({"human_profile": profile})
        return profile
