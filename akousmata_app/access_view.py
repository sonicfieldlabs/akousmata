"""Owner-only qualified facets and unmodified apparatus/access declarations."""

from copy import deepcopy
import json

# A SQL view projects existing canonical storage; no duplicate record/index store.
_SELECTS = {
    "subject": "SELECT a.akousma_id, 'subject' kind, json_extract(a.record,'$.subject') value FROM akousmata a UNION SELECT a.akousma_id,'subject',json_extract(c.value,'$.subject_ref') FROM akousmata a,json_each(a.record,'$.extensions.earworm_listening_context.contexts') c",
    "recipient": "SELECT a.akousma_id,'recipient',json_extract(r.value,'$.id') FROM akousmata a,json_each(a.record,'$.extensions.earworm_listening_context.contexts') c,json_each(c.value,'$.recipients') r",
    "human_access": "SELECT a.akousma_id,'human_access',COALESCE(json_extract(h.value,'$.status'),'undeclared') FROM akousmata a LEFT JOIN json_each(a.record,'$.extensions.earworm_listening_access.human_access') h",
    "register": "SELECT a.akousma_id,'register',r.value FROM akousmata a,json_each(a.record,'$.extensions.earworm_matter_context.registers') r",
    "scale": "SELECT a.akousma_id,'scale',s.value FROM akousmata a,json_each(a.record,'$.extensions.earworm_matter_context.scales') s",
    "listener_type": "SELECT akousma_id,'listener_type',listener_type FROM listener_type_index",
}


def ensure(store):
    store.conn.execute(
        "CREATE TEMP VIEW IF NOT EXISTS navigator_facets AS "
        + " UNION ".join(_SELECTS.values())
    )


def options(store, limit=200):
    ensure(store)
    return {
        kind: [
            dict(r)
            for r in store.conn.execute(
                "SELECT value,COUNT(DISTINCT akousma_id) count FROM navigator_facets WHERE kind=? AND value IS NOT NULL GROUP BY value ORDER BY value LIMIT ?",
                (kind, limit),
            )
        ]
        for kind in _SELECTS
    }


def find(store, facets, filters, limit):
    ensure(store)
    clauses = []
    args = []
    for kind, value in facets.items():
        if kind not in _SELECTS:
            raise ValueError("Unknown facet")
        if not isinstance(value, str) or not value or len(value) > 4096:
            raise ValueError("Invalid facet value")
        clauses.append(
            "EXISTS(SELECT 1 FROM navigator_facets f WHERE f.akousma_id=a.akousma_id AND f.kind=? AND f.value=?)"
        )
        args.extend([kind, value])
    columns = {
        "app": "originating_app",
        "origin": "origin",
        "source_type": "source_type",
        "covenant_id": "covenant_id",
        "record_class_filter": "record_class",
        "revision_of": "revision_of",
    }
    for key, column in columns.items():
        if filters.get(key) is not None:
            clauses.append(f"a.{column}=?")
            args.append(filters[key])
    for key, op in [("since", ">="), ("until", "<=")]:
        if filters.get(key) is not None:
            clauses.append(f"a.created_at{op}?")
            args.append(filters[key])
    if filters.get("text") is not None:
        clauses.append("a.record LIKE ?")
        args.append("%" + filters["text"] + "%")
    if filters.get("tag") is not None:
        clauses.append(
            "EXISTS(SELECT 1 FROM json_each(a.record,'$.tags') t WHERE t.value=?)"
        )
        args.append(filters["tag"])
    flags = {
        "has_auditum": "auditum_contract IS NOT NULL",
        "has_disagreement": "disagreement_count>0",
        "has_route_decision": "route_decision_count>0",
        "has_stop_decision": "stop_decision_count>0",
    }
    for key, condition in flags.items():
        if filters.get(key) is not None:
            clauses.append(f"({condition})" if filters[key] else f"NOT ({condition})")
    if filters.get("listener_type") is not None:
        clauses.append(
            "EXISTS(SELECT 1 FROM listener_type_index l WHERE l.akousma_id=a.akousma_id AND l.listener_type=?)"
        )
        args.append(filters["listener_type"])
    return [
        json.loads(r["record"])
        for r in store.conn.execute(
            "SELECT a.record FROM akousmata a WHERE "
            + " AND ".join(clauses)
            + " ORDER BY a.created_at DESC,a.akousma_id LIMIT ?",
            (*args, limit),
        )
    ]


def project(record):
    ext = record.get("extensions", {})
    access = ext.get("earworm_listening_access")
    context = ext.get("earworm_listening_context", {})
    matter = ext.get("earworm_matter_context")
    return deepcopy(
        dict(
            contract="akousmata/access-view/v1",
            declaration=access,
            status="declared" if access else "undeclared",
            contexts=context.get("contexts", []),
            matter_context=matter,
            limitation="Capture, sampled representation, model input and human access are separate declarations; none establishes another.",
        )
    )
