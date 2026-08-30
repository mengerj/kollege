"""Opt-in LLM-/Verlaufs-Traces für Live-Debugging (Schritt 8.21).

Motiv: Ein Live-Vorfall (Schritt 8.20) war nur per Code-Rekonstruktion
analysierbar, weil nichts vom LLM-Verkehr (Prompts, Tool-Calls, Rückgaben)
aufgezeichnet wurde. Traces schließen diese Lücke — **bewusst getrennt** vom
inhaltsfreien Dauer-Log (Datensparsamkeit, Designprinzip 5): Traces enthalten
Volltext und sind per Default aus (``KOLLEGE_TRACE=1`` aktiviert sie).

Ein ``TraceWriter`` schreibt eine JSON-Zeile pro Ereignis nach
``data/traces/<datum>.jsonl`` (append-only): ``{"ts", "event", "run_id",
"payload"}``. ``run_id`` gruppiert alle Ereignisse **einer** eingehenden
Nachricht (Orchestrator-Ereignisse + alle darin ausgelösten LLM-Läufe) — so
lässt sich ein einzelner Vorgang mit ``scripts/show_trace.py --run <id>``
vollständig herausfiltern, während die Tagesdatei in chronologischer
Reihenfolge den gesamten Faden über mehrere Nachrichten hinweg zeigt.
"""

from __future__ import annotations

import datetime
import json
import uuid
from pathlib import Path
from typing import Any, Protocol

__all__ = [
    "JsonlTraceWriter",
    "NoopTraceWriter",
    "TraceWriter",
    "build_trace_writer",
    "new_run_id",
]


def new_run_id() -> str:
    """Neue, zufällige Lauf-ID (verknüpft zusammengehörige Trace-Ereignisse)."""
    return uuid.uuid4().hex


class TraceWriter(Protocol):
    """Schnittstelle für das Schreiben eines Trace-Ereignisses."""

    def write(self, event: str, run_id: str, payload: dict[str, Any]) -> None: ...


class NoopTraceWriter:
    """Default-Writer: verwirft alle Ereignisse (Tracing aus)."""

    def write(self, event: str, run_id: str, payload: dict[str, Any]) -> None:
        pass


class JsonlTraceWriter:
    """Schreibt Trace-Ereignisse append-only als JSONL, eine Datei pro Tag."""

    def __init__(self, trace_dir: Path) -> None:
        self._trace_dir = trace_dir
        self._trace_dir.mkdir(parents=True, exist_ok=True)

    def write(self, event: str, run_id: str, payload: dict[str, Any]) -> None:
        now = datetime.datetime.now(tz=datetime.UTC)
        path = self._trace_dir / f"{now.date().isoformat()}.jsonl"
        line = {"ts": now.isoformat(), "event": event, "run_id": run_id, "payload": payload}
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")


def build_trace_writer(*, enabled: bool, trace_dir: str) -> TraceWriter:
    """``TraceWriter`` aus Settings-Werten erzeugen (``NoopTraceWriter`` wenn aus)."""
    if not enabled:
        return NoopTraceWriter()
    return JsonlTraceWriter(Path(trace_dir))
