"""Listening circuits and run memories, read and kept through the store.

A run memory (``earworm/run-memory/v1``) is what a listening run remembers of itself; a circuit
(``earworm/listening-circuit/v1``) rides on each record and holds the moves that produced its
listenings. Akousmata keeps run memories compare-and-set for their owner (Khipu during a run) and
answers recall questions: this run's moves, this source's moves across runs, one record's circuit.
"""

from __future__ import annotations

from typing import Any

from akousma.listening_circuit import CIRCUIT_EXTENSION, RUN_MEMORY_CONTRACT, listening_circuit_errors


def runs(store, *, limit: int = 100) -> dict[str, Any]:
    return {"contract": RUN_MEMORY_CONTRACT, "runs": store.run_memories(limit=limit)}


def run_detail(store, session_id: str, *, limit: int = 2000) -> dict[str, Any] | None:
    memory = store.run_memory(session_id)
    steps = store.circuit_steps(session_id=session_id, limit=limit)
    if memory is None and not steps:
        return None
    return {"session_id": session_id, "memory": memory, "steps": steps}


def source_steps(store, source_key: str, *, move: str | None = None, limit: int = 500) -> dict[str, Any]:
    return {"source_key": source_key, "steps": store.circuit_steps(source_key=source_key, move=move, limit=limit)}


def record_circuit(store, akousma_id: str) -> dict[str, Any] | None:
    record = store.get(akousma_id)
    if record is None:
        return None
    extensions = record.get("extensions") if isinstance(record.get("extensions"), dict) else {}
    circuit = extensions.get(CIRCUIT_EXTENSION)
    if circuit is None:
        return {"akousma_id": akousma_id, "circuit": None, "targets": {}}
    targets: dict[str, str] = {}
    for step in circuit.get("steps", []):
        for key in ("from_akousma_id", "to_akousma_id"):
            ref = step.get(key)
            if isinstance(ref, str) and ref and ref not in targets:
                if store.get(ref) is not None:
                    targets[ref] = "available"
                elif store.forgotten(ref) is not None:
                    targets[ref] = "forgotten"
                else:
                    targets[ref] = "unavailable"
    return {
        "akousma_id": akousma_id,
        "circuit": circuit,
        "errors": listening_circuit_errors(circuit, record),
        "targets": targets,
    }


def put_memory(store, memory: dict[str, Any], *, expected_revision: int | None) -> dict[str, Any]:
    stored = store.put_run_memory(memory, expected_revision=expected_revision)
    return {"session_id": stored["session_id"], "revision": stored["revision"]}
