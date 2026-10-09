"""Typed, private local settings; provider credentials never enter source control."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
import secrets
import tempfile
import threading
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from akousmata_app.paths import settings_path


class SettingsSection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class ProfilePatch(SettingsSection):
    display_name: str = ""
    privacy: Literal["private", "shared"] = "private"

    @field_validator("display_name")
    @classmethod
    def trim_display_name(cls, value):
        return value.strip()


class HumanProfile(ProfilePatch):
    # A local ownership handle, not a global identity or authentication token.
    listener_id: str = ""


class LLMSettings(SettingsSection):
    provider: Literal["none", "openai_compatible", "anthropic", "cli"] = "none"
    base_url: str = ""
    model: str = ""
    api_key: str = ""
    command: str = ""


class WatcherSettings(SettingsSection):
    enabled: bool = True
    ingest_seconds: float = Field(default=60, ge=0.1, le=86400, allow_inf_nan=False)
    lint_minutes: float = Field(default=30, ge=0.01, le=1440, allow_inf_nan=False)


class Settings(SettingsSection):
    germ_url: str = ""
    oida_url: str = "http://127.0.0.1:8765"
    human_profile: HumanProfile = Field(default_factory=HumanProfile)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    watcher: WatcherSettings = Field(default_factory=WatcherSettings)


class SettingsPatch(SettingsSection):
    germ_url: str | None = None
    oida_url: str | None = None
    human_profile: ProfilePatch | None = None
    llm: LLMSettings | None = None
    watcher: WatcherSettings | None = None

    @field_validator("human_profile", "llm", "watcher", mode="before")
    @classmethod
    def section_is_object(cls, value):
        if value is None:
            raise ValueError("Settings section must be an object")
        return value


DEFAULTS = Settings().model_dump()
_NESTED = ("human_profile", "llm", "watcher")
PROFILE_PRIVACY_VALUES = {"private", "shared"}
_PROFILE_LOCK = threading.RLock()


def _merge(data: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    result = json.loads(json.dumps(data))
    for key, value in patch.items():
        if key in _NESTED and isinstance(value, dict):
            result[key].update(value)
        else:
            result[key] = value
    return result


def load() -> dict[str, Any]:
    """Recover valid known fields from malformed local JSON without logging it.

    Loading does not rewrite the file. Invalid fields fall back to defaults;
    valid provider credentials and profile fields remain available.
    """
    data = Settings().model_dump()
    try:
        stored = json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return data
    if not isinstance(stored, dict):
        return data
    for key in DEFAULTS:
        if key not in stored:
            continue
        value = stored[key]
        patches = [{key: {field: item}} for field, item in value.items()] if key in _NESTED and isinstance(value, dict) else [{key: value}]
        for patch in patches:
            try:
                data = Settings.model_validate(_merge(data, patch)).model_dump()
            except ValidationError:
                pass
    return data


@contextmanager
def _write_lock(path):
    # A stable lock inode serializes read/modify/replace across processes too.
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path.parent / ".settings.lock", os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        if os.name == "nt":
            import msvcrt
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\0")
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            os.fchmod(fd, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _atomic_write(path, data):
    staged = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix=".settings-", suffix=".tmp", dir=path.parent, delete=False) as output:
            staged = output.name
            # mkstemp-backed staging is private even under a permissive umask.
            json.dump(data, output, indent=2, ensure_ascii=False, allow_nan=False)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(staged, path)
        if os.name != "nt":
            directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if staged is not None:
            try:
                os.unlink(staged)
            except FileNotFoundError:
                pass


def save(patch: dict[str, Any], *, ensure_profile: bool = False) -> dict[str, Any]:
    if not isinstance(patch, dict):
        raise ValueError("Settings patch must be an object")
    with _PROFILE_LOCK, _write_lock(settings_path()):
        try:
            data = Settings.model_validate(_merge(load(), patch)).model_dump()
        except ValidationError:
            raise ValueError("Invalid settings configuration") from None
        if ensure_profile and not data["human_profile"]["listener_id"].strip():
            data["human_profile"]["listener_id"] = f"human_local_{secrets.token_hex(12)}"
        _atomic_write(settings_path(), data)
        return data


def public_view(data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Settings with the key masked for the UI."""
    data = data if data is not None else load()
    view = json.loads(json.dumps(data))
    key = view["llm"]["api_key"]
    view["llm"]["api_key"] = ("•" * 8 + key[-4:]) if key else ""
    view["llm"]["configured"] = bool(
        (data["llm"]["provider"] == "openai_compatible" and data["llm"]["model"])
        or (data["llm"]["provider"] == "anthropic" and data["llm"]["api_key"])
        or (data["llm"]["provider"] == "cli" and data["llm"]["command"])
    )
    return view


def ensure_human_profile() -> dict[str, str]:
    """Return a stable local identity, creating it in a locked transaction."""
    with _PROFILE_LOCK:
        profile = load()["human_profile"]
        if not profile["listener_id"].strip():
            profile = save({}, ensure_profile=True)["human_profile"]
        return {key: value.strip() for key, value in profile.items()}


def update_human_profile(*, display_name: str = "", privacy: str = "private") -> dict[str, str]:
    try:
        profile = ProfilePatch(display_name=display_name, privacy=privacy)
    except ValidationError:
        raise ValueError("Invalid human profile configuration") from None
    return save({"human_profile": profile.model_dump()}, ensure_profile=True)["human_profile"]
