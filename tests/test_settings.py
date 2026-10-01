"""Settings failures and concurrent owners use only disposable stores."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
import stat
import subprocess
import sys
import threading

import pytest
from fastapi.testclient import TestClient

from akousmata_app import settings


@pytest.fixture
def local_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("AKOUSMATA_PATH", str(tmp_path))
    monkeypatch.setenv("AKOUSMATA_WATCHER", "0")
    return tmp_path / "settings.json"


@pytest.mark.parametrize("value", [None, [], "wrong root", {"llm": []}, {"watcher": None}, {"human_profile": 1}])
def test_wrong_stored_shapes_load_defaults_without_rewriting(local_settings, value):
    local_settings.write_text(json.dumps(value))
    before = local_settings.read_bytes()
    assert settings.load() == settings.DEFAULTS
    assert local_settings.read_bytes() == before


def test_recovery_preserves_other_valid_private_fields(local_settings):
    local_settings.write_text(json.dumps({
        "llm": {"api_key": "fixture-only-key", "provider": "anthropic", "model": []},
        "watcher": {"ingest_seconds": "invalid", "enabled": False},
        "human_profile": {"listener_id": "fixture-owner", "privacy": "invalid"},
    }))
    data = settings.load()
    assert data["llm"]["api_key"] == "fixture-only-key"
    assert data["llm"]["model"] == ""
    assert data["watcher"] == {**settings.DEFAULTS["watcher"], "enabled": False}
    assert data["human_profile"]["listener_id"] == "fixture-owner"
    assert data["human_profile"]["privacy"] == "private"
    saved = settings.save({"llm": {"model": "fixture-model"}})
    assert json.loads(local_settings.read_text()) == saved
    assert saved["llm"]["api_key"] == "fixture-only-key"


@pytest.mark.parametrize("patch", [
    [], {"llm": []}, {"llm": {"api_key": 1}}, {"llm": {"provider": "unknown"}},
    {"watcher": {"enabled": "false"}}, {"watcher": {"ingest_seconds": True}},
    {"watcher": {"ingest_seconds": "60"}}, {"watcher": {"ingest_seconds": 0}},
    {"watcher": {"ingest_seconds": 86401}}, {"watcher": {"ingest_seconds": float("nan")}},
    {"watcher": {"lint_minutes": float("inf")}}, {"watcher": {"lint_minutes": -1}},
    {"watcher": {"lint_minutes": 1441}}, {"human_profile": {"privacy": "public"}},
    {"unknown": "value"},
])
def test_invalid_patch_keeps_last_valid_settings(local_settings, patch):
    settings.save({"llm": {"api_key": "fixture-only-key"}})
    before = local_settings.read_bytes()
    with pytest.raises(ValueError):
        settings.save(patch)
    assert local_settings.read_bytes() == before


@pytest.mark.parametrize("operation", ["replace", "fsync"])
def test_failed_save_is_atomic_private_and_retryable(local_settings, monkeypatch, operation):
    settings.save({"llm": {"api_key": "fixture-only-key"}})
    before = local_settings.read_bytes()
    with monkeypatch.context() as context:
        def fail(*_args):
            raise OSError("injected interrupted save")
        context.setattr(settings.os, operation, fail)
        with pytest.raises(OSError):
            settings.save({"watcher": {"enabled": False}})
    assert local_settings.read_bytes() == before
    assert list(local_settings.parent.glob(".settings-*.tmp")) == []
    settings.save({"watcher": {"enabled": False}})
    assert settings.load()["watcher"]["enabled"] is False
    if os.name != "nt":
        assert stat.S_IMODE(local_settings.stat().st_mode) == 0o600
        assert stat.S_IMODE((local_settings.parent / ".settings.lock").stat().st_mode) == 0o600


def test_thread_updates_do_not_lose_fields(local_settings):
    barrier = threading.Barrier(3)

    def update(patch):
        barrier.wait(timeout=5)
        settings.save(patch)

    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs = [pool.submit(update, patch) for patch in (
            {"llm": {"model": "fixture-model"}}, {"llm": {"api_key": "fixture-only-key"}},
            {"watcher": {"enabled": False}},
        )]
        for job in jobs:
            job.result(timeout=10)
    data = settings.load()
    assert data["llm"]["model"] == "fixture-model"
    assert data["llm"]["api_key"] == "fixture-only-key"
    assert data["watcher"]["enabled"] is False


def test_process_updates_preserve_fields_and_one_owner_identity(local_settings):
    script = """
