"""Akousmata navigator tests over an isolated temp store."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import wave
import json
from pathlib import Path
from unittest.mock import patch

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
        os.environ["AKOUSMATA_WATCHER"] = "0"
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
        os.environ.pop("AKOUSMATA_WATCHER", None)
        self.tmp.cleanup()

    def _manual_with_audio(self, summary="rain on the skylight", tags=("rain",)):
        source = Path(self.tmp.name) / "clip.wav"
        if not source.exists():
            with wave.open(str(source), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(16000)
                handle.writeframes(b"\x00\x00" * 1600)
        response = self.client.post("/api/records", json={
            "summary": summary, "tags": list(tags), "kind": "file", "audio_path": str(source),
        })
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["record"]

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
        self.assertEqual(entry["contract"], "akousmata/v0.2")
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
        # the child's outgoing edges left with it; nothing dangles
        self.assertEqual(lint["store"]["dangling_relations"], [])
        self.assertEqual(lint["store"]["dangling_parents"], [])
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

    def test_constellations_crud_and_resolve(self):
        created = self.client.post("/api/constellations", json={
            "name": "harbor dawn walk", "note": "the harbor series in listening order",
        }).json()["constellation"]
        self.client.post(f"/api/constellations/{created['id']}/records", json={"akousma_id": self.parent_id})
        self.client.post(f"/api/constellations/{created['id']}/records", json={"akousma_id": self.child_id})
        resolved = self.client.get(f"/api/constellations/{created['id']}").json()["constellation"]
        self.assertEqual([m["akousma_id"] for m in resolved["members"]], [self.parent_id, self.child_id])
        self.assertEqual(resolved["playable_count"], 0)  # neither has stored audio bytes
        # a forgotten member stays visible as absence
        self.client.post(f"/api/records/{self.child_id}/forget", json={"delete_audio": False})
        resolved = self.client.get(f"/api/constellations/{created['id']}").json()["constellation"]
        self.assertTrue(resolved["members"][1]["missing"])
        # remove + delete
        self.client.delete(f"/api/constellations/{created['id']}/records/{self.parent_id}")
        resolved = self.client.get(f"/api/constellations/{created['id']}").json()["constellation"]
        self.assertEqual(len(resolved["members"]), 1)
        self.assertEqual(self.client.delete(f"/api/constellations/{created['id']}").json()["deleted"], created["id"])
        self.assertEqual(self.client.get(f"/api/constellations/{created['id']}").status_code, 404)
        self.assertEqual(self.client.post("/api/constellations", json={"name": "  "}).status_code, 400)

    def test_timeline_buckets(self):
        data = self.client.get("/api/timeline", params={"bucket": "year"}).json()
        self.assertEqual(data["total"], 2)
        self.assertEqual(len(data["buckets"]), 1)
        self.assertEqual(data["buckets"][0]["by_app"], {"oida": 1, "germ": 1})
        self.assertIn("harbor", data["buckets"][0]["top_tags"])
        season = self.client.get("/api/timeline", params={"bucket": "season"}).json()
        self.assertTrue(season["buckets"][0]["bucket"].endswith("JJA"))
        self.assertTrue(season["recurrence_rhythms"]["peak_weekday"])
        self.assertEqual(self.client.get("/api/timeline", params={"bucket": "hour"}).status_code, 400)

    def test_similar_finds_kin_with_basis(self):
        data = self.client.get(f"/api/records/{self.parent_id}/similar").json()
        hits = {hit["card"]["akousma_id"]: hit for hit in data["similar"]}
        self.assertIn(self.child_id, hits)
        self.assertGreater(hits[self.child_id]["score"], 0)
        self.assertTrue(hits[self.child_id]["basis"])
        self.assertEqual(self.client.get("/api/records/akm_missing/similar").status_code, 404)

    def test_similar_uses_stored_local_embeddings(self):
        store = akousma.AkousmataStore(self.tmp.name)
        try:
            parent = store.get(self.parent_id)
            child = store.get(self.child_id)
            parent.setdefault("extensions", {}).setdefault("akousmata.app", {})["embedding"] = [1.0, 0.0, 0.5]
            child.setdefault("extensions", {}).setdefault("akousmata.app", {})["embedding"] = [0.9, 0.1, 0.45]
            store.put(parent)
            store.put(child)
        finally:
            store.close()
        data = self.client.get(f"/api/records/{self.parent_id}/similar").json()
        hit = next(item for item in data["similar"] if item["card"]["akousma_id"] == self.child_id)
        self.assertTrue(any("local embedding cosine" in basis for basis in hit["basis"]))

    def test_diary_entry_and_digest(self):
        posted = self.client.post("/api/diary", json={
            "text": "morning: rain over the patio, a bus sighing two streets away",
            "tags": ["rain"], "place": "medellín",
        }).json()
        record = posted["record"]
        self.assertIn("diary", record["tags"])
        self.assertEqual(record["listening"]["human.note"]["payload"]["kind"], "diary")
        self.assertIn("rain over the patio", posted["digest"])
        page = self.client.get(f"/api/diary/{posted['day']}").json()
        self.assertIn("rain over the patio", page["markdown"])
        self.assertIn(posted["day"], self.client.get("/api/wiki").json()["pages"]["diary"])
        self.assertEqual(self.client.post("/api/diary", json={"text": "  "}).status_code, 400)

    def test_consent_audit_and_set(self):
        audit = self.client.get("/api/audit/consent").json()
        self.assertEqual(audit["total"], 2)
        self.assertEqual(audit["exportable"], 0)
        self.assertEqual(audit["totals"].get("unknown"), 2)
        response = self.client.post(f"/api/records/{self.parent_id}/consent", json={
            "consent_status": "owned", "rights_note": "recorded by me at the harbor",
        })
        record = response.json()["record"]
        self.assertEqual(record["provenance"]["consent_status"], "owned")
        self.assertEqual(record["extensions"]["akousmata.app"]["consent_set_by"], "human")
        audit = self.client.get("/api/audit/consent").json()
        self.assertEqual(audit["exportable"], 1)
        self.assertEqual(self.client.post(f"/api/records/{self.parent_id}/consent", json={"consent_status": "stolen"}).status_code, 400)
        self.assertEqual(self.client.post("/api/records/akm_missing/consent", json={"consent_status": "owned"}).status_code, 404)

    def test_export_pack_blocks_by_consent(self):
        import json as _json

        store = akousma.AkousmataStore(self.tmp.name)
        parent = store.get(self.parent_id)
        parent["annotations"] = {"private": "private field note"}
        parent.setdefault("extensions", {})["test.export"] = {
            "source_path": "$HOME/private/harbor.wav",
            "api_key": "do-not-export",
        }
        store.put(parent)
        store.close()
        self.client.post(f"/api/records/{self.parent_id}/consent", json={"consent_status": "owned"})
        result = self.client.post("/api/export", json={
            "name": "harbor pack", "akousma_ids": [self.parent_id, self.child_id],
        }).json()
        self.assertEqual(result["included"], 1)
        self.assertEqual(len(result["excluded"]), 1)
        self.assertEqual(result["excluded"][0]["akousma_id"], self.child_id)
        self.assertIn("consent_status", result["excluded"][0]["reason"])
        pack_root = Path(result["path"])
        self.assertTrue((pack_root / "manifest.json").exists())
        self.assertTrue(Path(result["archive"]).exists())
        lines = (pack_root / "records" / "records.jsonl").read_text().strip().splitlines()
        shipped = _json.loads(lines[0])
        self.assertEqual(shipped["akousma_id"], self.parent_id)
        self.assertNotIn("annotations", shipped)
        self.assertNotIn("akousmata.app", shipped.get("extensions") or {})
        serialized = _json.dumps(shipped)
        self.assertNotIn("/U[s]ers/", serialized)
        self.assertNotIn("do-not-export", serialized)
        wiki_page = (pack_root / "wiki" / f"{self.parent_id}.md").read_text()
        self.assertNotIn("private field note", wiki_page)
        packs = self.client.get("/api/exports").json()["packs"]
        self.assertEqual(packs[0]["included"], 1)
        self.assertEqual(self.client.post("/api/export", json={"name": "empty"}).status_code, 400)

    def test_listen_again_requires_audio_and_reachable_oida(self):
        # no resolvable audio → 409
        self.assertEqual(
            self.client.post(f"/api/records/{self.parent_id}/listen-again", json={}).status_code, 409,
        )
        # audio but oída unreachable → 502
        record = self._manual_with_audio()
        self.client.put("/api/settings", json={"oida_url": "http://127.0.0.1:9"})
        response = self.client.post(f"/api/records/{record['akousma_id']}/listen-again", json={"preset": "field"})
        self.assertEqual(response.status_code, 502)
        self.assertIn("oída", response.json()["detail"])

    def test_listen_again_files_gateway_result_on_same_record(self):
        record = self._manual_with_audio()
        gateway = {
            "contract": "oida/gateway/v0.2",
            "perception_path": "oida_owned",
            "listening_event": {
                "id": "evt_fresh",
                "aggregate": {"title": "Fresh rain", "short_summary": "Rain and a distant bus.", "detailed_summary": "A new pass."},
                "routes": [{"route_id": "field-listener"}],
            },
            "command_output": {
                "claim_summary": {"heard": [{"statement": "Rain is audible."}]},
                "outputs": [{"apparatus": {"substrate": "hybrid_agent_stack"}}],
            },
        }

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps(gateway).encode("utf-8")

        with patch("urllib.request.urlopen", return_value=Response()):
            response = self.client.post(f"/api/records/{record['akousma_id']}/listen-again", json={"preset": "field"})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["namespace"].startswith("akousmata.listen_again"))
        self.assertEqual(body["listening"]["contract"], "akousmata/v0.2")
        self.assertEqual(body["listening"]["payload"]["source_contract"], "oida/gateway/v0.2")
        self.assertEqual(body["listening"]["payload"]["event_id"], "evt_fresh")
        self.assertEqual(body["listening"]["payload"]["claims"]["heard"][0]["statement"], "Rain is audible.")

    def test_watcher_status_shape(self):
        status = self.client.get("/api/watcher").json()
        self.assertFalse(status["enabled"])  # disabled under tests
        for key in ("started_at", "last_ingest_at", "ingested_count", "last_lint_at", "last_lint_issues"):
            self.assertIn(key, status)

    def test_watcher_reconciles_from_durable_cursor(self):
        first = self.client.post("/api/watcher/run", params={"lint": True}).json()
        second = self.client.post("/api/watcher/run", params={"lint": False}).json()
        self.assertEqual(first["ingested"], 2)
        self.assertEqual(second["ingested"], 0)
        self.assertTrue((Path(self.tmp.name) / "watcher-state.json").exists())
        self.assertTrue((Path(self.tmp.name) / "wiki" / "records" / f"{self.parent_id}.md").exists())

    def test_settings_roundtrip_masks_key(self):
        saved = self.client.put("/api/settings", json={
            "llm": {"provider": "openai_compatible", "api_key": "sk-test-1234", "model": "grok-4"},
            "watcher": {"enabled": False, "ingest_seconds": 5, "lint_minutes": 10},
        }).json()
        self.assertTrue(saved["llm"]["api_key"].startswith("•"))
        self.assertTrue(saved["llm"]["configured"])
        self.assertFalse(saved["watcher"]["enabled"])
        # round-tripping the masked key must not clobber the stored one
        again = self.client.put("/api/settings", json={"llm": {"provider": "openai_compatible", "api_key": saved["llm"]["api_key"]}}).json()
        self.assertTrue(again["llm"]["api_key"].endswith("1234"))


if __name__ == "__main__":
    unittest.main()
