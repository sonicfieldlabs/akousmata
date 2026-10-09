"""Exercise research proposals in an installed runtime without dev dependencies.

Run with Python -I, passing the synthetic research-workflow fixture explicitly.
Only a newly created temporary store is written; no service or model is started.
"""
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import sys
import tempfile

import akousma
import akousmata_app
import akouo_contract
from akousmata_app import research_proposals


def main():
    prefix = Path(sys.prefix).resolve()
    for module in (akousma, akousmata_app, akouo_contract):
        if not Path(module.__file__).resolve().is_relative_to(prefix):
            raise AssertionError("Expected installed packages, not sibling source")
    if importlib.util.find_spec("pytest") is not None:
        raise AssertionError("Use a minimal runtime without pytest/dev dependencies")
    fixture = json.loads(Path(sys.argv[1]).read_text())
    with tempfile.TemporaryDirectory(prefix="akousmata-installed-research-") as temporary:
        with akousma.AkousmataStore(Path(temporary)) as store:
            for record in fixture["sources"]:
                store.put(record)
            receipt = research_proposals.submit(store, fixture["request"])
            assert receipt["state"] == "complete"
            assert store.get(fixture["request"]["record_id"])
            assert research_proposals.submit(store, fixture["request"])["replayed"]
            assert all(store.get(record["akousma_id"]) == record for record in fixture["sources"])
    print(json.dumps({"minimal_installed_research": "passed", "proposal_and_retry": "passed",
                      "sources_preserved": True, "live_store_changed": False,
                      "versions": {name: importlib.metadata.version(name)
                                   for name in ("akousma", "akousmata", "akouo-contract")}}))


if __name__ == "__main__":
    main()
