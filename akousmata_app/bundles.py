"""Private restoration preserves history; public projections require current grants."""

from __future__ import annotations
import hashlib
import json
from pathlib import Path
import secrets
import zipfile

from akousma import validation_errors
from akousma.bundles import bundle_manifest_errors
from akousmata_app.exports import exportable, build_pack, claim_clock
from akousmata_app.paths import store_root

MAX_BYTES = 32 * 1024 * 1024


def encoded(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def export_bundle(store, ids, *, disclosure="private"):
    if (
        not isinstance(ids, list)
        or not 1 <= len(ids) <= 128
        or len(set(ids)) != len(ids)
    ):
        raise ValueError("Select 1–128 distinct record IDs")
    if disclosure not in {"private", "public-projection"}:
        raise ValueError("Choose private or public-projection")
    originals = {}
    for rid in ids:
        record = store.get(rid)
        if record is None or store.forgotten(rid) or (disclosure == "public-projection" and not exportable(record)[0]):
            raise ValueError("Selected record is missing, forgotten or not exportable")
        originals[rid] = record
    if disclosure == "public-projection":
        pack = build_pack(
            store,
            name="Listening memory projections",
            akousma_ids=ids,
            audience="public",
            include_audio=False,
            include_wiki=False,
        )
        records = [
            json.loads(line)
            for line in (Path(pack["path"]) / "records/records.jsonl")
            .read_text()
            .splitlines()
        ]
        if len(records) != len(ids):
            raise ValueError(
                "Each public record requires a current selected-field grant"
            )
    else:
        # Private record copies preserve historical claims and consent metadata.
        # They copy no audio assets and confer no public distribution grant.
        records = list(originals.values())
    entries, payloads = [], {}
    for i, record in enumerate(records):
        rid = record["akousma_id"]
        data = encoded(record)
        if len(data) > 2 * 1024 * 1024:
            raise ValueError("Record exceeds 2 MiB")
        path = f"records/{i:04d}.json"
        payloads[path] = data
        source = originals[rid]
        entries.append(
            dict(
                id=rid,
                path=path,
                sha256=digest(data),
                source_sha256=digest(encoded(source)),
                schema_version=source["schema_version"],
                kind="canonical-record"
                if disclosure == "private"
                else "metadata-projection",
                evidence_class="generated"
                if source.get("provenance", {}).get("source_type") == "generated"
                else "unknown",
                covenants=[source.get("auditum", {}).get("covenant", {})]
                if disclosure == "private"
                else [],
                transforms=[]
                if disclosure == "private"
                else ["akousmata/public-record/v1"],
                recipient_requirements=[
                    "earworm/akousma/v" + source["schema_version"].rsplit(".", 1)[0]
                ]
                if disclosure == "private"
                else ["akousmata/public-record/v1"],
            )
        )
    manifest = dict(
        contract="earworm/listening-memories/v1",
        bundle_id="bundle:" + secrets.token_hex(16),
        created_at=claim_clock(),
        producer="akousmata",
        disclosure=disclosure,
        entries=entries,
        human_rendering="unknown",
    )
    errors = bundle_manifest_errors(manifest)
    if errors:
        raise ValueError("; ".join(errors))
    if sum(map(len, payloads.values())) > MAX_BYTES:
        raise ValueError("Bundle exceeds 32 MiB")
    # Recheck current consent and content after projection, before publication.
    for rid, old in originals.items():
        if store.get(rid) != old or store.forgotten(rid):
            raise ValueError("Export source changed")
        if disclosure == "public-projection":
            from akousmata_app.publication import public_record
            if public_record(store, rid) != next(r for r in records if r["akousma_id"] == rid):
                raise ValueError("Public grant changed during export")
    root = store_root() / "exports"
    root.mkdir(parents=True, exist_ok=True)
    path = root / ("bundle-" + secrets.token_hex(12) + ".zip")
    with zipfile.ZipFile(path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", encoded(manifest))
        for name, data in payloads.items():
            archive.writestr(name, data)
    return dict(manifest=manifest, archive=str(path), sha256=digest(path.read_bytes()))


def _inspect_bundle(data):
    import io

    if not isinstance(data, bytes) or len(data) > MAX_BYTES:
        raise ValueError("Bundle exceeds 32 MiB")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if (
            len(entries) > 129
            or len({e.filename for e in entries}) != len(entries)
            or sum(e.file_size for e in entries) > MAX_BYTES
        ):
            raise ValueError("Duplicate or oversized archive")
        manifest = json.loads(archive.read("manifest.json"))
        errors = bundle_manifest_errors(manifest)
        if errors:
            raise ValueError("; ".join(errors))
        if {e.filename for e in entries} != {
            "manifest.json",
            *(e["path"] for e in manifest["entries"]),
        }:
            raise ValueError("Archive membership differs from manifest")
        payloads = {}
        for entry in manifest["entries"]:
            payload = archive.read(entry["path"])
            if digest(payload) != entry["sha256"]:
                raise ValueError("Bundle payload hash mismatch")
            payloads[entry["path"]] = payload
    return manifest, payloads



def inspect_bundle(data):
    try:
        return _inspect_bundle(data)
    except (zipfile.BadZipFile, KeyError, UnicodeError, RecursionError, RuntimeError) as exc:
        raise ValueError("Malformed or unsupported bundle archive") from exc


def import_bundle(store, data, *, supported_contracts):
    if (
        not isinstance(supported_contracts, list)
        or not 1 <= len(supported_contracts) <= 32
        or any(
            not isinstance(v, str) or not 1 <= len(v) <= 256
            for v in supported_contracts
        )
    ):
        raise ValueError("Declare 1–32 supported contracts")
    manifest, payloads = inspect_bundle(data)
    if manifest["contract"] not in supported_contracts:
        raise ValueError("Bundle contract was not negotiated")
    if (
        manifest["disclosure"] != "private"
        or manifest["contract"] != "earworm/listening-memories/v1"
    ):
        raise ValueError(
            "Projections and agent audio cannot be imported as canonical records"
        )
    adapter = {}
    prepared = []
    for entry in manifest["entries"]:
        if entry["kind"] != "canonical-record" or not set(
            entry["recipient_requirements"]
        ) <= set(supported_contracts):
            raise ValueError("Recipient does not support this canonical record")
        record = json.loads(payloads[entry["path"]])
        errors = validation_errors(record)
        if (
            errors
            or record.get("akousma_id") != entry["id"]
            or record.get("schema_version") != entry["schema_version"]
            or entry["source_sha256"] != entry["sha256"]
        ):
            raise ValueError("Invalid canonical identity, version or source hash")
        if record.get("schema_version") == "1.8.0":
            # Canonical bundles do not carry spectral objects or host validators.
            # Validate admission before any writes; never downgrade evidence.
            from akousma.spectral import admit_record
            admit_record(record, supported_versions=["1.8.0"])
        # Private restoration is not disclosure admission. Keep the source's
        # historical consent and receiving claims without inventing rights.
        # The receiver's current forgetting ledger remains authoritative.
        if store.forgotten(entry["id"]):
            raise ValueError("Current forgetting ledger refuses import")
        old = store.get(entry["id"])
        if old is not None and old != record:
            raise ValueError("Canonical identity/hash conflict")
        if record.get("record_kind") == "transformation_graph":
            import os
            from akousma.masa_runtime import masa_validator, lineage_directions
            from akousma.transformation_graph import transformation_graph_errors

            if not adapter:
                adapter = dict(
                    validate_masa=masa_validator(
                        os.environ.get("AKOUSMATA_MASA_VALIDATOR_MODULE", "")
                    ),
                    lineage_directions=lineage_directions(
                        os.environ.get("AKOUSMATA_MASA_CORE_MODULE", "")
                    ),
                )
            errors = transformation_graph_errors(
                record["extensions"]["earworm_transformation_graph"], **adapter
            )
            if errors:
                raise ValueError("; ".join(errors))
        prepared.append(record)
    scope = {r["akousma_id"]: r for r in prepared}
    refs = set()
    for record in prepared:
        refs.update(record.get("lineage", {}).get("parent_akousma_ids", []))
        refs.update(
            r["target_akousma_id"]
            for r in record.get("lineage", {}).get("relations", [])
            if r.get("target_akousma_id")
        )
        refs.update(
            record.get("extensions", {})
            .get("earworm_generation_decision", {})
            .get("input_refs", [])
        )
    if len(refs) > 2048:
        raise ValueError("Bundle reference scope exceeds 2048 records")
    for ref in refs - scope.keys():
        found = store.get(ref)
        if found is not None:
            scope[ref] = found
    from akousma.record_evolution import next_record_reference_errors

    for record in prepared:
        if record["schema_version"] == "1.7.0":
            errors = next_record_reference_errors(record, list(scope.values()))
            if errors:
                raise ValueError("; ".join(errors))
    pending, ordered = list(prepared), []
    while pending:
        ids = {r["akousma_id"] for r in pending}
        ready = [
            r
            for r in pending
            if r.get("auditum", {}).get("revision", {}).get("revises_akousma_id")
            not in ids
        ]
        if not ready:
            raise ValueError("Cyclic bundle revision dependencies")
        ordered.extend(ready)
        pending = [r for r in pending if r not in ready]
    prepared = ordered
    results = []
    # Existing store rechecks its current forgetting ledger on every put. No
    # database replacement or imported grant can override that authority.
    for record in prepared:
        old = store.get(record["akousma_id"])
        if store.forgotten(record["akousma_id"]):
            raise ValueError("Record was forgotten during import")
        if old is None:
            options = dict(adapter)
            if record["schema_version"] == "1.8.0":
                options["supported_versions"] = ["1.8.0"]
            store.put(record, **options)
        elif old != record:
            raise ValueError("Identity changed during import")
        results.append(
            dict(
                record_ref=record["akousma_id"],
                outcome="reused" if old is not None else "retained",
                audio="original locator retained; availability must be resolved separately",
            )
        )
    receipt = dict(
        contract="akousmata/bundle-import/v1",
        bundle_id=manifest["bundle_id"],
        bundle_sha256=digest(data),
        created_at=claim_clock(),
        records=results,
        grants_imported=False,
        admission="private-restoration",
        publication="requires-current-local-grant-and-consent",
    )
    root = Path(store.root) / "bundle-receipts"
    root.mkdir(parents=True, exist_ok=True)
    path = root / (digest(data) + ".json")
    path.write_bytes(encoded(receipt))
    return receipt
