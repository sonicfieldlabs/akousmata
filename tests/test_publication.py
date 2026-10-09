"""Projection boundaries over real temporary stores and the FastAPI routers."""
import json
import os
import tempfile
import unittest
import zipfile
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import akousma
from fastapi import FastAPI
from fastapi.testclient import TestClient
from akousmata_app import exports, publication, records
from akousmata_app.server import app, public_router


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"AKOUSMATA_PATH": self.tmp.name, "AKOUSMATA_WATCHER": "0"})
        self.env.start()
        self.store = akousma.AkousmataStore(self.tmp.name)
        self.client = TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000))
        self.first = self.add("First public summary", "2026-07-01T12:00:00Z")
        self.second = self.add("Second public summary", "2026-07-02T12:00:00Z")
        self.private = self.add("PRIVATE_SUMMARY", "2026-07-03T12:00:00Z")

    def tearDown(self):
        self.client.close()
        self.store.close()
        self.env.stop()
        self.tmp.cleanup()

    def add(self, summary, created):
        record = akousma.new_akousma(audio={"asset_id": "PRIVATE_ASSET", "uri": "file:///private/not-shared.wav", "sample_rate": 16000},
            originating_app="fixture", summary=summary, tags=["approved-tag"],
            listening={"agent.fixture": {"payload": {"secret_named_innocently": "PRIVATE_REPORT"}}},
            extensions={"future.payload": {"private_data": "PRIVATE_EXTENSION"},
                        "akousmata.app": {"publication": {"state": "granted", "fields": ["summary"]}}})
        record["created_at"] = created
        record["provenance"].update(consent_status="owned", rights_note="PRIVATE_RIGHTS")
        record["annotations"] = {"notes": "PRIVATE_ANNOTATION"}
        record["unknown_top"] = "PRIVATE_TOP"
        self.store.put(record)
        return record

    def allow(self, record, fields=None):
        return publication.grant(self.store, record["akousma_id"], fields or ["summary", "tags"])

    def test_consent_and_imported_extensions_do_not_grant_publication(self):
        self.assertEqual(publication.public_counts(self.store)["total"], 0)
        self.assertEqual(publication.public_page(self.store)["records"], [])
        self.assertIsNone(publication.public_record(self.store, self.first["akousma_id"]))
        self.assertEqual(publication.grant_status(self.store, self.first["akousma_id"])["state"], "unpublished")

    def test_allowlist_and_source_immutability(self):
        source = deepcopy(self.first)
        self.allow(self.first, ["summary", "tags", "provenance", "audio_metadata", "listener_types"])
        result = publication.public_record(self.store, self.first["akousma_id"])
        self.assertEqual(result["projection_contract"], exports.PROJECTION_CONTRACT)
        self.assertNotIn("schema_version", result)
        self.assertNotIn("PRIVATE_", json.dumps(result))
        self.assertNotIn("listening", result)
        self.assertNotIn("lineage", result)
        self.assertNotIn("uri", result["audio"])
        self.assertNotIn("asset_id", result["audio"])
        result["summary"] = "changed copy"
        self.assertEqual(self.store.get(self.first["akousma_id"]), source)

    def test_invalid_fields_and_unknown_consent_fail_closed(self):
        for fields in [["extensions"], ["summary", "summary"], ["location"], [False], "summary"]:
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                publication.grant(self.store, self.first["akousma_id"], fields)
        changed = deepcopy(self.first); changed["provenance"]["consent_status"] = "unknown"
        self.store.put(changed)
        with self.assertRaises(ValueError): self.allow(changed)
        with self.assertRaises(KeyError): publication.grant(self.store, "missing", [])

    def test_counts_match_visible_records_and_projected_filters(self):
        self.allow(self.first)
        self.allow(self.second, ["summary", "provenance"])
        page = publication.public_page(self.store)
        count = publication.public_counts(self.store)
        self.assertEqual(count["total"], len(page["records"]))
        self.assertEqual(count["by_app"], {"fixture": 1})
        self.assertNotIn("private", json.dumps(count).lower())
        self.assertEqual(publication.public_counts(self.store, tag="approved-tag")["total"], 1)
        self.assertEqual(publication.public_counts(self.store, text="PRIVATE_REPORT")["total"], 0)
        self.assertEqual(publication.public_page(self.store, text="PRIVATE_REPORT")["records"], [])

    def test_pagination_has_no_private_gaps_or_raw_counts(self):
        self.allow(self.first); self.allow(self.second)
        first = publication.public_page(self.store, limit=1)
        self.assertNotIn("total", first)
        self.assertEqual(first["records"][0]["akousma_id"], self.second["akousma_id"])
        second = publication.public_page(self.store, limit=1, cursor=first["next_cursor"])
        self.assertEqual(second["records"][0]["akousma_id"], self.first["akousma_id"])
        self.assertIsNone(second["next_cursor"])
        self.add("another PRIVATE_RECORD", "2026-09-01T00:00:00Z")
        self.assertEqual(publication.public_page(self.store, limit=1), first)
        self.assertEqual(publication.public_page(self.store, limit=1, cursor=first["next_cursor"]), second)

    def test_revocation_invalidates_cursor_and_does_not_expose_missing_identity(self):
        self.allow(self.first); self.allow(self.second)
        first = publication.public_page(self.store, limit=1)
        publication.revoke(self.store, self.first["akousma_id"])
        with self.assertRaises(publication.ViewChanged):
            publication.public_page(self.store, limit=1, cursor=first["next_cursor"])
        for record_id in (self.first["akousma_id"], self.private["akousma_id"], "missing"):
            result = self.client.get(f"/api/public/records/{record_id}")
            self.assertEqual(result.status_code, 404)
            self.assertEqual(result.json(), {"detail": "record not available"})
            self.assertEqual(result.headers["cache-control"], "no-store")

    def test_source_change_stales_grant_and_requires_explicit_refresh(self):
        self.allow(self.first)
        source = deepcopy(self.first); source["annotations"]["new"] = "private curation"
        self.store.put(source)
        self.assertEqual(publication.public_counts(self.store)["total"], 0)
        self.assertEqual(publication.grant_status(self.store, source["akousma_id"])["state"], "stale")
        self.allow(source)
        self.assertEqual(publication.public_counts(self.store)["total"], 1)
        self.assertNotIn("private curation", json.dumps(publication.public_page(self.store)))

    def test_consent_withdrawal_and_restoration_do_not_revive_grant(self):
        self.allow(self.first)
        records.set_consent(self.store, self.first["akousma_id"], "unknown")
        records.set_consent(self.store, self.first["akousma_id"], "owned")
        self.assertEqual(publication.public_counts(self.store)["total"], 0)
        self.assertEqual(publication.grant_status(self.store, self.first["akousma_id"])["state"], "revoked")

    def test_forgetting_reindex_and_reopen_preserve_boundary(self):
        self.allow(self.first); self.allow(self.second)
        self.store.forget_with_receipt(self.first["akousma_id"], actor="fixture", reason="test revocation")
        self.store.reindex(); self.store.close()
        self.store = akousma.AkousmataStore(self.tmp.name)
        self.assertEqual(publication.public_counts(self.store)["total"], 1)
        self.assertEqual(publication.public_page(self.store)["records"][0]["akousma_id"], self.second["akousma_id"])
        self.assertEqual(self.store.get(self.second["akousma_id"]), self.second)
        self.assertNotIn("forgetting", json.dumps(publication.public_counts(self.store)))

    def test_owner_grant_api_and_public_router_are_separate(self):
        rid = self.first["akousma_id"]
        self.assertEqual(self.client.post(f"/api/records/{rid}/publication", json={"fields": ["summary"]}).status_code, 200)
        self.assertEqual(self.client.get("/api/public/status").json()["total"], 1)
        self.assertEqual(self.client.get("/api/public/status").headers["cache-control"], "no-store")
        public_app = FastAPI(); public_app.include_router(public_router)
        with TestClient(public_app) as client:
            self.assertEqual(client.get("/api/public/status").json()["total"], 1)
            for path in ("/api/health", "/api/records", "/api/settings", "/api/exports"):
                self.assertEqual(client.get(path).status_code, 404)
            self.assertEqual(client.post(f"/api/records/{rid}/publication", json={"fields": []}).status_code, 404)
        self.assertEqual(self.client.delete(f"/api/records/{rid}/publication").json(), {"state": "revoked"})
        self.assertEqual(self.client.get("/api/public/status").json()["total"], 0)

    def test_bad_cursor_and_public_view_change_statuses(self):
        self.allow(self.first); self.allow(self.second)
        for cursor in ["!invalid", "e30=", "x" * 513]:
            self.assertEqual(self.client.get("/api/public/records", params={"cursor": cursor}).status_code, 400)
        self.assertEqual(self.client.get("/api/public/records", params={"limit": 201}).status_code, 422)
        first = self.client.get("/api/public/records", params={"limit": 1}).json()
        publication.revoke(self.store, self.first["akousma_id"])
        result = self.client.get("/api/public/records", params={"cursor": first["next_cursor"]})
        self.assertEqual(result.status_code, 409)

    def test_pack_wiki_manifest_and_preview_cannot_rehydrate_private_fields_or_edges(self):
        child = deepcopy(self.private)
        child["akousma_id"] = "ak_private_child_fixture"
        child["lineage"]["parent_akousma_ids"] = [self.first["akousma_id"]]
        child["provenance"]["consent_status"] = "unknown"
        self.store.put(child)
        before = self.store.get(self.first["akousma_id"])
        result = exports.build_pack(self.store, name="fixture", akousma_ids=[child["akousma_id"], self.first["akousma_id"]])
        self.assertEqual(len(result["excluded"]), 1)  # Local diagnostics only.
        self.assertEqual(exports.list_packs()[0]["excluded"], 1)
        with zipfile.ZipFile(result["archive"]) as archive:
            self.assertIn("wiki/record-0001.md", archive.namelist())
            self.assertFalse(any("owner.json" in name or "0002" in name for name in archive.namelist()))
            for name in archive.namelist():
                if not name.endswith('/'):
                    content = archive.read(name).decode()
                    self.assertNotIn("PRIVATE_", content, name)
                    self.assertNotIn(child["akousma_id"], content, name)
        self.assertNotIn("PRIVATE_", json.dumps(result["preview"]))
        self.assertEqual(self.store.get(self.first["akousma_id"]), before)

    def test_public_pack_matches_projection_and_ignores_audio_and_field_widening(self):
        self.allow(self.first, ["summary"])
        result = exports.build_pack(self.store, name="public", akousma_ids=[self.first["akousma_id"], self.private["akousma_id"]],
            audience="public", fields=["summary", "provenance", "audio_metadata"], include_audio=True)
        manifest = json.loads((Path(result["path"])/'manifest.json').read_text())
        projected = json.loads((Path(result["path"])/'records/records.jsonl').read_text())
        self.assertEqual(projected, publication.public_record(self.store, self.first["akousma_id"]))
        self.assertFalse(manifest["include_audio"])
        self.assertFalse(any(item['kind']=='audio' for item in manifest['files']))
        self.assertEqual(manifest['excluded'], [])

    def test_audio_uri_and_unapproved_metadata_are_not_publicly_searchable(self):
        self.allow(self.first, ["summary"])
        self.assertEqual(publication.public_counts(self.store, text="not-shared")["total"], 0)
        self.assertEqual(publication.public_counts(self.store, tag="approved-tag")["total"], 0)
        self.assertEqual(publication.public_counts(self.store)["by_app"], {})
