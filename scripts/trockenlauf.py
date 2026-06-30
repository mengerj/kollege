"""Schritt-8-Trockenlauf: lokale End-to-End-Simulation ohne echtes Signal.

Testet die Komplettkette mit Fake-Projekten/Daten:

  Transkript → Agent (Ollama) → Vorschlag → Bestätigung → SQLite-DB

Kanal:       MemoryChannel (kein Signal benötigt)
Transcriber: StubTranscriber (Fake-Text) + optional FasterWhisper auf WAV-Fixture
LLM:         Ollama lokal (qwen2.5:7b-instruct)
DB:          temp SQLite (wird am Ende gelöscht)

Aufruf:
    uv run python scripts/trockenlauf.py

Optionen:
    --model MODEL   Ollama-Modell (Standard: qwen2.5:7b-instruct)
    --provider {ollama,anthropic,openai}
    --whisper       Auch FasterWhisper-Test auf Dummy-WAV durchführen
"""

from __future__ import annotations

import argparse
import sqlite3
import struct
import sys
import tempfile
import wave
from pathlib import Path

# Sicherstellen, dass src/ im Python-Pfad liegt (bei direktem Aufruf).
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from kollege.channels import IncomingMessage, MemoryChannel
from kollege.config import LLMProvider, Settings
from kollege.db import Repository
from kollege.orchestrator import Orchestrator
from kollege.transcription import StubTranscriber

# Fake-Projekte / Transkripte für den Trockenlauf
_SZENARIEN: list[dict[str, str]] = [
    {
        "label": "Neue Aufgabe (einfach)",
        "text": (
            "Ich muss morgen Frau Müller vom Gartenamt Beispielstadt zurückrufen wegen "
            "des Bebauungsplans Grüne Mitte. Die brauchen bis Ende der Woche eine "
            "Rückmeldung zu unserem Angebot."
        ),
    },
    {
        "label": "Kontakt + Projektstatus",
        "text": (
            "Herr Schneider von der Firma Landplan GmbH hat heute Morgen angerufen. "
            "Das Projekt Naturpark Feldweg ist jetzt in der Umsetzungsphase. "
            "Ich warte noch auf die Baugenehmigung von der Gemeinde."
        ),
    },
    {
        "label": "Einfache To-Do ohne Projekt",
        "text": "Pflanzenliste für Familie Wagner fertigstellen, bis Freitag.",
    },
]


def _make_dummy_wav(path: Path, duration_sec: float = 1.0) -> None:
    """Erstellt eine stille WAV-Datei als Dummy-Audio für Whisper-Tests."""
    sample_rate = 16000
    n_samples = int(sample_rate * duration_sec)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(struct.pack(f"<{n_samples}h", *([0] * n_samples)))


def _print_section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print("=" * 60)


