"""Schritt-8.21-Trace-Viewer: LLM-/Verlaufs-Traces menschenlesbar anzeigen.

Liest JSONL-Trace-Dateien (``data/traces/<datum>.jsonl``, geschrieben von
``kollege.trace.JsonlTraceWriter`` bei ``KOLLEGE_TRACE=1``) und rendert sie
chronologisch: Nachrichtenerkennung, Routing-Entscheidung, jeder LLM-Lauf
(Kind, Modell, kompletter Prompt, Tool-Call-Sequenz mit Argumenten/Rückgaben,
Tokens/Latenz/Pfad, finales Ergebnis), Vorschlag/Rückfrage, Bestätigung/
Ablehnung, Persistenz, Fehler. Zweck: in einer Live-Session in Sekunden
beantworten, *warum* ein Eintrag fehlte oder verschwand (siehe
docs/live-testing-guide.md §3e).

Aufruf:
    uv run python scripts/show_trace.py                  # heute, alle Läufe
    uv run python scripts/show_trace.py --date 2026-07-02
    uv run python scripts/show_trace.py --last 3          # nur die letzten 3 Läufe
    uv run python scripts/show_trace.py --run <run_id>    # ein Lauf komplett
    uv run python scripts/show_trace.py --full            # Prompts/Inhalte ungekürzt

Traces enthalten Volltext (Prompts, Tool-Argumente) — Datensparsamkeit
(Designprinzip 5): nach der Debugging-Phase mit ``rm -r data/traces`` löschen.
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from kollege.config import load_settings

_TRUNCATE_CHARS = 400


def _truncate(text: str, *, full: bool) -> str:
    """Text für die Terminal-Ausgabe kürzen, außer ``--full`` ist gesetzt."""
    if full or len(text) <= _TRUNCATE_CHARS:
        return text
    rest = len(text) - _TRUNCATE_CHARS
    return f"{text[:_TRUNCATE_CHARS]}… [{rest} weitere Zeichen, --full für Volltext]"


def _indent(text: str, prefix: str = "    ") -> str:
    return "\n".join(prefix + line for line in text.splitlines())


def load_events(trace_dir: Path, date: str | None) -> list[dict[str, Any]]:
    """Ereignisse aus einer Tagesdatei oder — ohne ``date`` — allen Tagesdateien laden.

    Chronologisch, da die Dateien append-only geschrieben werden und
    ``Path.glob`` Dateinamen (⇒ Datum) alphabetisch sortiert zurückgibt.
    """
    paths = [trace_dir / f"{date}.jsonl"] if date is not None else sorted(trace_dir.glob("*.jsonl"))
    events: list[dict[str, Any]] = []
    for path in paths:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))
    return events


def filter_by_run(events: list[dict[str, Any]], run_id: str) -> list[dict[str, Any]]:
    """Nur Ereignisse mit genau dieser ``run_id`` — ein Lauf komplett."""
    return [e for e in events if e.get("run_id") == run_id]


def filter_last_n_runs(events: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    """Nur Ereignisse der zeitlich letzten ``n`` Läufe (nach ``run_id``)."""
    order: list[str] = []
    for e in events:
        rid = e.get("run_id")
        if rid is not None and rid not in order:
            order.append(rid)
    keep = set(order[-n:])
    return [e for e in events if e.get("run_id") in keep]


def _format_message_part(part: dict[str, Any], *, full: bool) -> str:
    kind = part.get("part_kind", "?")
    if kind == "tool-call":
        return f"→ Tool-Call {part.get('tool_name')}({part.get('args')})"
    if kind == "tool-return":
        content = _truncate(str(part.get("content")), full=full)
        return f"← Tool-Return {part.get('tool_name')}: {content}"
    if kind == "retry-prompt":
        return f"⟳ Retry: {_truncate(str(part.get('content')), full=full)}"
    if kind in ("text", "system-prompt", "user-prompt"):
        return f"{kind}: {_truncate(str(part.get('content')), full=full)}"
    return f"{kind}: {part}"


def _format_message(msg: dict[str, Any], *, full: bool) -> str:
    kind = msg.get("kind", "?")
    parts = [_format_message_part(p, full=full) for p in msg.get("parts", [])]
    return f"{kind}:\n" + _indent(" \n".join(parts)) if parts else f"{kind}: (keine Parts)"


def format_event(event: dict[str, Any], *, full: bool) -> str:
    """Ein einzelnes Trace-Ereignis lesbar formatieren."""
    ts = event.get("ts", "?")
    name = event.get("event", "?")
    run_id = event.get("run_id", "?")
    payload: dict[str, Any] = event.get("payload", {})
    lines = [f"[{ts}] {name}  (run={run_id})"]

    if name == "message_received":
        lines.append(f"  Absender: {payload.get('sender')}  Art: {payload.get('kind')}")
        if payload.get("text"):
            lines.append(f"  Text: {_truncate(str(payload['text']), full=full)}")
    elif name == "routing":
        lines.append(f"  Entscheidung: {payload.get('entscheidung')}")
    elif name == "llm_run_start":
        model = f"{payload.get('provider')}/{payload.get('model')}"
        lines.append(f"  Kind: {payload.get('kind')}  Modell: {model}")
        lines.append(f"  Prompt:\n{_indent(_truncate(str(payload.get('prompt', '')), full=full))}")
    elif name in ("llm_run_result", "llm_run_error"):
        lines.append(
            f"  Kind: {payload.get('kind')}  Pfad: {payload.get('path')}  "
            f"Latenz: {payload.get('latency_s')}s"
        )
        if name == "llm_run_result":
            usage = payload.get("usage", {})
            lines.append(
                f"  Tokens: input={usage.get('input_tokens')} output={usage.get('output_tokens')} "
                f"requests={usage.get('requests')}"
            )
            output = json.dumps(payload.get("output"), ensure_ascii=False)
            lines.append(f"  Ergebnis: {_truncate(output, full=full)}")
        else:
            exc_type = payload.get("exception_type")
            lines.append(f"  Fehler: {exc_type}: {payload.get('exception_text')}")
        messages = payload.get("messages", [])
        if messages:
            lines.append("  Messages:")
            for msg in messages:
                lines.append(_indent(_format_message(msg, full=full)))
    elif name == "proposal_sent":
        lines.append(f"  Vorschlag:\n{_indent(_truncate(str(payload.get('text', '')), full=full))}")
    elif name == "clarification_sent":
        lines.append(f"  Rückfrage: {payload.get('frage')}")
    elif name == "confirmed":
        lines.append(f"  Bestätigt, Auswahl: {payload.get('indices') or 'alle'}")
    elif name == "rejected":
        lines.append("  Verworfen.")
    elif name == "persisted":
        count = payload.get("count")
        lines.append(f"  Gespeichert: {count} Eintrag/Einträge — {payload.get('labels')}")
    elif name == "error":
        phase = payload.get("phase", "orchestrator")
        exc_type = payload.get("exception_type")
        lines.append(f"  Fehler ({phase}): {exc_type}: {payload.get('exception_text')}")
    else:
        lines.append(f"  {payload}")
    return "\n".join(lines)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--date", help="Datum YYYY-MM-DD (Default: heute)")
    parser.add_argument("--last", type=int, metavar="N", help="Nur die letzten N Läufe zeigen")
    parser.add_argument("--run", metavar="RUN_ID", help="Nur diesen einen Lauf komplett zeigen")
    parser.add_argument("--full", action="store_true", help="Prompts/Tool-Inhalte ungekürzt zeigen")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    settings = load_settings()
    trace_dir = Path(settings.trace_dir)

    if not trace_dir.exists():
        print(
            f"Kein Trace-Verzeichnis gefunden: {trace_dir}\n"
            "Traces aktivieren: KOLLEGE_TRACE=1 (siehe docs/live-testing-guide.md §3e)."
        )
        return 1

    if args.run is not None:
        events = filter_by_run(load_events(trace_dir, args.date), args.run)
        if not events:
            scope = f" am {args.date}" if args.date else ""
            print(f"Keine Ereignisse für run_id={args.run}{scope} gefunden.")
            return 1
    else:
        date = args.date or datetime.datetime.now(tz=datetime.UTC).date().isoformat()
        events = load_events(trace_dir, date)
        if not events:
            print(f"Keine Trace-Ereignisse für {date}.")
            return 0
        if args.last is not None:
            events = filter_last_n_runs(events, args.last)

    for event in events:
        print(format_event(event, full=args.full))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
