"""Live-Betrieb: Kollege am echten Signal-Konto starten.

Verdrahtet den ``Orchestrator`` mit dem echten ``SignalChannel`` (via laufender
signal-cli-rest-api), der echten SQLite-DB und dem Whisper-Transcriber und
lauscht dann dauerhaft auf eingehende Signal-Nachrichten.

  Signal → Transcriber (Audio) → Agent (Ollama) → Vorschlag → Bestätigung → DB

Voraussetzungen:
    1. signal-cli-rest-api-Container läuft und ist verknüpft (docs/signal-setup.md).
    2. Ollama läuft lokal mit einem tool-fähigen Modell (Standard: qwen2.5:7b-instruct).
    3. .env enthält KOLLEGE_SIGNAL_API_URL und KOLLEGE_SIGNAL_NUMBER.

Aufruf:
    uv run python scripts/run_signal.py

Beenden mit Strg-C.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Sicherstellen, dass src/ im Python-Pfad liegt (bei direktem Aufruf).
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from kollege.agent import pre_warm_model
from kollege.channels.signal_channel import SignalChannel
from kollege.config import load_settings
from kollege.db import open_repository
from kollege.transcription.faster_whisper import FasterWhisperTranscriber


def _health_ok(base_url: str) -> bool:
    """Prüft /v1/health der signal-cli-rest-api (204 = gesund)."""
    import httpx

    try:
        resp = httpx.get(f"{base_url.rstrip('/')}/v1/health", timeout=5.0)
    except httpx.HTTPError:
        return False
    return resp.status_code == 204


def _account_linked(base_url: str, number: str) -> bool:
    """Prüft, ob die Nummer als verknüpftes Gerät registriert ist."""
    import httpx

    try:
        resp = httpx.get(f"{base_url.rstrip('/')}/v1/accounts", timeout=5.0)
        resp.raise_for_status()
    except httpx.HTTPError:
        return False
    return number in resp.json()


def main() -> None:
    # Logging früh konfigurieren, damit Orchestrator-Events (Eingang, Extraktion,
    # Persistenz, Fehler) im Log sichtbar sind. Datensparsam: keine Nachrichten-
    # inhalte, nur Metadaten (Absender, Typ, Anzahl). Zusätzlich zur Konsole immer
    # auch nach kollege.log schreiben (Schritt 8.21) — beim Vordergrund-Start ohne
    # Shell-Redirect (``uv run python scripts/run_signal.py`` ohne ``> log``) ging
    # der Verlauf bisher beim Schließen des Terminals verloren.
    log_format = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    date_format = "%H:%M:%S"
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        datefmt=date_format,
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("kollege.log", encoding="utf-8"),
        ],
    )

    settings = load_settings()

    print("=" * 60)
    print("  Kollege — Live-Betrieb (Signal)")
    print("=" * 60)
    print(f"  Signal-API:  {settings.signal_api_url}")
    print(f"  Nummer:      {settings.signal_number or '(nicht gesetzt!)'}")
    print(f"  LLM:         {settings.llm_provider}/{settings.llm_model}")
    print(f"  DB:          {settings.db_path}")
    print(f"  Logs:        {settings.markdown_dir}")
    print("=" * 60)

    # --- Vorab-Prüfungen mit klaren Fehlermeldungen ---------------------------
    if not settings.signal_number:
        print(
            "\n✗ KOLLEGE_SIGNAL_NUMBER ist nicht gesetzt.\n"
            "  Trage deine verknüpfte Signal-Nummer in .env ein (z. B. +49170...)."
        )
        sys.exit(1)

    if not _health_ok(settings.signal_api_url):
        print(
            f"\n✗ signal-cli-rest-api unter {settings.signal_api_url} nicht erreichbar.\n"
            "  Container starten:  docker compose up -d\n"
            "  Details:            docs/signal-setup.md"
        )
        sys.exit(1)

    if not _account_linked(settings.signal_api_url, settings.signal_number):
        print(
            f"\n✗ Nummer {settings.signal_number} ist nicht als Gerät verknüpft.\n"
            "  Verknüpfung durchführen (QR scannen):  docs/signal-setup.md\n"
            "  Status prüfen:  curl -s "
            f"{settings.signal_api_url.rstrip('/')}/v1/accounts"
        )
        sys.exit(1)

    # --- Komponenten verdrahten -----------------------------------------------
    # SQLite legt fehlende Elternverzeichnisse nicht selbst an.
    db_parent = Path(settings.db_path).parent
    if db_parent != Path():
        db_parent.mkdir(parents=True, exist_ok=True)
    repo = open_repository(settings.db_path)
    log_dir = Path(settings.markdown_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    channel = SignalChannel(
        base_url=settings.signal_api_url,
        account=settings.signal_number,
    )
    # Lazy: Das Whisper-Modell wird erst beim ersten Audio geladen (Download
    # bei Erstnutzung). Reine Textnachrichten brauchen es nie.
    transcriber = FasterWhisperTranscriber()

    # Import hier, damit die Vorab-Prüfungen ohne schwere Imports laufen.
    from kollege.orchestrator import Orchestrator
    from kollege.trace import build_trace_writer

    trace_writer = build_trace_writer(enabled=settings.trace_enabled, trace_dir=settings.trace_dir)
    if settings.trace_enabled:
        print(f"  Traces:      AN ({settings.trace_dir}) — Volltext, Datensparsamkeit beachten!")

    orchestrator = Orchestrator(
        channel=channel,
        repo=repo,
        transcriber=transcriber,
        settings=settings,
        log_dir=log_dir,
        trace=trace_writer,
    )

    # Ollama-Modell vorladen, damit die erste Sprachnotiz keine Cold-Start-Latenz
    # (mehrere Minuten bei RAM-Druck) erlebt. Schlägt fehl → Warnung, kein Absturz.
    pre_warm_model(settings)

    # Hinweis zur Nachrichten-Zuverlässigkeit (Schritt 8.9):
    # signal-cli puffert Nachrichten im Arbeitsspeicher, solange unsere WebSocket-
    # Verbindung unterbrochen ist. Bei Wiederherstellen der Verbindung werden sie
    # nachgeliefert. Startet signal-cli (Docker) neu, holt es fehlende Nachrichten
    # vom Signal-Server nach (Signal hält Nachrichten für verknüpfte Geräte ~30 Tage).
    # Einziges stilles Verlust-Risiko: Container UND Bot beide offline ohne je
    # reconnected zu haben — unrealistisch im täglichen Betrieb.
    # → Kein eigenes Ack-Protokoll nötig; launchd-Auto-Restart sichert den Bot ab.

    print("\n✓ Bereit. Lausche auf Signal-Nachrichten … (Strg-C zum Beenden)\n")
    try:
        orchestrator.run_forever()
    except KeyboardInterrupt:
        print("\nBeendet.")
    finally:
        channel.close()


if __name__ == "__main__":
    main()
