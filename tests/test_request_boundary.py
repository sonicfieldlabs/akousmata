"""Global owner admission is checked before any sensitive handler runs."""
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from akousmata_app.request_boundary import RequestBoundary


@pytest.fixture
def owner(monkeypatch, tmp_path):
    monkeypatch.setenv("AKOUSMATA_PATH", str(tmp_path))
    monkeypatch.setenv("AKOUSMATA_WATCHER", "0")
    from akousmata_app import server
    monkeypatch.setattr(server, "_REQUEST_BOUNDARY", RequestBoundary())
    monkeypatch.setattr(server, "_WORKSPACE_ID", None)
    return server


def local_client(owner, **kwargs):
    return TestClient(owner.app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000), **kwargs)


def test_local_browser_and_originless_cli_are_supported(owner):
    with local_client(owner) as client:
        assert client.get("/owner/identity").status_code == 200
        for origin in (None, "http://127.0.0.1", "http://127.0.0.1:80"):
            headers = {"Origin": origin} if origin else {}
            assert client.put("/api/settings", json={"watcher": {"enabled": False}}, headers=headers).status_code == 200


def test_mount_preserves_owner_admission_and_same_origin(owner):
    parent = FastAPI()
    parent.mount("/library", owner.app)
    with TestClient(parent, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 50000)) as client:
        assert client.get("/library/owner/identity").status_code == 200
        assert client.put("/library/api/settings", json={}, headers={"Origin": "http://127.0.0.1:8765"}).status_code == 200
        assert client.put("/library/api/settings", json={}, headers={"Origin": "https://foreign.invalid"}).status_code == 403


def test_duplicate_host_and_origin_headers_are_rejected(owner):
    with local_client(owner) as client:
        assert client.get("/owner/identity", headers=[("Host", "127.0.0.1"), ("Host", "attacker.invalid")]).status_code == 400
        assert client.put("/api/settings", json={}, headers=[("Origin", "http://127.0.0.1"), ("Origin", "https://foreign.invalid")]).status_code == 403


@pytest.mark.parametrize("host", ["attacker.invalid", "localhost.attacker.invalid", "127.0.0.1.attacker.invalid", "user@localhost", "localhost:invalid", "localhost/path", "[::1]:0"])
def test_untrusted_or_malformed_host_is_rejected(owner, host):
    with local_client(owner) as client:
        assert client.get("/owner/identity", headers={"Host": host}).status_code == 400


def test_ipv6_loopback_and_localhost_are_allowed(owner):
    # TestClient's transport does not parse bracketed IPv6 URL ports. Supply
    # the real owner authority as Host while keeping its transport URL IPv4.
    for host, address in (("[::1]:5180", "::1"), ("localhost:5180", "127.0.0.1")):
        with TestClient(owner.app, base_url="http://127.0.0.1", client=(address, 50000)) as client:
            assert client.get("/owner/identity", headers={"Host": host}).status_code == 200
            assert client.put("/api/settings", json={}, headers={"Host": host, "Origin": "http://" + host}).status_code == 200


@pytest.mark.parametrize("headers", [
    {"Forwarded": "host=127.0.0.1;proto=https"},
    {"X-Forwarded-Host": "127.0.0.1"}, {"X-Forwarded-Proto": "https"},
    {"X-Forwarded-For": "127.0.0.1"},
])
def test_forwarded_authority_and_client_spoofing_are_rejected(owner, headers):
    with local_client(owner) as client:
        assert client.get("/owner/identity", headers=headers).status_code == 400


def test_every_mutating_route_rejects_foreign_origin_before_handler(owner, tmp_path):
    # OpenAPI expands included routers, including FastAPI's deferred routers.
    routes = [(path, method.upper()) for path, operations in owner.app.openapi()["paths"].items()
              for method in operations if method.upper() in {"POST", "PUT", "PATCH", "DELETE"}]
    assert {"/api/settings", "/api/research", "/api/bundles/import", "/api/acoustic/query"} <= {path for path, _ in routes}
    with local_client(owner) as client:
        for path, method in routes:
            url = re.sub(r"\{[^}]+\}", "fixture", path)
            response = client.request(method, url, json={}, headers={"Origin": "https://foreign.invalid"})
            assert response.status_code == 403, (method, path, response.text)
    assert not (tmp_path / "settings.json").exists()
    assert not (tmp_path / "index.sqlite").exists()


