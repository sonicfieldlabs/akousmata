"""Capture each launcher's app in a fresh interpreter without opening a service."""
import json
import subprocess
import sys


SCRIPT = '''
import json, runpy, sys, uvicorn

def capture(app, **_kw):
    print(json.dumps(sorted((path, sorted(methods)) for path, methods in app.openapi()["paths"].items())))
uvicorn.run = capture
mode = sys.argv[1]
if mode == "module":
    runpy.run_module("akousmata_app.server", run_name="__main__", alter_sys=True)
else:
    from akousmata_app import server
    if mode == "console": server.main()
    elif mode == "file": runpy.run_path(server.__file__, run_name="__main__")
    else: capture(server.app)
'''


def test_supported_launchers_have_complete_route_parity():
    captured = []
    for mode in ["import", "console", "module", "file"]:
        result = subprocess.run([sys.executable, "-I", "-c", SCRIPT, mode], check=True, capture_output=True, text=True)
        captured.append(json.loads(result.stdout))
    assert captured == [captured[0]] * 4
    paths = {path for path, _methods in captured[0]}
    assert {"/api/bundles/import", "/api/research/proposals", "/api/capabilities", "/api/score"} <= paths
