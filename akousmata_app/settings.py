"""Local settings for the navigator (stored beside the data, never tracked).

BYOK: keys and endpoints live in ``<store>/settings.json`` on this machine
only. Without any provider configured the app is fully functional as a
library; the LLM layer is an optional deepening, never a requirement.
"""
from __future__ import annotations

import json
from typing import Any

from akousmata_app.paths import settings_path

DEFAULTS: dict[str, Any] = {
    "germ_url": "http://127.0.0.1:5178",
    "oida_url": "http://127.0.0.1:8765",
    "llm": {
        # provider: "none" | "openai_compatible" | "anthropic" | "cli"
        "provider": "none",
        # openai_compatible covers OpenAI, xAI/Grok, OpenRouter, Ollama,
        # llama.cpp — anything speaking /v1/chat/completions.
        "base_url": "",
        "model": "",
        "api_key": "",
        # cli: a local agent command that reads the prompt on stdin and
        # prints the answer (e.g. `codex exec -`, `opencode run`).
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
_NESTED = ("llm", "watcher")


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
    settings_path().write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
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
