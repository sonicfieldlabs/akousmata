"""The akousmata as a graph: lineage (causal) + relations (kinship).

Two edge kinds, never conflated — parents mean "made from", relations mean
"belongs with". Both are walkable; the navigator draws them differently.
"""
from __future__ import annotations

import json
from typing import Any

from akousmata_app.records import summary_line


def full_graph(store, *, limit: int = 400) -> dict[str, Any]:
    rows = store.conn.execute(
        "SELECT record FROM akousmata ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    records = [json.loads(r["record"]) for r in rows]
    ids = {r["akousma_id"] for r in records}
    nodes = [_node(r) for r in records]
    edges: list[dict[str, Any]] = []
    for record in records:
        rid = record["akousma_id"]
        lineage = record.get("lineage") or {}
        for parent in lineage.get("parent_akousma_ids") or []:
            edges.append({"from": parent, "to": rid, "kind": "lineage", "missing": parent not in ids})
        for rel in lineage.get("relations") or []:
            target = rel.get("target_akousma_id", "")
            edges.append({
                "from": rid,
                "to": target,
                "kind": "relation",
                "type": rel.get("type", "other"),
                "missing": target not in ids,
            })
    return {"nodes": nodes, "edges": edges, "truncated": len(records) >= limit}


def neighborhood(store, akousma_id: str, *, depth: int = 2, limit: int = 120) -> dict[str, Any]:
    """The memory's surroundings: breadth-first over both edge kinds."""
    seen: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    edge_keys: set[tuple] = set()
    frontier = [akousma_id]
    for _ in range(max(1, depth)):
        next_frontier: list[str] = []
        for rid in frontier:
            if rid in seen or len(seen) >= limit:
                continue
            record = store.get(rid)
            if record is None:
                seen[rid] = {"id": rid, "missing": True, "label": "(missing)", "app": "unknown"}
                continue
            seen[rid] = _node(record)
            lineage = record.get("lineage") or {}
            for parent in lineage.get("parent_akousma_ids") or []:
                key = (parent, rid, "lineage", "")
                if key not in edge_keys:
                    edge_keys.add(key)
                    edges.append({"from": parent, "to": rid, "kind": "lineage"})
                next_frontier.append(parent)
            for child in store.children(rid):
                key = (rid, child, "lineage", "")
                if key not in edge_keys:
                    edge_keys.add(key)
                    edges.append({"from": rid, "to": child, "kind": "lineage"})
                next_frontier.append(child)
            for rel in lineage.get("relations") or []:
                target = rel.get("target_akousma_id", "")
                key = (rid, target, "relation", rel.get("type", ""))
                if key not in edge_keys:
                    edge_keys.add(key)
                    edges.append({"from": rid, "to": target, "kind": "relation", "type": rel.get("type", "other")})
                next_frontier.append(target)
            if hasattr(store, "related"):
                for link in store.related(rid):
                    other = link.get("akousma_id", "")
                    if link.get("direction") == "incoming":
                        key = (other, rid, "relation", link.get("type", ""))
                        if key not in edge_keys:
                            edge_keys.add(key)
                            edges.append({"from": other, "to": rid, "kind": "relation", "type": link.get("type", "other")})
                        next_frontier.append(other)
        frontier = [rid for rid in next_frontier if rid not in seen]
        if not frontier:
            break
    for edge in edges:
        edge["missing"] = edge["from"] not in seen or edge["to"] not in seen
    return {"focus": akousma_id, "nodes": list(seen.values()), "edges": edges}


def _node(record: dict[str, Any]) -> dict[str, Any]:
    provenance = record.get("provenance") or {}
    auditum = record.get("auditum") if isinstance(record.get("auditum"), dict) else {}
    revision = auditum.get("revision") if isinstance(auditum.get("revision"), dict) else {}
    return {
        "id": record["akousma_id"],
        "label": summary_line(record)[:80],
        "app": provenance.get("originating_app") or "unknown",
        "origin": provenance.get("origin"),
        "created_at": record.get("created_at"),
        "tags": list(record.get("tags") or []),
        "listening_count": len(auditum.get("listenings") or []),
        "disagreement_count": len(auditum.get("disagreements") or []),
        "revision_of": revision.get("revises_akousma_id"),
        "missing": False,
    }
