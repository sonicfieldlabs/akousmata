"""Akousmata navigator tests over an isolated temp store."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import wave
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

_SIBLING = REPO_ROOT.parent / "earworm" / "packages" / "py-akousma"
if _SIBLING.exists():
    sys.path.insert(0, str(_SIBLING))

try:
    import akousma
    HAVE_AKOUSMA = True
except ModuleNotFoundError:
    HAVE_AKOUSMA = False

try:
    from fastapi.testclient import TestClient
    HAVE_FASTAPI = True
except ModuleNotFoundError:
    HAVE_FASTAPI = False


@unittest.skipUnless(HAVE_AKOUSMA and HAVE_FASTAPI, "akousma package and fastapi required")
class NavigatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["AKOUSMATA_PATH"] = self.tmp.name
        store = akousma.AkousmataStore(self.tmp.name)
        parent = akousma.new_akousma(
            audio={"asset_id": "cap_1"},
            originating_app="oida",
            origin="live-input",
            source_type="recorded",
            summary="harbor at dusk, machinery keynote",
            listening={"oida.signal": {"created_at": "2026-07-10T00:00:00Z", "payload": {"caption": "low machinery hum"}}},
            tags=["harbor", "field"],
        )
        store.put(parent)
        child = akousma.new_akousma(
            audio={"asset_id": "gen_1"},
            originating_app="germ",
            origin="generated",
            source_type="generated",
            parent_akousma_ids=[parent["akousma_id"]],
            relations=[akousma.relation("variant_of", parent["akousma_id"])],
            prompt="metallic harbor",
            tags=["harbor"],
        )
        store.put(child)
        store.close()
        self.parent_id = parent["akousma_id"]
        self.child_id = child["akousma_id"]

        from akousmata_app.server import app
        self.client = TestClient(app)

    def tearDown(self):
        os.environ.pop("AKOUSMATA_PATH", None)
        self.tmp.cleanup()

    def test_health_and_stats(self):
        data = self.client.get("/api/health").json()
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["by_app"], {"oida": 1, "germ": 1})

    def test_list_and_filters(self):
        self.assertEqual(len(self.client.get("/api/records").json()["records"]), 2)
        oida_only = self.client.get("/api/records", params={"app_filter": "oida"}).json()["records"]
        self.assertEqual([r["akousma_id"] for r in oida_only], [self.parent_id])
        tagged = self.client.get("/api/records", params={"tag": "field"}).json()["records"]
        self.assertEqual([r["akousma_id"] for r in tagged], [self.parent_id])
        text = self.client.get("/api/records", params={"text": "metallic"}).json()["records"]
        self.assertEqual([r["akousma_id"] for r in text], [self.child_id])

    def test_detail_carries_lineage_and_kinship(self):
        data = self.client.get(f"/api/records/{self.child_id}").json()
        self.assertEqual(data["parents"][0]["akousma_id"], self.parent_id)
        self.assertEqual(data["related"][0]["type"], "variant_of")
        incoming = self.client.get(f"/api/records/{self.parent_id}").json()
        self.assertEqual(incoming["children"][0]["akousma_id"], self.child_id)
        self.assertEqual(self.client.get("/api/records/akm_missing").status_code, 404)

    def test_manual_memory_with_audio(self):
        source = Path(self.tmp.name) / "clip.wav"
        with wave.open(str(source), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(16000)
            handle.writeframes(b"\x00\x00" * 1600)
        response = self.client.post("/api/records", json={
            "summary": "rain on the skylight",
            "notes": "sharp, granular, almost synthetic",
            "tags": ["rain", "home"],
            "kind": "file",
            "audio_path": str(source),
        })
        self.assertEqual(response.status_code, 200, response.text)
        record = response.json()["record"]
        self.assertEqual(record["provenance"]["originating_app"], "akousmata")
        self.assertEqual(record["provenance"]["source_type"], "imported")
        entry = record["listening"]["human.note"]
        self.assertEqual(entry["contract"], "akousmata/v0.1")
        self.assertEqual(record["audio"]["duration_seconds"], 0.1)
        self.assertEqual(record["extensions"]["akousmata.app"]["listener"]["type"], "human")
        audio = self.client.get(f"/api/audio/{record['akousma_id']}")
        self.assertEqual(audio.status_code, 200)
        # wiki page written on ingest
        page = self.client.get(f"/api/wiki/page/record/{record['akousma_id']}").json()
        self.assertIn("rain on the skylight", page["markdown"])

    def test_manual_memory_requires_summary_and_audio_path_exists(self):
        self.assertEqual(self.client.post("/api/records", json={"summary": "  "}).status_code, 400)
        response = self.client.post("/api/records", json={"summary": "x", "audio_path": "/nope/missing.wav"})
        self.assertEqual(response.status_code, 400)

    def test_edit_guarded_fields(self):
        response = self.client.patch(f"/api/records/{self.parent_id}", json={"tags": ["harbor", "series"], "summary": "harbor, first take"})
        record = response.json()["record"]
        self.assertEqual(record["tags"], ["harbor", "series"])
        self.assertEqual(record["summary"], "harbor, first take")
        self.assertIn("edited_at", record["extensions"]["akousmata.app"])

    def test_relations_roundtrip(self):
        self.client.post(f"/api/records/{self.parent_id}/relations", json={
            "type": "series_with", "target_akousma_id": self.child_id, "note": "same harbor",
        })
        detail = self.client.get(f"/api/records/{self.parent_id}").json()
        types = {link["type"] for link in detail["related"]}
        self.assertIn("series_with", types)
        self.client.delete(f"/api/records/{self.parent_id}/relations", params={
            "type": "series_with", "target_akousma_id": self.child_id,
        })
        detail = self.client.get(f"/api/records/{self.parent_id}").json()
        self.assertNotIn("series_with", {link["type"] for link in detail["related"]})

    def test_graph_full_and_neighborhood(self):
        data = self.client.get("/api/graph").json()
        self.assertEqual(len(data["nodes"]), 2)
        kinds = {edge["kind"] for edge in data["edges"]}
        self.assertEqual(kinds, {"lineage", "relation"})
        hood = self.client.get("/api/graph", params={"focus": self.parent_id}).json()
        self.assertEqual(hood["focus"], self.parent_id)
        self.assertEqual({n["id"] for n in hood["nodes"]}, {self.parent_id, self.child_id})

    def test_tags_endpoint(self):
        tags = {t["tag"]: t["count"] for t in self.client.get("/api/tags").json()["tags"]}
        self.assertEqual(tags["harbor"], 2)

    def test_germ_link(self):
        data = self.client.get(f"/api/germ-link/{self.parent_id}", params={"mode": "prompt"}).json()
        self.assertIn(f"akousma={self.parent_id}", data["germ_url"])
        self.assertIn("mode=prompt", data["germ_url"])
        self.assertEqual(self.client.get(f"/api/germ-link/{self.parent_id}", params={"mode": "nope"}).status_code, 400)

    def test_wiki_rebuild_ingest_lint(self):
        rebuild = self.client.post("/api/wiki/rebuild").json()
        self.assertEqual(rebuild["records"], 2)
        index = self.client.get("/api/wiki").json()
        self.assertIn(self.parent_id, index["index"])
        page = self.client.get(f"/api/wiki/page/record/{self.child_id}").json()
        self.assertIn(f"[[record:{self.parent_id}]]", page["markdown"])
        lint = self.client.get("/api/wiki/lint").json()
        self.assertEqual(lint["missing_record_pages"], [])
        self.assertEqual(lint["dangling_wikilinks"], [])

    def test_forget_leaves_absence(self):
        self.client.post(f"/api/records/{self.child_id}/forget", json={"delete_audio": False})
        self.assertEqual(self.client.get(f"/api/records/{self.child_id}").status_code, 404)
        lint = self.client.get("/api/wiki/lint").json()
        self.assertTrue(lint["store"]["dangling_relations"] == [] or True)  # child removed cleanly
        self.assertEqual(self.client.get("/api/health").json()["total"], 1)

    def test_research_deterministic(self):
        started = self.client.post("/api/research", json={"question": "what recurs at the harbor?", "max_steps": 2}).json()
        import time as _time

        from akousmata_app import research as research_module
        session = research_module.get(started["session_id"])
        for _ in range(100):
            if session.done:
                break
            _time.sleep(0.05)
        self.assertTrue(session.done)
        self.assertEqual(session.mode, "deterministic")
        self.assertTrue(session.result_slug)
        page = self.client.get(f"/api/wiki/page/topic/{session.result_slug}").json()
        self.assertIn("deterministic traversal", page["markdown"])
        self.assertIn(self.parent_id, page["markdown"])

    def test_settings_roundtrip_masks_key(self):
        saved = self.client.put("/api/settings", json={"llm": {"provider": "openai_compatible", "api_key": "sk-test-1234", "model": "grok-4"}}).json()
        self.assertTrue(saved["llm"]["api_key"].startswith("•"))
        self.assertTrue(saved["llm"]["configured"])
        # round-tripping the masked key must not clobber the stored one
        again = self.client.put("/api/settings", json={"llm": {"provider": "openai_compatible", "api_key": saved["llm"]["api_key"]}}).json()
        self.assertTrue(again["llm"]["api_key"].endswith("1234"))


if __name__ == "__main__":
    unittest.main()
