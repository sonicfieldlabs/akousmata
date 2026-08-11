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
        metadata = {"summary": summary, "tags": list(tags), "kind": "file", "heard": True}
        response = self.client.post(
            "/api/records/import",
            data={"metadata": json.dumps(metadata)},
            files={"audio": ("clip.wav", source.read_bytes(), "audio/wav")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["record"]

    def test_health_and_stats(self):
        data = self.client.get("/api/health").json()
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["by_app"], {"oida": 1, "germ": 1})
        self.assertEqual(data["accountable"], 0)
        self.assertEqual(data["with_disagreement"], 0)
        self.assertEqual(data["with_route_decisions"], 0)
        self.assertEqual(data["forgetting_receipt_count"], 0)

    def test_accountability_audit_and_filters(self):
        initial = self.client.get("/api/audit/accountability").json()
        self.assertEqual(initial["legacy"], 2)
        self.assertEqual(initial["accountable"], 0)

        manual = self.client.post("/api/records", json={
            "summary": "a bell heard without a recording",
            "notes": "one short decay",
            "heard": True,
        }).json()["record"]
        audit = self.client.get("/api/audit/accountability").json()
        self.assertEqual(audit["accountable"], 1)
        self.assertEqual(audit["legacy"], 2)
        item = next(entry for entry in audit["items"] if entry["akousma_id"] == manual["akousma_id"])
        self.assertEqual(item["listening_count"], 1)
        self.assertEqual(item["honest_absence_count"], 1)
        self.assertEqual(item["route_decision_count"], 1)
        self.assertEqual(item["stop_decision_count"], 0)
        self.assertEqual(item["issues"], [])

        accountable = self.client.get("/api/records", params={"accountable": True}).json()["records"]
        self.assertEqual([entry["akousma_id"] for entry in accountable], [manual["akousma_id"]])
        legacy = self.client.get("/api/records", params={"accountable": False}).json()["records"]
        self.assertEqual({entry["akousma_id"] for entry in legacy}, {self.parent_id, self.child_id})
        decided = self.client.get("/api/records", params={"route_decision": True}).json()["records"]
        self.assertEqual([entry["akousma_id"] for entry in decided], [manual["akousma_id"]])

    def test_decision_only_memory_is_complete_without_claiming_a_hearing(self):
        decision = akousma.route_decision(
            "decision-quiet-hours",
            gate="capture",
            outcome="refuse",
            subject="quiet-hours capture request",
            reason="The adopted covenant closed the ear before capture.",
            actor="oida-covenant-gate",
            producer_contract="akouo/v0.9",
            requires_confirmation=False,
        )
        decision["receipt"] = {
            "created_at": "2026-07-27T12:00:00Z",
            "actor": "oida-covenant-gate",
            "result": "listening did not begin",
            "recovery": "Revise the covenant before making a new request.",
        }
        auditum = akousma.auditum(
            honest_absences=[{
                "id": "absence-quiet-hours",
                "kind": "refused",
                "subject": "audio capture",
                "attributed_to": "quiet-hours/1",
                "listening_id": None,
                "count": 1,
            }],
            route_decisions=[decision],
        )
        record = akousma.new_akousma(
            audio=None,
            subject="quiet-hours capture request",
            originating_app="oida",
            source_type="unknown",
            origin="live-input",
            summary="Listening was refused before capture.",
            auditum=auditum,
        )
        store = akousma.AkousmataStore(self.tmp.name)
        try:
            store.put(record)
        finally:
            store.close()

        card = next(
            item for item in self.client.get("/api/records", params={"stop_decision": True}).json()["records"]
            if item["akousma_id"] == record["akousma_id"]
        )
        self.assertTrue(card["decision_only"])
        self.assertFalse(card["has_audio"])
        self.assertEqual(card["listening_count"], 0)
        self.assertEqual(card["route_decision_count"], 1)
        self.assertEqual(card["stop_decision_count"], 1)
        detail = self.client.get(f"/api/records/{record['akousma_id']}").json()
        self.assertEqual(detail["accountability"]["status"], "accountable")
        self.client.post(f"/api/wiki/ingest/{record['akousma_id']}")
        page = self.client.get(f"/api/wiki/page/record/{record['akousma_id']}").json()["markdown"]
        self.assertIn("route decision", page)
        self.assertIn("listening did not begin", page)

    def test_plural_listening_is_not_an_ear_swarm_without_an_ensemble(self):
        created_at = "2026-07-27T12:00:00Z"
        listenings = [
            {
                "listening_id": "listen-a",
                "listener_id": "listener-a",
                "listener_type": "human",
                "created_at": created_at,
                "report_namespace": "human.a",
                "contract": "akouo/v0.9",
                "route": ["/listen"],
                "route_decision_refs": ["decision-a"],
            },
            {
                "listening_id": "listen-b",
                "listener_id": "listener-b",
                "listener_type": "agent",
                "created_at": created_at,
                "report_namespace": "agent.b",
                "contract": "akouo/v0.9",
                "route": ["/listen"],
                "route_decision_refs": ["decision-b"],
            },
        ]
        decisions = [
            akousma.route_decision(
                f"decision-{suffix}",
                gate="input",
                outcome="proceed",
                subject="shared listening object",
                reason="The participant received the declared object.",
                actor=f"listener-{suffix}",
                listening_id=f"listen-{suffix}",
                requires_confirmation=False,
            )
            for suffix in ("a", "b")
        ]
        record = akousma.new_akousma(
            audio={"asset_id": "plural-object"},
            originating_app="akousmata",
            source_type="recorded",
            origin="file",
            listening={
                "human.a": {"contract": "akouo/v0.9", "payload": {"summary": "first position"}},
                "agent.b": {"contract": "akouo/v0.9", "payload": {"summary": "second position"}},
            },
            auditum=akousma.auditum(listenings=listenings, route_decisions=decisions),
        )
        store = akousma.AkousmataStore(self.tmp.name)
        try:
            store.put(record)
        finally:
            store.close()
        first = self.client.get("/api/audit/accountability").json()
        item = next(entry for entry in first["items"] if entry["akousma_id"] == record["akousma_id"])
        self.assertTrue(item["plural_listening"])
        self.assertFalse(item["ear_swarm"])

        swarm_auditum = akousma.auditum(
            listenings=listenings,
            route_decisions=decisions,
            ensemble={
                "id": "ensemble-harbor",
                "kind": "ear_swarm",
                "listening_ids": ["listen-a", "listen-b"],
                "influence_edges": [{
                    "from_listening_id": "listen-a",
                    "to_listening_id": "listen-b",
                    "effect": "The first pass redirected attention to recurrence.",
                }],
                "permissions_preserved": True,
                "disagreements_preserved": True,
                "dissolution_rule": "The ensemble dissolves after this bounded comparison.",
            },
            revision={
                "revision_id": akousma.new_id("rev"),
                "revises_akousma_id": record["akousma_id"],
                "reason": "the participants later declared attributable influence",
                "changes": ["explicit ear-swarm ensemble declaration"],
                "created_at": created_at,
            },
        )
        swarm_record = akousma.new_akousma(
            audio=dict(record["audio"]),
            originating_app="akousmata",
            source_type="recorded",
            origin="file",
            listening=dict(record["listening"]),
            relations=[akousma.relation("same_source_as", record["akousma_id"])],
            auditum=swarm_auditum,
        )
        store = akousma.AkousmataStore(self.tmp.name)
        try:
            store.put(swarm_record)
        finally:
            store.close()
        second = self.client.get("/api/audit/accountability").json()
        original = next(entry for entry in second["items"] if entry["akousma_id"] == record["akousma_id"])
        self.assertFalse(original["ear_swarm"])
        item = next(entry for entry in second["items"] if entry["akousma_id"] == swarm_record["akousma_id"])
        self.assertTrue(item["ear_swarm"])
        self.assertEqual(item["ensemble_kind"], "ear_swarm")

    def test_location_create_patch_and_map(self):
        created = self.client.post("/api/records", json={
            "summary": "river under the bridge",
            "tags": ["river"],
            "heard": True,
            "location": {"lat": 6.2442, "lon": -75.5812, "label": "puente de la 4 sur", "source": "gps"},
        })
        self.assertEqual(created.status_code, 200, created.text)
        record = created.json()["record"]
        self.assertEqual(record["location"]["label"], "puente de la 4 sur")
        self.assertEqual(record["location"]["source"], "gps")

        data = self.client.get("/api/map").json()
        self.assertEqual(data["located"], 1)
        self.assertEqual(data["unlocated"], 2)
        self.assertEqual(data["points"][0]["akousma_id"], record["akousma_id"])
        self.assertEqual(data["points"][0]["label"], "puente de la 4 sur")

        # location is listener-annotatable: geotag an existing memory, then clear it
        patched = self.client.patch(f"/api/records/{self.parent_id}", json={
            "location": {"lat": 43.36, "lon": -8.41, "label": "harbor"},
        })
        self.assertEqual(patched.status_code, 200, patched.text)
        self.assertEqual(patched.json()["record"]["location"]["source"], "manual")
        self.assertEqual(self.client.get("/api/map").json()["located"], 2)
        listed = self.client.get("/api/records").json()["records"]
        by_id = {item["akousma_id"]: item for item in listed}
        self.assertTrue(by_id[self.parent_id]["has_location"])
        self.assertFalse(by_id[self.child_id]["has_location"])

        cleared = self.client.patch(f"/api/records/{self.parent_id}", json={"location": {}})
        self.assertNotIn("location", cleared.json()["record"])
        self.assertEqual(self.client.get("/api/map").json()["located"], 1)

    def test_covenant_filter_and_card(self):
        from akousmata_app.paths import open_store, ensure_pyakousma

        ensure_pyakousma()
        import akousma

        store = open_store()
        try:
            under = akousma.new_akousma(
                audio={"asset_id": "cov1"},
                originating_app="oida",
                origin="live-input",
                summary="talk near the river, words withheld",
                covenant=akousma.covenant(
                    "river-covenant/2",
                    name="river covenant",
                    contract="akouo/v0.7",
                    extends=["algophonya/v7"],
                    withheld=[{"rule": "do_not_reveal", "subject": "transcript", "count": 1}],
                    commitments=1,
                ),
            )
            store.put(under)
        finally:
            store.close()

        listed = self.client.get("/api/records", params={"covenant": "river-covenant/2"}).json()["records"]
        self.assertEqual([r["akousma_id"] for r in listed], [under["akousma_id"]])
        self.assertEqual(listed[0]["covenant_id"], "river-covenant/2")
        empty = self.client.get("/api/records", params={"covenant": "no-such-covenant"}).json()["records"]
        self.assertEqual(empty, [])
        detail = self.client.get(f"/api/records/{under['akousma_id']}").json()
        self.assertEqual(detail["record"]["covenant"]["withheld"][0]["subject"], "transcript")

    def test_location_patch_validates(self):
        bad = self.client.patch(f"/api/records/{self.parent_id}", json={"location": {"lat": 123, "lon": 0}})
        self.assertEqual(bad.status_code, 400)
        missing = self.client.patch(f"/api/records/{self.parent_id}", json={"location": {"label": "nowhere"}})
        self.assertEqual(missing.status_code, 400)

    def test_export_strips_location(self):
        record = self._manual_with_audio(summary="located rain", tags=("rain", "geo"))
        self.client.patch(f"/api/records/{record['akousma_id']}", json={"location": {"lat": 6.2, "lon": -75.6}})
        self.client.post(f"/api/records/{record['akousma_id']}/consent", json={"consent_status": "owned"})
        result = self.client.post("/api/export", json={
            "name": "geo pack", "akousma_ids": [record["akousma_id"]],
            "include_audio": False, "include_wiki": False,
        }).json()
        jsonl = Path(result["path"]) / "records" / "records.jsonl"
        exported = json.loads(jsonl.read_text(encoding="utf-8").strip())
        self.assertEqual(exported["akousma_id"], record["akousma_id"])
        self.assertNotIn("location", exported)

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
        metadata = {
            "summary": "rain on the skylight",
            "notes": "sharp, granular, almost synthetic",
            "tags": ["rain", "home"],
            "kind": "file",
            "heard": True,
        }
        response = self.client.post(
            "/api/records/import",
            data={"metadata": json.dumps(metadata)},
            files={"audio": ("clip.wav", source.read_bytes(), "audio/wav")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        record = response.json()["record"]
        self.assertEqual(record["provenance"]["originating_app"], "akousmata")
        self.assertEqual(record["provenance"]["source_type"], "imported")
        entry = record["listening"]["human.note"]
        from akousmata_app import AKOUSMATA_CONTRACT
        self.assertEqual(entry["contract"], AKOUSMATA_CONTRACT)
        self.assertEqual(record["audio"]["duration_seconds"], 0.1)
        self.assertEqual(record["extensions"]["akousmata.app"]["listener"]["type"], "human")
        self.assertEqual(record["auditum"]["contract"], "earworm/auditum/v2")
        self.assertEqual(record["auditum"]["listenings"][0]["listener_type"], "human")
        self.assertEqual(record["auditum"]["route_decisions"][0]["outcome"], "proceed")
        audio = self.client.get(f"/api/audio/{record['akousma_id']}")
        self.assertEqual(audio.status_code, 200)
        # wiki page written on ingest
        page = self.client.get(f"/api/wiki/page/record/{record['akousma_id']}").json()
        self.assertIn("rain on the skylight", page["markdown"])
        self.assertIn("Accountable auditum", page["markdown"])

    def test_manual_memory_validates_summary_and_audio_upload(self):
        self.assertEqual(self.client.post("/api/records", json={"summary": "  "}).status_code, 400)
        legacy = self.client.post("/api/records", json={"summary": "x", "audio_path": "/nope/missing.wav"})
        self.assertEqual(legacy.status_code, 422)
        unsupported = self.client.post(
            "/api/records/import",
            data={"metadata": json.dumps({"summary": "x", "kind": "file"})},
            files={"audio": ("clip.txt", b"not audio", "text/plain")},
        )
        self.assertEqual(unsupported.status_code, 400)
        empty = self.client.post(
            "/api/records/import",
            data={"metadata": json.dumps({"summary": "x", "kind": "file"})},
            files={"audio": ("clip.wav", b"", "audio/wav")},
        )
        self.assertEqual(empty.status_code, 400)

    def _agent_listening_record(self, *, namespace="human.misleading_namespace", listener_type="agent"):
        created_at = "2026-08-11T12:00:00Z"
        listening_id = akousma.new_id("lst")
        decision_id = akousma.new_id("dec")
        target = akousma.new_akousma(
            audio={"asset_id": akousma.new_id("asset")},
            originating_app="oida",
            origin="file",
            source_type="imported",
            listening={namespace: {
                "contract": "oida/gateway/v0.6",
                "created_at": created_at,
                "summary": "machine account under a deliberately misleading namespace",
                "payload": {"summary": "machine pass"},
            }},
            auditum=akousma.auditum(
                listenings=[{
                    "listening_id": listening_id,
                    "listener_id": f"test-{listener_type}-listener",
                    "listener_type": listener_type,
                    "created_at": created_at,
                    "report_namespace": namespace,
                    "contract": "oida/gateway/v0.6",
                    "route": ["basic"],
                    "route_decision_refs": [decision_id],
                }],
                route_decisions=[akousma.route_decision(
                    decision_id,
                    gate="input",
                    outcome="proceed",
                    subject="test audio",
                    reason="The bounded test input was available.",
                    actor=f"test-{listener_type}-listener",
                    decided_at=created_at,
                    listening_id=listening_id,
                    requires_confirmation=False,
                )],
            ),
        )
        store = akousma.AkousmataStore(self.tmp.name)
        try:
            store.put(target)
        finally:
            store.close()
        return target

    def test_listener_classification_uses_auditum_types_and_notes_do_not_imply_heard(self):
        heard = self.client.post("/api/human-records", json={
            "summary": "a human heard the courtyard bell",
            "notes": "one decay",
            "heard": True,
        })
        self.assertEqual(heard.status_code, 200, heard.text)
        heard_record = heard.json()["record"]
        self.assertNotIn("audio", heard_record)
        heard_card = self.client.get(f"/api/records/{heard_record['akousma_id']}").json()["card"]
        self.assertEqual(heard_card["record_class"], "human")
        self.assertEqual(heard_card["listener_types"], ["human"])
        self.assertTrue(heard_card["owned_human_record"])
        self.assertTrue(heard_card["human_editable"])

        note = self.client.post("/api/human-records", json={
            "summary": "a note about an event I did not hear",
            "notes": "received from another person",
        })
        self.assertEqual(note.status_code, 200, note.text)
        note_record = note.json()["record"]
        self.assertEqual(note_record["auditum"]["listenings"][0]["listener_type"], "human")
        self.assertFalse(note_record["listening"]["human.note"]["payload"]["hearing_evidence"]["confirmed"])
        note_card = self.client.get(f"/api/records/{note_record['akousma_id']}").json()["card"]
        self.assertEqual(note_card["record_class"], "human")
        self.assertEqual(note_card["listener_types"], ["human"])

        agent = self._agent_listening_record()
        sensor = self._agent_listening_record(namespace="agent.misleading_sensor", listener_type="sensor")
        cards = {item["akousma_id"]: item for item in self.client.get("/api/records").json()["records"]}
        self.assertEqual(cards[agent["akousma_id"]]["record_class"], "agent")
        self.assertEqual(cards[agent["akousma_id"]]["listener_types"], ["agent"])
        self.assertEqual(cards[sensor["akousma_id"]]["record_class"], "plural_other")
        self.assertEqual(cards[sensor["akousma_id"]]["listener_types"], ["sensor"])
        self.assertEqual(cards[self.parent_id]["record_class"], "legacy")

        human_only = self.client.get("/api/records", params={"record_class": "human"}).json()["records"]
        self.assertEqual(
            {item["akousma_id"] for item in human_only},
            {heard_record["akousma_id"], note_record["akousma_id"]},
        )
        agents = self.client.get("/api/records", params={"listener_type": "agent"}).json()["records"]
        self.assertEqual([item["akousma_id"] for item in agents], [agent["akousma_id"]])
        self.assertEqual(self.client.get("/api/records", params={"listener_type": "machine"}).status_code, 400)

    def test_human_machine_links_are_typed_and_same_source_requires_verification(self):
        agent = self._agent_listening_record(namespace="anything.at.all")
        unverified = self.client.post("/api/human-records", json={
            "summary": "my position beside the agent pass",
            "same_source_as": agent["akousma_id"],
            "heard": True,
        })
        self.assertEqual(unverified.status_code, 400)

        linked = self.client.post("/api/human-records", json={
            "summary": "my position beside the agent pass",
            "notes": "the near bell was more prominent to me",
            "response_to": agent["akousma_id"],
            "same_source_as": agent["akousma_id"],
            "same_source_verified": True,
            "heard": True,
        })
        self.assertEqual(linked.status_code, 200, linked.text)
        record = linked.json()["record"]
        self.assertEqual(record["lineage"]["parent_akousma_ids"], [])
        self.assertEqual(
            {item["type"] for item in record["lineage"]["relations"]},
            {"response_to", "same_source_as"},
        )
        legacy_target = self.client.post("/api/human-records", json={
            "summary": "invalid legacy link", "response_to": self.parent_id,
        })
        self.assertEqual(legacy_target.status_code, 400)
        false_parent = self.client.post("/api/human-records", json={
            "summary": "invalid causal claim", "parent_akousma_ids": [agent["akousma_id"]],
        })
        self.assertEqual(false_parent.status_code, 400)

        from_machine = self.client.post(f"/api/records/{agent['akousma_id']}/relations", json={
            "type": "response_to", "target_akousma_id": record["akousma_id"],
        })
        self.assertEqual(from_machine.status_code, 403)

    def test_owned_human_edit_creates_a_new_revision_head(self):
        first_profile = self.client.get("/api/human-profile").json()
        second_profile = self.client.get("/api/human-profile").json()
        self.assertEqual(first_profile["listener_id"], second_profile["listener_id"])
        updated_profile = self.client.put("/api/human-profile", json={
            "display_name": "local listener", "privacy": "shared",
        })
        self.assertEqual(updated_profile.status_code, 200, updated_profile.text)

        created = self.client.post("/api/human-records", json={
            "summary": "first account of the rain",
            "notes": "steady rain",
            "tags": ["rain"],
            "heard": True,
        }).json()["record"]
        self.assertEqual(
            created["extensions"]["akousmata.app"]["human_record"]["display_name"],
            "local listener",
        )
        revised_response = self.client.post(f"/api/human-records/{created['akousma_id']}/revisions", json={
            "summary": "revised account of the rain",
            "notes": "steady rain with a distant bus",
            "tags": ["rain", "bus"],
            "kind": "heard_live",
            "heard": True,
            "reason": "I remembered the distant bus",
        })
        self.assertEqual(revised_response.status_code, 200, revised_response.text)
        revised = revised_response.json()["record"]
        self.assertNotEqual(revised["akousma_id"], created["akousma_id"])
        self.assertEqual(revised["auditum"]["revision"]["revises_akousma_id"], created["akousma_id"])
        self.assertIn("replaces", {item["type"] for item in revised["lineage"]["relations"]})

        original_detail = self.client.get(f"/api/records/{created['akousma_id']}").json()
        new_detail = self.client.get(f"/api/records/{revised['akousma_id']}").json()
        self.assertEqual(original_detail["record"]["summary"], "first account of the rain")
        self.assertFalse(original_detail["human_record"]["editable"])
        self.assertTrue(new_detail["human_record"]["editable"])
        self.assertEqual(len(new_detail["revision"]["history"]), 2)

        stale = self.client.post(f"/api/human-records/{created['akousma_id']}/revisions", json={
            "summary": "stale branch", "notes": "no", "heard": True, "reason": "should fail",
        })
        self.assertEqual(stale.status_code, 400)
        machine = self._agent_listening_record(namespace="agent.report")
        forbidden = self.client.post(f"/api/human-records/{machine['akousma_id']}/revisions", json={
            "summary": "rewrite machine", "notes": "no", "heard": True, "reason": "should fail",
        })
        self.assertEqual(forbidden.status_code, 403)
        core_patch = self.client.patch(f"/api/records/{machine['akousma_id']}", json={"listening": {}})
        self.assertEqual(core_patch.status_code, 422)
        curation = self.client.patch(f"/api/records/{machine['akousma_id']}/curation", json={"tags": ["reviewed"]})
        self.assertEqual(curation.status_code, 200)
        self.assertEqual(curation.json()["operation"], "library_curation")

        revisions = self.client.get("/api/records", params={"revision_of": created["akousma_id"]}).json()["records"]
        self.assertEqual([item["akousma_id"] for item in revisions], [revised["akousma_id"]])

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
        disabled = self.client.get(f"/api/germ-link/{self.parent_id}", params={"mode": "prompt"})
        self.assertEqual(disabled.status_code, 409)
        self.client.put("/api/settings", json={"germ_url": "http://127.0.0.1:5178"})
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
        response = self.client.post(
            f"/api/records/{self.child_id}/forget",
            json={"delete_audio": False, "actor": "listener-owner", "reason": "retention consent withdrawn"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        receipt = response.json()["receipt"]
        self.assertEqual(receipt["contract"], "earworm/forgetting-receipt/v1")
        self.assertEqual(receipt["akousma_id"], self.child_id)
        self.assertEqual(receipt["actor"], "listener-owner")
        self.assertNotIn("summary", receipt)
        self.assertNotIn("audio", receipt)
        self.assertEqual(self.client.get(f"/api/records/{self.child_id}").status_code, 404)
        receipts = self.client.get("/api/forgetting-receipts", params={"akousma_id": self.child_id}).json()
        self.assertEqual(receipts["total"], 1)
        self.assertEqual(receipts["receipts"][0]["receipt_id"], receipt["receipt_id"])
        lint = self.client.get("/api/wiki/lint").json()
        # the child's outgoing edges left with it; nothing dangles
        self.assertEqual(lint["store"]["dangling_relations"], [])
        self.assertEqual(lint["store"]["dangling_parents"], [])
        self.assertEqual(self.client.get("/api/health").json()["total"], 1)
        self.assertEqual(self.client.get("/api/health").json()["forgetting_receipt_count"], 1)

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
        self.assertEqual(self.client.get("/api/diary/not-a-date").status_code, 400)

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
            "source_path": "/private/example/harbor.wav",
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
        self.assertNotIn("/private/example/", serialized)
        self.assertNotIn("do-not-export", serialized)
        manifest = _json.loads((pack_root / "manifest.json").read_text())
        wiki_entry = next(item for item in manifest["files"] if item["kind"] == "wiki")
        wiki_page = (pack_root / wiki_entry["path"]).read_text()
        self.assertNotIn("private field note", wiki_page)
        packs = self.client.get("/api/exports").json()["packs"]
        self.assertEqual(packs[0]["included"], 1)
        self.assertEqual(self.client.post("/api/export", json={"name": "empty"}).status_code, 400)

    def test_exported_audio_uses_a_pack_relative_uri(self):
        record = self._manual_with_audio(summary="packable rain")
        record_id = record["akousma_id"]
        self.client.post(f"/api/records/{record_id}/consent", json={"consent_status": "owned"})
        result = self.client.post(
            "/api/export",
            json={"name": "audio pack", "akousma_ids": [record_id]},
        ).json()
        pack_root = Path(result["path"])
        manifest = json.loads((pack_root / "manifest.json").read_text())
        audio_entry = next(item for item in manifest["files"] if item["kind"] == "audio")
        shipped = json.loads((pack_root / "records" / "records.jsonl").read_text())
        self.assertEqual(shipped["audio"]["uri"], f"pack://{audio_entry['path']}")

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

        # Non-network URL schemes are rejected before urllib can open them.
        self.client.put("/api/settings", json={"oida_url": "file:///etc/passwd"})
        with patch("urllib.request.urlopen") as urlopen:
            response = self.client.post(f"/api/records/{record['akousma_id']}/listen-again", json={})
        self.assertEqual(response.status_code, 422)
        urlopen.assert_not_called()

    def test_listen_again_creates_an_additive_revision(self):
        record = self._manual_with_audio()
        gateway = {
            "contract": "oida/gateway/v0.5",
            "perception_path": "oida_owned",
            "listening_event": {
                "id": "evt_fresh",
                "aggregate": {"title": "Fresh rain", "short_summary": "Rain and a distant bus.", "detailed_summary": "A new pass."},
                "routes": [{"route_id": "field-listener"}],
                "listening_provenance": {
                    "listening_sources": [{"id": "source-audio", "kind": "audio"}],
                    "cuts": [],
                    "corpus_lineage": [],
                },
                "listening_passes": [{"id": "pass-fresh", "listener_id": "oida-local-listener"}],
                "route_decisions": [{
                    "id": "decision-fresh-input",
                    "gate": "input",
                    "outcome": "proceed",
                    "subject": "retained audio reference",
                    "reason": "The explicit re-listening input was available.",
                    "decided_at": "2026-07-27T12:00:00Z",
                    "authority": {
                        "mode": "observe_only",
                        "actor": "oida-gateway",
                        "requires_confirmation": False,
                        "reversible": True,
                    },
                }],
                "listening_context": {
                    "honest_absences": [{
                        "kind": "not_retained",
                        "subject": "raw audio",
                        "attributed_to": "oída retention boundary",
                        "count": 1,
                    }],
                },
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
        from akousmata_app import AKOUSMATA_CONTRACT
        self.assertEqual(body["listening"]["contract"], AKOUSMATA_CONTRACT)
        self.assertEqual(body["listening"]["payload"]["source_contract"], "oida/gateway/v0.5")
        self.assertEqual(body["listening"]["payload"]["event_id"], "evt_fresh")
        self.assertEqual(body["listening"]["payload"]["claims"]["heard"][0]["statement"], "Rain is audible.")
        self.assertNotEqual(body["record"]["akousma_id"], record["akousma_id"])
        self.assertEqual(body["revision_of"], record["akousma_id"])
        self.assertEqual(
            body["record"]["auditum"]["revision"]["revises_akousma_id"],
            record["akousma_id"],
        )
        self.assertEqual(body["record"]["auditum"]["disagreements"], [])
        self.assertEqual(body["record"]["auditum"]["honest_absences"][0]["kind"], "not_retained")
        self.assertEqual(body["record"]["auditum"]["contract"], "earworm/auditum/v2")
        self.assertEqual(body["record"]["auditum"]["route_decisions"][0]["decision_id"], "decision-fresh-input")
        self.assertTrue(body["record"]["auditum"]["listenings"][0]["listening_pass_ref"])
        self.assertTrue(body["record"]["auditum"]["listenings"][0]["listening_provenance_ref"])
        original = self.client.get(f"/api/records/{record['akousma_id']}").json()["record"]
        self.assertNotIn("akousmata.listen_again", original["listening"])

    def test_listen_again_does_not_turn_a_refusal_into_a_hearing(self):
        record = self._manual_with_audio()
        gateway = {
            "contract": "oida/gateway/v0.5",
            "status": "complete",
            "outcome": "refused",
            "listening_event": None,
            "route_outcome": {
                "contract": "oida/route-outcome/v0.1",
                "subject": "file listening input",
                "route_decision": {"outcome": "refuse"},
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
            response = self.client.post(f"/api/records/{record['akousma_id']}/listen-again", json={})
        self.assertEqual(response.status_code, 423, response.text)
        detail = response.json()["detail"]
        self.assertIn("no listening revision", detail["message"])
        self.assertEqual(detail["route_outcome"]["contract"], "oida/route-outcome/v0.1")
        stored = self.client.get("/api/records").json()["records"]
        self.assertFalse(any(item.get("revision_of") == record["akousma_id"] for item in stored))

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