@pytest.mark.parametrize("headers", [
    {"Origin": "null"}, {"Origin": "http://127.0.0.1:5180"},
    {"Origin": "https://127.0.0.1"}, {"Origin": "http://127.0.0.1/path"},
    {"Origin": "http://user@127.0.0.1"}, {"Sec-Fetch-Site": "cross-site"},
    {"Origin": "http://127.0.0.1", "Sec-Fetch-Site": "same-site"},
])
def test_origin_and_browser_metadata_cannot_bypass_mutation_boundary(owner, headers):
    with local_client(owner) as client:
        assert client.put("/api/settings", json={}, headers=headers).status_code == 403


def test_remote_client_cannot_claim_local_authority(owner):
    with TestClient(owner.app, base_url="http://127.0.0.1", client=("203.0.113.10", 50000)) as client:
        assert client.get("/owner/identity").status_code == 403


def test_explicit_remote_mode_authenticates_reads_and_writes(owner, monkeypatch):
    token = "fixture-only-access-token-32-characters"
    monkeypatch.setattr(owner, "_REQUEST_BOUNDARY", RequestBoundary(frozenset({"owner.example.invalid"}), token))
    with TestClient(owner.app, base_url="https://owner.example.invalid", client=("203.0.113.10", 50000)) as client:
        assert client.get("/owner/identity").status_code == 401
        assert client.put("/api/settings", json={}).status_code == 401
        assert client.get("/owner/identity", headers={"Authorization": "Bearer incorrect"}).status_code == 401
        headers = {"Authorization": "Bearer " + token}
        assert client.get("/owner/identity", headers=headers).status_code == 200
        assert client.put("/api/settings", json={}, headers={**headers, "Origin": "https://foreign.invalid"}).status_code == 403
        assert client.put("/api/settings", json={}, headers={**headers, "Origin": "https://owner.example.invalid"}).status_code == 200


def test_workspace_admission_remains_required_after_owner_admission(owner, monkeypatch):
    monkeypatch.setattr(owner, "_WORKSPACE_ID", "fixture-workspace")
    monkeypatch.setattr(owner, "_WORKSPACE_GENERATION", "fixture-generation")
    with local_client(owner) as client:
        assert client.put("/api/settings", json={}).status_code == 409
        headers = {"X-Centaur-Workspace": "fixture-workspace", "X-Centaur-Generation": "fixture-generation", "X-Centaur-Binding": owner._WORKSPACE_BINDING}
        assert client.put("/api/settings", json={}, headers=headers).status_code == 200


def test_startup_requires_explicit_authenticated_nonloopback_mode(owner, monkeypatch):
    calls = []
    import uvicorn
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: calls.append(kwargs))
    monkeypatch.setenv("AKOUSMATA_HOST", "127.0.0.1")
    owner.main()
    assert calls[-1]["host"] == "127.0.0.1" and calls[-1]["proxy_headers"] is False
    monkeypatch.setenv("AKOUSMATA_HOST", "0.0.0.0")
    with pytest.raises(ValueError, match="Non-loopback"):
        owner.main()
    monkeypatch.setenv("AKOUSMATA_ACCESS_TOKEN", "fixture-only-access-token-32-characters")
    monkeypatch.setenv("AKOUSMATA_ALLOWED_HOSTS", "owner.example.invalid")
    monkeypatch.setattr(owner, "_REQUEST_BOUNDARY", RequestBoundary.from_env())
    owner.main()
    assert calls[-1]["host"] == "0.0.0.0"


@pytest.mark.parametrize("token,hosts", [("", "owner.example.invalid"), ("short", ""), ("fixture-only-access-token-32-characters", "owner.example.invalid:5180")])
def test_remote_configuration_cannot_silently_weaken_boundary(monkeypatch, token, hosts):
    monkeypatch.setenv("AKOUSMATA_ACCESS_TOKEN", token)
    monkeypatch.setenv("AKOUSMATA_ALLOWED_HOSTS", hosts)
    with pytest.raises(ValueError):
        RequestBoundary.from_env()