def run_trockenlauf(
    model: str,
    provider: str,
    with_whisper: bool,
) -> dict[str, object]:
    """Führt den Trockenlauf durch und gibt ein Ergebnis-Dict zurück."""
    results: dict[str, object] = {
        "model": model,
        "provider": provider,
        "szenarien": [],
        "whisper": None,
        "fehler": [],
    }

    settings = Settings(
        llm_provider=LLMProvider(provider),
        llm_model=model,
        db_path=":memory:",
        markdown_dir="",
    )

    _print_section("Schritt 8 — Trockenlauf (lokale Simulation)")
    print(f"  Modell:   {provider}/{model}")
    print("  Kanal:    MemoryChannel (kein Signal)")
    print(f"  Whisper:  {'aktiviert' if with_whisper else 'deaktiviert (StubTranscriber)'}")

    # -- Whisper-Test ----------------------------------------------------------------
    if with_whisper:
        _print_section("Whisper-Test (Stille-WAV)")
        try:
            from faster_whisper import WhisperModel  # type: ignore[import-untyped]

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                wav_path = Path(f.name)
            _make_dummy_wav(wav_path)
            print(f"  WAV erstellt: {wav_path}")
            w_model = WhisperModel("tiny", device="auto", compute_type="auto")
            segs, _ = w_model.transcribe(str(wav_path), language="de")
            transcript = " ".join(s.text.strip() for s in segs).strip()
            print(f"  Transkript: '{transcript}' (leer = Stille erkannt ✓)")
            wav_path.unlink(missing_ok=True)
            results["whisper"] = {"status": "ok", "transcript": transcript}
        except Exception as exc:
            msg = f"Whisper-Fehler: {exc}"
            print(f"  ⚠ {msg}")
            results["fehler"].append(msg)  # type: ignore[union-attr]
            results["whisper"] = {"status": "fehler", "meldung": str(exc)}

    # -- Orchestrator-Szenarien ------------------------------------------------------
    with tempfile.TemporaryDirectory() as log_dir_str:
        log_dir = Path(log_dir_str)
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        repo = Repository(conn)

        for idx, szenario in enumerate(_SZENARIEN, start=1):
            _print_section(f"Szenario {idx}: {szenario['label']}")
            channel = MemoryChannel()
            stub = StubTranscriber(canned_text="")  # kein Audio in diesem Pfad
            orchestrator = Orchestrator(
                channel=channel,
                repo=repo,
                transcriber=stub,
                settings=settings,
                log_dir=log_dir,
            )

            sender = "+49123456789"
            text = szenario["text"]
            print(f"\n  Eingabe:\n  {text}\n")

            # Schritt 1: Text-Nachricht senden → Orchestrator verarbeitet
            channel.inbox.append(IncomingMessage(sender=sender, text=text))
            try:
                orchestrator.run_once()
            except Exception as exc:
                msg = f"Extraktion fehlgeschlagen: {exc}"
                print(f"  ⚠ {msg}")
                results["fehler"].append(msg)  # type: ignore[union-attr]
                results["szenarien"].append(  # type: ignore[union-attr]
                    {"label": szenario["label"], "status": "fehler", "meldung": str(exc)}
                )
                continue

            if not channel.sent:
                msg = "Kein Vorschlag erhalten (leere Extraktion oder Rückfrage)"
                print(f"  ⚠ {msg}")
                results["szenarien"].append(  # type: ignore[union-attr]
                    {"label": szenario["label"], "status": "kein_vorschlag"}
                )
                continue

            _, proposal_text = channel.sent[-1]
            print(f"  Vorschlag:\n{proposal_text}\n")

            # Schritt 2: Bestätigung senden
            channel.inbox.append(IncomingMessage(sender=sender, text="ja"))
            orchestrator.run_once()

            if len(channel.sent) >= 2:
                _, confirm_text = channel.sent[-1]
                print(f"  Bestätigung: {confirm_text}")
                status = "ok"
            else:
                confirm_text = "keine Bestätigungsantwort"
                status = "kein_confirm"

            results["szenarien"].append(  # type: ignore[union-attr]
                {
                    "label": szenario["label"],
                    "status": status,
                    "vorschlag": proposal_text,
                    "bestätigung": confirm_text,
                }
            )

        # DB-Inhalt nach allen Szenarien prüfen
        _print_section("DB-Inhalt nach Trockenlauf")
        tasks_in_db = repo.query_open_items()
        contacts_raw = conn.execute("SELECT id, name, type FROM contacts").fetchall()
        projects_raw = conn.execute("SELECT id, title, status FROM projects").fetchall()

        print(f"\n  Kontakte ({len(contacts_raw)}):")
        for cid, cname, ctype in contacts_raw:
            print(f"    [{cid}] {cname} ({ctype})")

        print(f"\n  Projekte ({len(projects_raw)}):")
        for pid, ptitle, pstatus in projects_raw:
            print(f"    [{pid}] {ptitle} ({pstatus})")

        print(f"\n  Offene Tasks ({len(tasks_in_db)}):")
        for t in tasks_in_db:
            print(f"    [{t.id}] {t.title}")

        results["db"] = {  # type: ignore[assignment]
            "kontakte": len(contacts_raw),
            "projekte": len(projects_raw),
            "tasks": len(tasks_in_db),
        }

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Kollege Trockenlauf (Schritt 8)")
    parser.add_argument("--model", default="qwen2.5:7b-instruct")
    parser.add_argument("--provider", default="ollama", choices=["ollama", "anthropic", "openai"])
    parser.add_argument("--whisper", action="store_true", help="Whisper-Test mit Dummy-WAV")
    args = parser.parse_args()

    results = run_trockenlauf(
        model=args.model,
        provider=args.provider,
        with_whisper=args.whisper,
    )

    _print_section("Zusammenfassung")
    fehler = results.get("fehler", [])
    szenarien = results.get("szenarien", [])
    ok_count = sum(1 for s in szenarien if isinstance(s, dict) and s.get("status") == "ok")  # type: ignore[union-attr]
    print(f"\n  Szenarien: {ok_count}/{len(szenarien)} erfolgreich")
    print(f"  Fehler:    {len(fehler)}")
    db = results.get("db", {})
    if isinstance(db, dict):
        n_k, n_p, n_t = db.get("kontakte", 0), db.get("projekte", 0), db.get("tasks", 0)
        print(f"  DB:        {n_k} Kontakte, {n_p} Projekte, {n_t} Tasks")
    if fehler:
        print("\n  Fehlerliste:")
        for f in fehler:  # type: ignore[union-attr]
            print(f"    - {f}")
    w = results.get("whisper")
    if w and isinstance(w, dict):
        print(f"\n  Whisper:   {w.get('status')} — {w.get('transcript', w.get('meldung', ''))}")
    if ok_count == len(szenarien) and not fehler:
        print("\n  ✅ Trockenlauf erfolgreich")
        sys.exit(0)
    else:
        print("\n  ⚠ Trockenlauf mit Einschränkungen abgeschlossen")
        sys.exit(1)


if __name__ == "__main__":
    main()
