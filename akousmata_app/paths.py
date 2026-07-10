"""Store discovery and sibling py-akousma resolution.

The app code lives in the same folder as the store data by default
(`~/workspace/akousmata`, override with ``AKOUSMATA_PATH``); the data
files (``index.sqlite``, ``objects/``, ``wiki/``, ``settings.json``) are
gitignored — the library is personal, the navigator is public.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def store_root() -> Path:
    env = os.getenv("AKOUSMATA_PATH")
    if env:
        return Path(env).expanduser()
    return REPO_ROOT


def wiki_root() -> Path:
    return store_root() / "wiki"


def settings_path() -> Path:
    return store_root() / "settings.json"


def ensure_pyakousma() -> None:
    """Make the earworm reference implementation importable in monorepo
    layouts without an install step (mirrors algophony's test pattern)."""
    try:
        import akousma  # noqa: F401
        return
    except ModuleNotFoundError:
        pass
    for candidate in (
        os.getenv("AKOUSMATA_PYAKOUSMA_PATH"),
        REPO_ROOT.parent / "earworm" / "packages" / "py-akousma",
    ):
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        if (path / "akousma" / "__init__.py").exists():
            sys.path.insert(0, str(path))
            return


def open_store(root: str | Path | None = None):
    ensure_pyakousma()
    try:
        import akousma
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "the 'akousma' package is required: pip install -e <SFL>/earworm/packages/py-akousma "
            "(or set AKOUSMATA_PYAKOUSMA_PATH)"
        ) from exc
    return akousma.AkousmataStore(root or store_root())
