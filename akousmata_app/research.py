"""Auto-research sessions over the akousmata — bounded, logged, filed back.

A session takes a question (optionally seed records or tags) and walks the
library: gather → traverse lineage and kinship → read wiki pages → synthesize.
Without an LLM configured it produces a deterministic traversal report — the
graph itself already answers recurrence, kinship, and provenance questions.
With BYOK it runs a bounded plan→act→note loop and writes a topic page, so
answers compound in the wiki instead of evaporating (query, in the llm-wiki
sense: valuable results are filed back).

Sessions run in a worker thread; progress streams over SSE.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Any

from akousmata_app import wiki
from akousmata_app.llm import LLMUnavailable, complete
from akousmata_app.paths import open_store
from akousmata_app.records import summary_line

_SESSIONS: dict[str, "ResearchSession"] = {}
_LOCK = threading.Lock()

SYSTEM_PROMPT = (
    "You are the akousmata researcher: a careful listener's archivist working over a library of "
    "sonic memories (akousma records: provenance + listenings + lineage + kinship). Ground every "
    "claim in the records provided; cite record ids inline as [[record:<id>]]. Distinguish what the "
    "records state from what you infer. Absence from the library is not absence in the world. "
    "Answer in compact markdown."
)


class ResearchSession:
    def __init__(self, question: str, *, seed_ids: list[str] | None = None, tags: list[str] | None = None, max_steps: int = 4):
        self.id = f"res_{uuid.uuid4().hex[:10]}"
        self.question = question.strip()
        self.seed_ids = list(seed_ids or [])
        self.tags = list(tags or [])
        self.max_steps = max(1, min(int(max_steps), 8))
        self.events: list[dict[str, Any]] = []
        self.done = False
        self.result_slug: str | None = None
        self.mode = "deterministic"

    def log(self, kind: str, text: str) -> None:
        self.events.append({"at": time.strftime("%H:%M:%S", time.gmtime()), "kind": kind, "text": text})

    # ── corpus gathering (shared by both modes) ─────────────────────────────
    def gather(self, store) -> list[dict[str, Any]]:
        found: dict[str, dict[str, Any]] = {}

        def take(record: dict[str, Any] | None, why: str) -> None:
            if record and record["akousma_id"] not in found:
                found[record["akousma_id"]] = record
                self.log("gather", f"{record['akousma_id']} — {summary_line(record)[:70]} ({why})")

        for rid in self.seed_ids:
            take(store.get(rid), "seed")
        for tag in self.tags:
            for record in store.query(tag=tag, limit=40):
                take(record, f"tag:{tag}")
        terms = [t for t in self.question.lower().replace("?", " ").split() if len(t) > 3][:6]
        for term in terms:
            for record in store.query(text=term, limit=20):
                take(record, f"text:{term}")
        # one hop of lineage + kinship around everything gathered so far
        for rid in list(found):
            for pid in store.parents(rid):
                take(store.get(pid), "parent")
            for cid in store.children(rid):
                take(store.get(cid), "child")
            if hasattr(store, "related"):
                for link in store.related(rid):
                    take(store.get(link.get("akousma_id", "")), f"relation:{link.get('type')}")
        return list(found.values())

    # ── deterministic traversal report ──────────────────────────────────────
    def deterministic_report(self, store, corpus: list[dict[str, Any]]) -> str:
        by_app: dict[str, int] = {}
        by_tag: dict[str, int] = {}
        kinship: list[str] = []
        for record in corpus:
            app = (record.get("provenance") or {}).get("originating_app") or "unknown"
            by_app[app] = by_app.get(app, 0) + 1
            for tag in record.get("tags") or []:
                by_tag[tag] = by_tag.get(tag, 0) + 1
            for rel in (record.get("lineage") or {}).get("relations") or []:
                kinship.append(
                    f"- [[record:{record['akousma_id']}]] {rel.get('type', 'other').replace('_', ' ')} "
                    f"[[record:{rel.get('target_akousma_id', '?')}]]"
                )
        lines = [
            f"# research: {self.question}",
            "",
            f"_deterministic traversal · {len(corpus)} memories gathered · {time.strftime('%Y-%m-%d', time.gmtime())}_",
            "",
            "## Corpus",
        ]
        for record in sorted(corpus, key=lambda r: r.get("created_at") or ""):
            lines.append(f"- [[record:{record['akousma_id']}|{summary_line(record)[:80]}]] ({(record.get('provenance') or {}).get('originating_app', '?')}, {str(record.get('created_at') or '?')[:10]})")
        lines += ["", "## Shape"]
        lines.append("- by app: " + (", ".join(f"{k} {v}" for k, v in sorted(by_app.items())) or "—"))
        lines.append("- recurring tags: " + (", ".join(f"{k} ({v})" for k, v in sorted(by_tag.items(), key=lambda i: -i[1])[:8]) or "—"))
        if kinship:
            lines += ["", "## Kinship found"] + kinship
        lines += [
            "",
            "## Limits",
            "- This is a traversal, not a listening: it reports what the records say and how they connect.",
            "- Configure an LLM provider in Settings to run synthesizing research over the same corpus.",
        ]
        return "\n".join(lines) + "\n"

    # ── LLM loop ─────────────────────────────────────────────────────────────
    def llm_report(self, store, corpus: list[dict[str, Any]], settings: dict[str, Any]) -> str:
        notes: list[str] = []
        digest = "\n".join(
            f"[[record:{r['akousma_id']}]] {json.dumps({k: r.get(k) for k in ('summary', 'tags', 'provenance', 'lineage', 'listening')}, ensure_ascii=False)[:1400]}"
            for r in corpus[:24]
        )
        step_prompt = (
            f"Question: {self.question}\n\nLibrary excerpts (sonic memory records):\n{digest}\n\n"
            "Step {i} of {n}. Write brief research notes: what do these records establish about the question? "
            "Name gaps: which record ids or tags should be read next (they may not exist — say so)."
        )
        for index in range(self.max_steps - 1):
            self.log("think", f"LLM research step {index + 1}")
            note = complete(step_prompt.replace("{i}", str(index + 1)).replace("{n}", str(self.max_steps)), settings, system=SYSTEM_PROMPT)
            notes.append(note)
            self.log("note", note[:220])
            # follow up on any record ids the model asked for
            wanted = {rid for rid in wiki._WIKILINK_RE.findall(note) if rid[0] == "record"}
            for _, rid in list(wanted)[:6]:
                record = store.get(rid.strip())
                if record is not None and all(r["akousma_id"] != record["akousma_id"] for r in corpus):
                    corpus.append(record)
                    self.log("gather", f"followed [[record:{record['akousma_id']}]]")
        self.log("think", "synthesizing")
        synthesis = complete(
            f"Question: {self.question}\n\nYour accumulated notes:\n\n" + "\n\n---\n\n".join(notes)
            + "\n\nWrite the final research page in markdown: a titled synthesis with inline [[record:<id>]] citations, "
            "a 'What the library holds' section, a 'What remains undetermined' section, and 2-4 suggested next listenings.",
            settings,
            system=SYSTEM_PROMPT,
            max_tokens=2200,
        )
        return synthesis if synthesis.startswith("#") else f"# research: {self.question}\n\n{synthesis}"

    def run(self) -> None:
        try:
            from akousmata_app.settings import load as load_settings

            store = open_store()
            try:
                self.log("start", f"question: {self.question}")
                corpus = self.gather(store)
                if not corpus:
                    self.log("warn", "nothing gathered — the library holds no matching memories")
                settings = load_settings()
                try:
                    report = self.llm_report(store, corpus, settings)
                    self.mode = "llm"
                except LLMUnavailable as exc:
                    self.log("info", f"LLM unavailable ({exc}); producing deterministic traversal")
                    report = self.deterministic_report(store, corpus)
                slug = wiki.slugify(self.question)[:60] or self.id
                wiki.write_topic(slug, report)
                wiki.log_append("query", slug, f"research session {self.id}, mode={self.mode}, corpus={len(corpus)}")
                self.result_slug = wiki.slugify(slug)
                self.log("done", f"topic page written: {self.result_slug}")
            finally:
                store.close()
        except Exception as exc:  # noqa: BLE001 — session must always terminate
            self.log("error", str(exc))
        finally:
            self.done = True


def start(question: str, **kwargs: Any) -> ResearchSession:
    session = ResearchSession(question, **kwargs)
    with _LOCK:
        _SESSIONS[session.id] = session
    thread = threading.Thread(target=session.run, name=f"akousmata-{session.id}", daemon=True)
    thread.start()
    return session


def get(session_id: str) -> ResearchSession | None:
    with _LOCK:
        return _SESSIONS.get(session_id)


def list_sessions() -> list[dict[str, Any]]:
    with _LOCK:
        return [
            {"id": s.id, "question": s.question, "done": s.done, "mode": s.mode, "result_slug": s.result_slug}
            for s in _SESSIONS.values()
        ]