import json, sys
from akousmata_app.settings import save
print('ready', flush=True)
sys.stdin.readline()
saved = save(json.loads(sys.argv[1]), ensure_profile=True)
print(saved['human_profile']['listener_id'], flush=True)
"""
    children = [subprocess.Popen([sys.executable, "-c", script, json.dumps(patch)],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                for patch in ({"llm": {"model": "fixture-model"}}, {"llm": {"api_key": "fixture-only-key"}})]
    try:
        for child in children:
            assert child.stdout.readline().strip() == "ready"
        for child in children:
            child.stdin.write("go\n")
            child.stdin.flush()
        identities = []
        for child in children:
            output, error = child.communicate(timeout=10)
            assert child.returncode == 0, error
            identities.append(output.strip())
        assert identities[0] == identities[1] != ""
        data = settings.load()
        assert data["human_profile"]["listener_id"] == identities[0]
        assert data["llm"]["model"] == "fixture-model"
        assert data["llm"]["api_key"] == "fixture-only-key"
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.communicate()


def test_settings_api_rejects_whole_invalid_patch_and_preserves_masked_key(local_settings, monkeypatch):
    from akousmata_app import server
    from akousmata_app.request_boundary import RequestBoundary
    monkeypatch.setattr(server, "_REQUEST_BOUNDARY", RequestBoundary())
    monkeypatch.setattr(server, "_WORKSPACE_ID", None)
    settings.save({"llm": {"api_key": "fixture-only-key"}}, ensure_profile=True)
    before = local_settings.read_bytes()
    with TestClient(server.app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        for payload in (
            {"llm": None}, {"watcher": []}, {"human_profile": "invalid"},
            {"human_profile": {"display_name": "changed"}, "watcher": {"ingest_seconds": "invalid"}},
            {"llm": {"model": "changed"}, "human_profile": {"privacy": "public"}},
            {"human_profile": {"listener_id": "changed"}},
        ):
            assert client.put("/api/settings", json=payload).status_code == 422
            assert local_settings.read_bytes() == before
        for number in ("NaN", "Infinity", "-Infinity"):
            response = client.put("/api/settings", content='{"watcher":{"ingest_seconds":' + number + '}}', headers={"Content-Type": "application/json"})
            assert response.status_code == 422
            assert local_settings.read_bytes() == before
        response = client.put("/api/settings", json={"llm": {"api_key": {"secret": "fixture-only-key"}}})
        assert response.status_code == 422
        assert "fixture-only-key" not in response.text
        assert local_settings.read_bytes() == before
        response = client.put("/api/settings", json={"human_profile": {"privacy": "shared", "display_name": "  Fixture Owner  "}, "llm": {"api_key": "••••••••-key", "model": "fixture-model"}})
        assert response.status_code == 200
        assert response.json()["human_profile"]["display_name"] == "Fixture Owner"
        assert response.json()["llm"]["api_key"].endswith("-key")
    assert settings.load()["llm"]["api_key"] == "fixture-only-key"
    assert settings.load()["human_profile"]["listener_id"] == json.loads(before)["human_profile"]["listener_id"]


def test_keyless_local_provider_configuration_is_reported(local_settings):
    data = settings.save({"llm": {"provider": "openai_compatible", "model": "fixture-model"}})
    assert settings.public_view(data)["llm"]["configured"] is True
