"""Read-only owner projection of attributable passes and retained connections."""

from __future__ import annotations
import base64
import hashlib
import json
from typing import Any

CONTRACT = "akousmata/listening-relations/v1"


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _payload(record, namespace):
    entry = record.get("listening", {}).get(namespace, {})
    value = entry.get("payload", {}) if isinstance(entry, dict) else {}
    return value if isinstance(value, dict) else {}


def _pass_id(item):
    return item.get("listening_pass_ref") or item.get("listening_id")


def _report(record, listening):
    payload = _payload(record, listening.get("report_namespace"))
    retained = payload.get("record")
    if isinstance(retained, dict):
        original = next(
            (
                p
                for p in retained.get("auditum", {}).get("listenings", [])
                if _pass_id(p) == _pass_id(listening)
            ),
            None,
        )
        if original:
            payload = _payload(retained, original.get("report_namespace"))
    report = payload.get("report", payload)
    if (
        not isinstance(report, dict)
        or report.get("contract") != "akouo/agent-report/v0.1"
    ):
        return {}
    if report.get("listening_pass_id") != _pass_id(listening) or report.get(
        "listener_id"
    ) != listening.get("listener_id"):
        return {}
    return report


def project(record: dict[str, Any], resolve=None):
    """Display declarations and evidence availability, never infer a missing edge."""
    block = record.get("auditum") if isinstance(record.get("auditum"), dict) else {}
    nodes = []
    edges = []
    issues = []
    local = {}
    snapshots = {}
    for namespace in ("akouo.retained-ensemble", "akouo.second-report"):
        found = _payload(record, namespace).get("source_snapshots", {})
        if isinstance(found, dict):
            snapshots.update({k: v for k, v in found.items() if isinstance(v, dict)})
    for listening in block.get("listenings", []):
        lid = listening.get("listening_id")
        if not lid or lid in local:
            issues.append("Missing or duplicate listening identity")
            continue
        report = _report(record, listening)
        node = dict(
            id="listening:" + lid,
            listening_id=lid,
            pass_id=_pass_id(listening),
            participant_id=listening.get("listener_id"),
            participant_type=listening.get("listener_type"),
            report_ref=report.get("report_id"),
            report_namespace=listening.get("report_namespace"),
            categories=sorted(
                {
                    f["category"]
                    for f in report.get("features", [])
                    if isinstance(f, dict) and isinstance(f.get("category"), str)
                }
            ),
            kind="listening",
            status="retained",
        )
        local[lid] = node
        nodes.append(node)

    def record_node(identifier):
        key = "record:" + identifier
        existing = next((n for n in nodes if n["id"] == key), None)
        if existing:
            return key
        current = (
            record
            if identifier == record["akousma_id"]
            else resolve(identifier)
            if resolve
            else None
        )
        snapshot = snapshots.get(identifier)
        status = "canonical" if current else "snapshot_only" if snapshot else "missing"
        if current and snapshot and digest(current) != digest(snapshot):
            status = "canonical_changed"
        source = snapshot or current
        nodes.append(
            dict(
                id=key,
                kind="record",
                record_id=identifier,
                status=status,
                source_sha256=digest(source) if source else None,
                canonical_sha256=digest(current) if current else None,
                participant_ids=sorted(
                    {
                        p["listener_id"]
                        for p in (source or {}).get("auditum", {}).get("listenings", [])
                        if p.get("listener_id")
                    }
                ),
            )
        )
        return key

    for listening in block.get("listenings", []):
        receiver = local.get(listening.get("listening_id"))
        if receiver is None:
            continue
        report = _report(record, listening)
        origin = _payload(record, listening.get("report_namespace")).get(
            "record", record
        )
        plan = (
            _payload(origin, "akouo.second-report").get("route", {}).get("request", {})
        )
        second = (
            plan.get("profile") == "second_report"
            and plan.get("listening_pass_id") == receiver["pass_id"]
            and plan.get("report_id") == report.get("report_id")
        )
        refs = report.get("report_of_refs", [])
        refs = [r for r in refs if isinstance(r, str)] if isinstance(refs, list) else []
        for ref in dict.fromkeys(refs):
            if not isinstance(ref, str):
                continue
            identifier = ref.split("#", 1)[0]
            if identifier not in report.get("input_refs", []):
                issues.append("Second-report reference is not a declared input")
                continue
            edges.append(
                dict(
                    kind="second_report" if second else "retained_input",
                    source=record_node(identifier),
                    target=receiver["id"],
                    report_ref=report.get("report_id"),
                    input_ref=ref,
                    basis="Retained report input; no direct audio access or redirection implied",
                )
            )

    # A review is a record-level kinship declaration, not another model pass.
    for relation in record.get("lineage", {}).get("relations", []):
        if relation.get("type") == "response_to" and isinstance(
            relation.get("target_akousma_id"), str
        ):
            edges.append(
                dict(
                    kind="record_response",
                    source=record_node(relation["target_akousma_id"]),
                    target=record_node(record["akousma_id"]),
                    basis="Additive record response; no causal influence or same-source claim implied",
                )
            )

    evidence = _payload(record, "oida.influence-evidence").get("traces", [])
    ensemble = block.get("ensemble") if isinstance(block.get("ensemble"), dict) else {}
    seen = set()
    for edge in ensemble.get("influence_edges", []):
        source = local.get(edge.get("from_listening_id"))
        target = local.get(edge.get("to_listening_id"))
        identity = (
            edge.get("from_listening_id"),
            edge.get("to_listening_id"),
            edge.get("effect"),
        )
        if identity in seen:
            issues.append("Duplicate influence edge")
            continue
        seen.add(identity)
        receiver = next(
            (
                p
                for p in block.get("listenings", [])
                if p.get("listening_id") == edge.get("to_listening_id")
            ),
            {},
        )
        matched = any(
            i.get("listening_id") == edge.get("from_listening_id")
            and i.get("effect") == edge.get("effect")
            for i in receiver.get("influenced_by", [])
            if isinstance(i, dict)
        )
        members = ensemble.get("listening_ids", [])
        valid = bool(
            source
            and target
            and source != target
            and matched
            and edge.get("effect")
            and edge.get("from_listening_id") in members
            and edge.get("to_listening_id") in members
            and ensemble.get("permissions_preserved") is True
            and ensemble.get("disagreements_preserved") is True
            and ensemble.get("dissolution_rule")
        )
        linked = []
        if valid:
            for item in evidence if isinstance(evidence, list) else []:
                if not isinstance(item, dict):
                    continue
                trace = item.get("trace", {})
                if not isinstance(trace, dict):
                    continue
                target_record = snapshots.get(item.get("target_record_ref"), {})
                original = _payload(target_record, item.get("trace_namespace"))
                decisions = target_record.get("auditum", {}).get("route_decisions", [])
                if (
                    trace
                    and original == trace
                    and trace.get("from_pass_ref") == source["pass_id"]
                    and trace.get("to_pass_ref") == target["pass_id"]
                    and item.get("effect") == edge["effect"]
                    and item.get("before") in decisions
                    and item.get("after") in decisions
                ):
                    linked.append(
                        dict(
                            trace_id=trace.get("trace_id"),
                            source_record_ref=item.get("source_record_ref"),
                            target_record_ref=item.get("target_record_ref"),
                            trace_namespace=item.get("trace_namespace"),
                            before_decision_ref=trace.get("before_decision_ref"),
                            after_decision_ref=trace.get("after_decision_ref"),
                            basis=item.get("basis"),
                        )
                    )
        if not valid:
            issues.append(
                "Influence reference or preservation declaration is incomplete"
            )
        edges.append(
            dict(
                kind="recorded_redirection"
                if valid and linked
                else "declared_influence"
                if valid
                else "unresolved_influence",
                source=source["id"]
                if source
                else "missing:" + str(edge.get("from_listening_id")),
                target=target["id"]
                if target
                else "missing:" + str(edge.get("to_listening_id")),
                effect=edge.get("effect"),
                evidence=linked,
                basis="Retained attribution; trace availability is not independent causal verification",
            )
        )
    counts = {
        kind: sum(e["kind"] == kind for e in edges)
        for kind in (
            "record_response",
            "retained_input",
            "second_report",
            "recorded_redirection",
            "declared_influence",
            "unresolved_influence",
        )
    }
    return dict(
        contract=CONTRACT,
        audience="owner",
        record_id=record["akousma_id"],
        source_sha256=digest(record),
        nodes=nodes,
        edges=edges,
        counts=counts,
        issues=issues,
        independent=bool(local) and all(e["kind"] == "retained_input" for e in edges),
        note="No connection inferred from co-presence, scheduling or a shared participant",
    )


def page(store, identifier, *, limit=50, cursor=None):
    if type(limit) is not int or not 1 <= limit <= 200:
        raise ValueError("limit must be between 1 and 200")
    record = store.get(identifier)
    if record is None:
        raise KeyError(identifier)
    result = project(record, store.get)
    view = digest(result)
    offset = 0
    if cursor:
        try:
            if len(cursor) > 512:
                raise ValueError()
            token = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
            if (
                set(token) != {"view", "offset"}
                or type(token["offset"]) is not int
                or token["offset"] < 0
            ):
                raise ValueError()
            if token["view"] != view:
                raise ViewChanged(
                    "Listening references changed; restart from the first page"
                )
            offset = token["offset"]
        except (TypeError, KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Invalid listening cursor") from exc
    edges = result["edges"]
    if offset > len(edges):
        raise ValueError("Invalid listening cursor")
    result["edges"] = edges[offset : offset + limit]
    after = offset + len(result["edges"])
    result["next_cursor"] = (
        base64.urlsafe_b64encode(
            json.dumps(dict(view=view, offset=after)).encode()
        ).decode()
        if after < len(edges)
        else None
    )
    result["view_sha256"] = view
    return result


class ViewChanged(ValueError):
    pass
