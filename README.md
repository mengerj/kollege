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

## Projektsteuerung

- **[ROADMAP.md](ROADMAP.md)** — Phasen, Schritte und der jeweils nächste Schritt.
- **[PROJECT_LOG.md](PROJECT_LOG.md)** — chronologisches Log abgeschlossener Arbeit.
- **[CLAUDE.md](CLAUDE.md)** — Arbeitsanweisungen für KI-gestützte Sessions.

## Status

Phase 0/1 im Aufbau. Siehe [ROADMAP.md](ROADMAP.md).
