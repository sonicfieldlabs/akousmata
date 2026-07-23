"""The wiki layer — an LLM-wiki pattern forked into sonic memories.

Three layers, after Karpathy's llm-wiki gist:

- **Raw layer**: the akousma records and audio objects. Producers own them;
  the wiki reads but never rewrites another producer's listening.
- **Wiki layer** (`<store>/wiki/`): markdown pages the navigator owns —
  one page per record, one per tag, topic syntheses from research sessions,
  plus `index.md` (catalog with one-line summaries) and `log.md`
  (append-only operations journal). Pages regenerate deterministically from
  the store; LLM expansions are additive sections, clearly marked.
- **Schema layer**: `docs/wiki-conventions.md` in this repository — public
  conventions for layout, operations, and producer discipline.

Operations: **ingest** (a record arrives → its page, tag pages, and index
update; a log line is appended), **query** (research sessions file their
answers back as topic pages), **lint** (store integrity via `verify()` plus
wiki drift: orphan pages, missing pages, dangling wikilinks).
"""
from __future__ import annotations

import json
import re
import time
from datetime import date
from pathlib import Path
from typing import Any

from akousmata_app.paths import safe_component, wiki_root
from akousmata_app.records import summary_line

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    slug = _SLUG_RE.sub("-", str(value).lower()).strip("-")
    return slug or "untitled"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _dirs() -> dict[str, Path]:
    root = wiki_root()
    dirs = {
        "root": root,
        "records": root / "records",
        "tags": root / "tags",
        "topics": root / "topics",
        "research": root / "research",
        "diary": root / "diary",
    }
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return dirs


