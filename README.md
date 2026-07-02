# Kollege

Ein persönlicher KI-Projektassistent für eine selbstständige Landschaftsarchitektin.
Er überführt Informationen aus bestehenden Kanälen (Sprachnotizen, später E-Mail)
**automatisch** in strukturierte Aufgaben, Kontakte und Projektstände — ohne
manuelle Datenpflege.

> Lern- und Experimentierprojekt im datenschutzregulierten deutschen Raum.
> **Lokal-first, passive Erfassung, Human-in-the-loop.** Details:
> [Planungsdokument](Planungsdokument_KI-Projektassistent.md).

## Designprinzipien (nicht verhandelbar)

1. **Passive Erfassung** statt manueller Eingabe.
2. **Sprache als primäre Eingabe** (Sprachnotiz „runterquatschen").
3. **Bestätigungs-Loop** (Human-in-the-loop): extrahieren → vorschlagen → bestätigen lassen.
4. **Das Notizbuch bleibt** — ergänzen, nicht ersetzen.
5. **Lokal-first & Datensparsamkeit** — Audio wird lokal transkribiert.
6. **Erfolg** = sie nutzt es freiwillig weiter.

## Architektur

Drei getrennte Verantwortlichkeiten: **Ohr & Wecker** (Listener/Scheduler),
**Gehirn** (Pydantic-AI-Agent), **Gedächtnis** (SQLite + Markdown-Logs).

```
Signal ──▶ Orchestrator ──▶ Whisper (lokal) ──▶ Pydantic-AI-Agent
                                                   │
                              SQLite ◀── Tools ────┤
                              Markdown-Logs ◀──────┘
Agent ──▶ Bestätigungsfrage ──▶ Signal
```

## Entwicklung

Voraussetzungen: [`uv`](https://docs.astral.sh/uv/), Python ≥ 3.12.
Lokal-first: [Ollama](https://ollama.com/) mit einem tool-fähigen Modell
(z. B. `ollama pull qwen2.5:7b-instruct`). Signal/E-Mail folgen phasenweise.

```bash
uv sync                      # Dependencies + venv
cp .env.example .env         # Konfiguration (Secrets NICHT committen)

uv run pytest                # Tests
uv run mypy                  # Typprüfung (strict)
uv run ruff check .          # Lint
uv run ruff format .         # Format
```

## Bot starten (Live-Betrieb Signal)

Der Bot besteht aus **drei getrennten Prozessen**, die alle laufen müssen.
`docker compose up` startet nur den **ersten** — die Signal-Bridge, also das „Ohr".
Das „Gehirn" (der eigentliche Bot) ist ein **separater Python-Prozess** und muss
zusätzlich gestartet werden. Reihenfolge:

```bash
# 1. Ollama (LLM) — muss laufen (Ollama.app oder):
ollama serve

# 2. Signal-Bridge (signal-cli-rest-api) im Docker-Container:
docker compose up -d

# 3. Der Bot selbst — lauscht auf Nachrichten, transkribiert, antwortet:
uv run python scripts/run_signal.py
```

Erst nach Schritt 3 werden eingehende Signal-Nachrichten beantwortet. Der Prozess
läuft im Vordergrund und protokolliert live; Beenden mit `Strg-C`.
`run_signal.py` prüft beim Start selbst, ob Bridge (Schritt 2) und
Nummernverknüpfung vorhanden sind, und meldet fehlende Voraussetzungen mit
Klartext-Hinweisen.

**Erstmalige Einrichtung** (Signal-Nummer verknüpfen, `.env` befüllen):
siehe [docs/signal-setup.md](docs/signal-setup.md).

### Dauerbetrieb (macOS, automatischer Neustart)

Statt den Bot manuell im Terminal laufen zu lassen, kann er als launchd-Dienst
im Hintergrund laufen (Auto-Restart bei Absturz, Start beim Login):

```bash
cp deploy/de.mengerj.kollege.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/de.mengerj.kollege.plist

launchctl list | grep kollege        # Status
tail -f kollege.log                  # Live-Log
```

Details und Deinstallation: Kommentarkopf in
[deploy/de.mengerj.kollege.plist](deploy/de.mengerj.kollege.plist).
Ollama und der Docker-Container müssen auch hier separat laufen.

### Antwortet nichts? — Schnelldiagnose

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8080/v1/health  # 204 = Bridge ok
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:11434/api/tags  # 200 = Ollama ok
pgrep -fl run_signal.py                                                   # läuft der Bot?
```

Liefert `pgrep` nichts, läuft der Bot-Prozess (Schritt 3) nicht — das ist die
häufigste Ursache dafür, dass Nachrichten unbeantwortet bleiben. Mehr zu
Monitoring und Live-Test: [docs/live-testing-guide.md](docs/live-testing-guide.md).

## Projektsteuerung

- **[ROADMAP.md](ROADMAP.md)** — Phasen, Schritte und der jeweils nächste Schritt.
- **[PROJECT_LOG.md](PROJECT_LOG.md)** — chronologisches Log abgeschlossener Arbeit.
- **[CLAUDE.md](CLAUDE.md)** — Arbeitsanweisungen für KI-gestützte Sessions.

## Status

Phase 0/1 im Aufbau. Siehe [ROADMAP.md](ROADMAP.md).
