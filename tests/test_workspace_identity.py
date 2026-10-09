import os
import subprocess
import sys


def test_workspace_identity_does_not_open_store_and_mutations_are_bound(tmp_path):
    code = """
from pathlib import Path
from fastapi.testclient import TestClient
from akousmata_app.server import app
with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
    identity = client.get('/owner/identity').json()
    assert identity['owner'] == 'akousmata' and len(identity['binding']) == 64
    assert not Path(__import__('os').environ['AKOUSMATA_PATH']).exists()
    assert client.post('/api/settings', json={}).status_code == 409
"""
    env = dict(os.environ)
    env.update(
        LISTENINGSTACK_WORKSPACE_ID="ws_0123456789abcdef01234567",
        LISTENINGSTACK_WORKSPACE_GENERATION="generation-one",
        AKOUSMATA_PATH=str(tmp_path / "memory"),
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_owner_transport_does_not_follow_redirects():
    import threading
    import urllib.error
    import urllib.request
    from http.server import BaseHTTPRequestHandler, HTTPServer

    import pytest
    from akousmata_app.server import _owner_open

    visited = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            visited.append(self.path)
            self.send_response(302)
            self.send_header('Location', '/redirected')
            self.end_headers()

        def log_message(self, *_args):
            pass

    with HTTPServer(('127.0.0.1', 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request = urllib.request.Request(
                f'http://127.0.0.1:{server.server_port}/owner/identity',
                headers={'X-Centaur-Binding': 'fixture-binding'},
            )
            with pytest.raises(urllib.error.HTTPError) as error:
                _owner_open(request, timeout=2)
            assert error.value.code == 302
            assert visited == ['/owner/identity']
        finally:
            server.shutdown()
            thread.join(timeout=2)