def log_append(operation: str, subject: str, note: str = "") -> None:
    root = _dirs()["root"]
    line = f"## [{_now()}] {operation} | {subject}"
    if note:
        line += f" — {note}"
    with open(root / "log.md", "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


# ── page builders (deterministic, grounded in the store) ────────────────────

def record_page(store, record: dict[str, Any]) -> str:
    rid = record["akousma_id"]
    provenance = record.get("provenance") or {}
    audio = record.get("audio") or {}
    lineage = record.get("lineage") or {}
    lines = [
        f"# {summary_line(record)}",
        "",
        f"- id: `{rid}`",
        f"- created: {record.get('created_at', '?')}",
        f"- app: {provenance.get('originating_app', 'unknown')} · origin: {provenance.get('origin', '?')} · source: {provenance.get('source_type', '?')}",
    ]
    if audio.get("duration_seconds"):
        lines.append(f"- duration: {audio['duration_seconds']} s")
    if provenance.get("consent_status"):
        lines.append(f"- consent: {provenance['consent_status']}")
    if provenance.get("pipeline_effects"):
        lines.append(f"- pipeline: {', '.join(provenance['pipeline_effects'])}")
    tags = record.get("tags") or []
    if tags:
        lines.append("- tags: " + ", ".join(f"[[tag:{slugify(t)}|{t}]]" for t in tags))
    lines.append("")

    listening = record.get("listening") or {}
    if listening:
        lines.append("## Listenings")
        for namespace in sorted(listening):
            entry = listening[namespace]
            if not isinstance(entry, dict):
                continue
            payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else entry
            contract = entry.get("contract")
            heading = f"### {namespace}" + (f" · `{contract}`" if contract else "")
            lines.append(heading)
            text = entry.get("summary") if isinstance(entry.get("summary"), str) else None
            if not text and isinstance(payload, dict):
                for key in ("caption", "summary", "main_reading", "notes", "brief"):
                    value = payload.get(key)
                    if isinstance(value, str) and value.strip():
                        text = value.strip()
                        break
            lines.append(text or "_structured payload without a prose summary_")
            lines.append("")

    auditum = record.get("auditum") if isinstance(record.get("auditum"), dict) else None
    if auditum:
        lines.append("## Accountable auditum")
        lines.append(f"- contract: `{auditum.get('contract', '?')}`")
        for item in auditum.get("listenings") or []:
            if not isinstance(item, dict):
                continue
            route = " → ".join(item.get("route") or [])
            suffix = f" · route: {route}" if route else ""
            lines.append(
                f"- listening `{item.get('listening_id', '?')}`: "
                f"{item.get('listener_id', '?')} ({item.get('listener_type', '?')}) · "
                f"`{item.get('report_namespace', '?')}`{suffix}"
            )
        for disagreement in auditum.get("disagreements") or []:
            if not isinstance(disagreement, dict):
                continue
            lines.append(
                f"- disagreement `{disagreement.get('id', '?')}` — "
                f"{disagreement.get('subject', '?')} ({disagreement.get('status', '?')})"
            )
            for position in disagreement.get("positions") or []:
                if isinstance(position, dict):
                    lines.append(
                        f"  - `{position.get('listening_id', '?')}`: "
                        f"{position.get('statement', '?')}"
                    )
        for absence in auditum.get("honest_absences") or []:
            if isinstance(absence, dict):
                count = f" ×{absence['count']}" if absence.get("count") is not None else ""
                lines.append(
                    f"- absence: {str(absence.get('kind', '?')).replace('_', ' ')} · "
                    f"{absence.get('subject', '?')}{count} — {absence.get('attributed_to', 'unattributed')}"
                )
        for action in auditum.get("actions") or []:
            if isinstance(action, dict):
                authority = action.get("authority") if isinstance(action.get("authority"), dict) else {}
                lines.append(
                    f"- action `{action.get('action_id', '?')}`: {action.get('status', '?')} · "
                    f"{action.get('proposal', '?')} — authority `{authority.get('mode', 'missing')}`"
                )
        revision = auditum.get("revision") if isinstance(auditum.get("revision"), dict) else None
        if revision and revision.get("revises_akousma_id"):
            lines.append(
                f"- revision of [[record:{revision['revises_akousma_id']}]] — "
                f"{revision.get('reason', 'reason not recorded')}"
            )
        lines.append("")

    parents = lineage.get("parent_akousma_ids") or []
    relations = lineage.get("relations") or []
    children = store.children(rid)
    if parents or children or relations:
        lines.append("## Lineage and kinship")
        for parent in parents:
            lines.append(f"- made from [[record:{parent}]]")
        for child in children:
            lines.append(f"- became [[record:{child}]]")
        for rel in relations:
            note = f" — {rel['note']}" if rel.get("note") else ""
            lines.append(f"- {rel.get('type', 'other').replace('_', ' ')} [[record:{rel.get('target_akousma_id', '?')}]]{note}")
        lines.append("")

    evaluation = (record.get("extensions") or {}).get("algophony.eval")
    if evaluation:
        lines.append("## Evaluation")
        lines.append("```json")
        lines.append(json.dumps(evaluation, indent=2, ensure_ascii=False))
        lines.append("```")
        lines.append("")

    annotations = record.get("annotations") or {}
    if annotations:
        lines.append("## Annotations")
        for key, value in annotations.items():
            lines.append(f"- **{key}**: {value}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def tag_page(store, tag: str) -> str:
    records = store.query(tag=tag, limit=500)
    lines = [f"# tag: {tag}", "", f"{len(records)} memories carry this tag.", ""]
    for record in records:
        lines.append(f"- [[record:{record['akousma_id']}|{summary_line(record)[:90]}]] ({record.get('created_at', '?')[:10]})")
    return "\n".join(lines) + "\n"


def build_index(store) -> str:
    dirs = _dirs()
    rows = store.conn.execute("SELECT record FROM akousmata ORDER BY created_at DESC").fetchall()
    records = [json.loads(r["record"]) for r in rows]
    tags = store.tags() if hasattr(store, "tags") else []
    topics = sorted(p.stem for p in dirs["topics"].glob("*.md"))
    lines = [
        "# akousmata — index",
        "",
        f"_{len(records)} memories · {len(tags)} tags · {len(topics)} topics · rebuilt {_now()}_",
        "",
        "## Topics",
    ]
    lines += [f"- [[topic:{slug}]]" for slug in topics] or ["- _none yet — research sessions file their answers here_"]
    lines += ["", "## Tags"]
    lines += [f"- [[tag:{slugify(t['tag'])}|{t['tag']}]] ({t['count']})" for t in tags] or ["- _none yet_"]
    lines += ["", "## Memories"]
    for record in records:
        lines.append(f"- [[record:{record['akousma_id']}|{summary_line(record)[:90]}]] — {record.get('created_at', '?')[:10]}")
    return "\n".join(lines) + "\n"


# ── operations ───────────────────────────────────────────────────────────────

def ingest(store, akousma_id: str) -> dict[str, Any]:
    """One record arrives (or changes): refresh its page, its tag pages, and
    the index; log the pass. A single ingest may touch many pages."""
    record = store.get(akousma_id)
    if record is None:
        raise KeyError(f"akousma not found: {akousma_id}")
    record_id = safe_component(str(record["akousma_id"]), label="akousma id")
    dirs = _dirs()
    touched = []
    page = dirs["records"] / f"{record_id}.md"
    page.write_text(record_page(store, record), encoding="utf-8")
    touched.append(str(page.relative_to(dirs["root"])))
    for tag in record.get("tags") or []:
        path = dirs["tags"] / f"{slugify(tag)}.md"
        path.write_text(tag_page(store, tag), encoding="utf-8")
        touched.append(str(path.relative_to(dirs["root"])))
    (dirs["root"] / "index.md").write_text(build_index(store), encoding="utf-8")
    touched.append("index.md")
    log_append("ingest", record_id, f"{len(touched)} pages touched")
    return {"akousma_id": record_id, "touched": touched}


def rebuild(store) -> dict[str, Any]:
    """Full deterministic regeneration of record pages, tag pages, and index.
    Topic pages (research output) are preserved — they are synthesis, not
    derivation."""
    dirs = _dirs()
    rows = store.conn.execute("SELECT record FROM akousmata").fetchall()
    records = [json.loads(r["record"]) for r in rows]
    known_ids = set()
    for record in records:
        record_id = safe_component(str(record["akousma_id"]), label="akousma id")
        known_ids.add(record_id)
        (dirs["records"] / f"{record_id}.md").write_text(record_page(store, record), encoding="utf-8")
    tags = store.tags() if hasattr(store, "tags") else []
    known_tags = set()
    for item in tags:
        slug = slugify(item["tag"])
        known_tags.add(slug)
        (dirs["tags"] / f"{slug}.md").write_text(tag_page(store, item["tag"]), encoding="utf-8")
    orphans = []
    for page in dirs["records"].glob("*.md"):
        if page.stem not in known_ids:
            orphans.append(f"records/{page.name}")
    for page in dirs["tags"].glob("*.md"):
        if page.stem not in known_tags:
            orphans.append(f"tags/{page.name}")
    (dirs["root"] / "index.md").write_text(build_index(store), encoding="utf-8")
    log_append("rebuild", "full wiki", f"{len(records)} records, {len(tags)} tags, {len(orphans)} orphan pages kept")
    return {"records": len(records), "tags": len(tags), "orphan_pages": orphans}


_WIKILINK_RE = re.compile(r"\[\[(record|tag|topic):([^\]|]+)(?:\|[^\]]*)?\]\]")


def lint(store) -> dict[str, Any]:
    """Drift prevention — the pattern only works if this runs. Store
    integrity (dangling parents/relations, missing audio, invalid records)
    plus wiki drift (missing/orphan pages, dangling wikilinks)."""
    dirs = _dirs()
    report: dict[str, Any] = {"store": store.verify() if hasattr(store, "verify") else {}}
    rows = store.conn.execute("SELECT akousma_id FROM akousmata").fetchall()
    ids = {r["akousma_id"] for r in rows}
    record_pages = {p.stem for p in dirs["records"].glob("*.md")}
    report["missing_record_pages"] = sorted(ids - record_pages)
    report["orphan_record_pages"] = sorted(record_pages - ids)
    tag_slugs = {slugify(t["tag"]) for t in (store.tags() if hasattr(store, "tags") else [])}
    tag_pages = {p.stem for p in dirs["tags"].glob("*.md")}
    report["orphan_tag_pages"] = sorted(tag_pages - tag_slugs)
    topic_slugs = {p.stem for p in dirs["topics"].glob("*.md")}
    dangling: list[str] = []
    for page in list(dirs["records"].glob("*.md")) + list(dirs["tags"].glob("*.md")) + list(dirs["topics"].glob("*.md")):
        text = page.read_text(encoding="utf-8")
        for kind, target in _WIKILINK_RE.findall(text):
            target = target.strip()
            missing = (
                (kind == "record" and target not in ids)
                or (kind == "tag" and target not in tag_slugs)
                or (kind == "topic" and target not in topic_slugs)
            )
            if missing:
                dangling.append(f"{page.relative_to(dirs['root'])} -> [[{kind}:{target}]]")
    report["dangling_wikilinks"] = dangling
    log_append("lint", "wiki + store", f"{len(dangling)} dangling links")
    return report


def read_page(kind: str, name: str) -> str | None:
    dirs = _dirs()
    folder = {
        "record": dirs["records"],
        "tag": dirs["tags"],
        "topic": dirs["topics"],
        "research": dirs["research"],
        "diary": dirs["diary"],
    }.get(kind)
    if folder is None:
        return None
    try:
        page_name = safe_component(name, label="wiki page name")
    except ValueError:
        return None
    path = folder / f"{page_name}.md"
    return path.read_text(encoding="utf-8") if path.exists() else None


def write_topic(slug: str, markdown: str) -> str:
    dirs = _dirs()
    path = dirs["topics"] / f"{slugify(slug)}.md"
    path.write_text(markdown, encoding="utf-8")
    log_append("topic", slugify(slug))
    return str(path)


def diary_digest(store, day: str) -> str:
    """One day's page: diary entries first, then everything else the library
    gained that day — the listening diary as a maintained wiki layer."""
    day = date.fromisoformat(day).isoformat()
    dirs = _dirs()
    records = store.query(since=f"{day}T00:00:00Z", until=f"{day}T23:59:59Z", limit=500)
    diary_entries = []
    other = []
    for record in records:
        entry = (record.get("listening") or {}).get("human.note") or {}
        payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else {}
        if payload.get("kind") == "diary":
            diary_entries.append(record)
        else:
            other.append(record)
    lines = [f"# diary — {day}", ""]
    if diary_entries:
        lines.append("## What you listened")
        for record in diary_entries:
            entry = record["listening"]["human.note"]
            payload = entry.get("payload") or {}
            when = str(record.get("created_at") or "")[11:16]
            lines.append(f"- **{when}** [[record:{record['akousma_id']}|{summary_line(record)[:80]}]]")
            notes = payload.get("notes")
            if isinstance(notes, str) and notes.strip() and notes.strip() != summary_line(record):
                lines.append(f"  - {notes.strip()[:300]}")
    else:
        lines.append("_no diary entries this day_")
    if other:
        lines += ["", "## What the library gained"]
        for record in other:
            app = (record.get("provenance") or {}).get("originating_app") or "?"
            lines.append(f"- [[record:{record['akousma_id']}|{summary_line(record)[:80]}]] ({app})")
    lines += ["", f"_{len(diary_entries)} diary entries · {len(other)} other memories · refreshed {_now()}_"]
    page = "\n".join(lines) + "\n"
    (dirs["diary"] / f"{day}.md").write_text(page, encoding="utf-8")
    log_append("diary", day, f"{len(diary_entries)} entries, {len(other)} other memories")
    return page


def list_pages() -> dict[str, list[str]]:
    dirs = _dirs()
    return {
        "records": sorted(p.stem for p in dirs["records"].glob("*.md")),
        "tags": sorted(p.stem for p in dirs["tags"].glob("*.md")),
        "topics": sorted(p.stem for p in dirs["topics"].glob("*.md")),
        "research": sorted(p.stem for p in dirs["research"].glob("*.md")),
        "diary": sorted((p.stem for p in dirs["diary"].glob("*.md")), reverse=True),
        "has_index": (dirs["root"] / "index.md").exists(),
    }
