"""The akousmata as a graph: lineage (causal) + relations (kinship).

Two edge kinds, never conflated — parents mean "made from", relations mean
"belongs with". Both are walkable; the navigator draws them differently.
"""

from __future__ import annotations

import json
from typing import Any

from akousmata_app.records import summary_line


def _restricted(record):
    return record.get("provenance", {}).get("consent_status") == "restricted"


def _edges(store, record, cap):
    from akousmata_app.relation_index import page

    rid = record["akousma_id"]
    edges = []
    parents = store.conn.execute(
        "SELECT parent_id FROM lineage_edges WHERE child_id=? ORDER BY parent_id LIMIT ?",
        (rid, cap + 1),
    ).fetchall()
    children = store.conn.execute(
        "SELECT child_id FROM lineage_edges WHERE parent_id=? ORDER BY child_id LIMIT ?",
        (rid, cap + 1),
    ).fetchall()
    for row in parents:
        edges.append(dict(**{"from": row["parent_id"], "to": rid}, kind="lineage"))
    for row in children:
        edges.append(dict(**{"from": rid, "to": row["child_id"]}, kind="lineage"))
    relations = page(store, rid, limit=min(200, cap))
    for link in relations["edges"]:
        edges.append(
            dict(
                **{"from": link["source_ref"], "to": link["target_ref"]},
                kind="relation",
                type=link["relation"].get("type", "other"),
                relation=link["relation"],
                ordinal=link["ordinal"],
            )
        )
    return edges[:cap], len(edges) > cap or relations["next_cursor"] is not None


def _walk(store, seeds, depth, limit):
    if (
        type(limit) is not int
        or type(depth) is not int
        or not 1 <= limit <= 800
        or not 1 <= depth <= 4
    ):
        raise ValueError("Invalid graph bounds")
    nodes = {}
    edges = {}
    frontier = list(seeds)
    truncated = False
    edge_limit = min(1600, limit * 4)
    for _ in range(depth):
        next_frontier = []
        for rid in frontier:
            if rid in nodes:
                continue
            if len(nodes) >= limit:
                truncated = True
                break
            record = store.get(rid)
            if record is None or _restricted(record):
                nodes[rid] = dict(
                    id=rid,
                    label="(missing or restricted)",
                    app="unknown",
                    missing=True,
                    stage="unavailable",
                )
                continue
            nodes[rid] = _node(record)
            remaining = edge_limit - len(edges)
            if remaining <= 0:
                truncated = True
                continue
            found, cut = _edges(store, record, remaining)
            truncated |= cut
            for edge in found:
                key = json.dumps(
                    [
                        edge["from"],
                        edge["to"],
                        edge["kind"],
                        edge.get("type"),
                        edge.get("ordinal"),
                    ]
                )
                edges[key] = edge
                next_frontier.extend([edge["from"], edge["to"]])
        frontier = list(dict.fromkeys(r for r in next_frontier if r not in nodes))
    withheld = {
        ref
        for e in edges.values()
        for ref in (e["from"], e["to"])
        if (record := store.get(ref)) is not None and _restricted(record)
    }
    edges = {
        key: e
        for key, e in edges.items()
        if e["from"] not in withheld and e["to"] not in withheld
    }
    for edge in edges.values():
        edge["missing"] = (
            edge["from"] not in nodes
            or edge["to"] not in nodes
            or nodes.get(edge["from"], {}).get("missing", False)
            or nodes.get(edge["to"], {}).get("missing", False)
        )
        edge["role"] = "retained relation"
        if edge["kind"] == "lineage":
            edge["role"] = (
                "generated from"
                if nodes.get(edge["to"], {}).get("stage") == "generation"
                else (
                    "later listening lineage"
                    if nodes.get(edge["from"], {}).get("stage") == "generation"
                    and nodes.get(edge["to"], {}).get("stage") == "listening"
                    else "parent lineage"
                )
            )
        if edge["missing"]:
            edge["gap"] = "missing, restricted or outside this bounded view"
    return dict(
        nodes=list(nodes.values()),
        edges=list(edges.values()),
        truncated=truncated or bool(frontier),
        bounds=dict(nodes=limit, edges=edge_limit, depth=depth),
        aggregation="No hidden nodes merged; omitted neighborhoods are marked by truncation and gaps",
    )


def full_graph(store, *, limit=400):
    if type(limit) is not int or not 1 <= limit <= 800:
        raise ValueError("Invalid graph bounds")
    seeds = [
        r[0]
        for r in store.conn.execute(
            "SELECT akousma_id FROM akousmata ORDER BY created_at DESC,akousma_id LIMIT ?",
            (limit + 1,),
        )
    ]
    result = _walk(store, seeds[:limit], 1, limit)
    result["truncated"] |= len(seeds) > limit
    return result


def neighborhood(store, akousma_id, *, depth=2, limit=120):
    return dict(focus=akousma_id, **_walk(store, [akousma_id], depth, limit))


def _node(record: dict[str, Any]) -> dict[str, Any]:
    provenance = record.get("provenance") or {}
    auditum = record.get("auditum") if isinstance(record.get("auditum"), dict) else {}
    revision = (
        auditum.get("revision") if isinstance(auditum.get("revision"), dict) else {}
    )
    return {
        "id": record["akousma_id"],
        "stage": "generation"
        if provenance.get("source_type") == "generated"
        else ("listening" if auditum.get("listenings") else "record"),
        "label": summary_line(record)[:80],
        "app": provenance.get("originating_app") or "unknown",
        "origin": provenance.get("origin"),
        "created_at": record.get("created_at"),
        "tags": list(record.get("tags") or []),
        "listening_count": len(auditum.get("listenings") or []),
        "disagreement_count": len(auditum.get("disagreements") or []),
        "route_decision_count": len(auditum.get("route_decisions") or []),
        "decision_only": not bool(auditum.get("listenings"))
        and bool(auditum.get("route_decisions")),
        "ensemble_kind": (auditum.get("ensemble") or {}).get("kind")
        if isinstance(auditum.get("ensemble"), dict)
        else None,
        "revision_of": revision.get("revises_akousma_id"),
        "missing": False,
    }
