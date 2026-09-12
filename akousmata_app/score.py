"""Bounded score data from K10 membership and current canonical records."""

from datetime import datetime
from hashlib import sha256
import json
from akousmata_app.graph_history import replay


def project(store, *, event_id, scales, resolution_ms=1000):
    if (
        not isinstance(scales, list)
        or not scales
        or len(set(scales)) != len(scales)
        or not set(scales) <= {"records", "listenings", "observations"}
    ):
        raise ValueError("Choose records, listenings and/or observations")
    if type(resolution_ms) is not int or not 1 <= resolution_ms <= 86400000:
        raise ValueError("Resolution must be 1–86400000 ms")
    snapshot = replay(store, event_id)
    events, gaps = [], []
    for node in snapshot["nodes"]:
        if node.get("missing"):
            gaps.append({"record_ref": node["id"], "reason": "unavailable"})
            continue
        record = store.get(node["id"])
        if (
            record is None
            or record.get("provenance", {}).get("consent_status") == "restricted"
        ):
            gaps.append({"record_ref": node["id"], "reason": "unavailable"})
            continue
        record_hash = sha256(
            json.dumps(
                record, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
        ).hexdigest()
        rows = []
        if "records" in scales:
            rows.append(("records", record["akousma_id"], record["created_at"]))
        if "listenings" in scales:
            rows.extend(
                ("listenings", p["listening_id"], p.get("created_at"))
                for p in record.get("auditum", {}).get("listenings", [])
            )
        if "observations" in scales:
            binding = record.get("extensions", {}).get("earworm_observation", {})
            mapping = (
                record.get("listening", {})
                .get(binding.get("mapping_namespace"), {})
                .get("payload", {})
            )
            for observation in mapping.get("source_snapshot", {}).get(
                "observations", []
            ):
                if observation.get("id") == binding.get("observation_ref"):
                    clock = observation.get("observedAt", {})
                    rows.append(
                        (
                            "observations",
                            observation["id"],
                            clock
                            if isinstance(clock, str)
                            else clock.get("value")
                            if isinstance(clock, dict) and clock.get("state") == "known"
                            else None,
                        )
                    )
        for scale, ref, clock in rows:
            try:
                dt = datetime.fromisoformat(clock.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    raise ValueError()
                bucket = int(dt.timestamp() * 1000) // resolution_ms * resolution_ms
            except (ValueError, AttributeError, TypeError):
                bucket = None
            events.append(
                dict(
                    record_ref=record["akousma_id"],
                    source_ref=ref,
                    scale=scale,
                    source_clock=clock,
                    bucket_ms=bucket,
                    source_sha256=record_hash,
                )
            )
            if len(events) >= 2000:
                break
        if len(events) >= 2000:
            gaps.append({"reason": "2000-event limit reached"})
            break
    return dict(
        contract="akousmata/score-projection/v1",
        event_id=event_id,
        event_clock=snapshot["captured_at"],
        source_policy="Snapshot membership with current canonical record content and consent; not historical record replay",
        scales=scales,
        resolution_ms=resolution_ms,
        events=events,
        gaps=gaps,
        coverage={
            "snapshot_nodes": len(snapshot["nodes"]),
            "events": len(events),
            "gaps": len(gaps),
        },
        perceptual_access="not_established",
    )
