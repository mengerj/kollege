# CLAUDE.md — Arbeitsanweisungen für Kollege

Anweisungen für KI-gestützte Entwicklungssessions an diesem Projekt. Vor jeder
Session lesen. Bei Konflikt gewinnen die **Designprinzipien**.

## Was Kollege ist

Persönlicher KI-Projektassistent für eine selbstständige Landschaftsarchitektin.
Überführt Sprachnotizen (später E-Mail) **automatisch** in strukturierte Tasks,
Kontakte und Projektstände. Lern-/Experimentierprojekt, lokal-first, DSGVO-bewusst.
Vollständiger Kontext: [Planungsdokument](Planungsdokument_KI-Projektassistent.md).

## Designprinzipien (nicht verhandelbar — bei jeder Entscheidung prüfen)

1. **Passive Erfassung** — niemals manuelle Datenpflege verlangen. Frühere
   Excel/Kanban-Versuche scheiterten genau daran.
2. **Sprache zuerst** — niedrigste Hürde, Kern des Produkts.
3. **Human-in-the-loop** — nichts unkontrolliert anlegen: extrahieren → vorschlagen
   → bestätigen lassen (Emoji 👍 / nummerierte Auswahl). Bei Unklarheit **nachfragen**.
4. **Notizbuch bleibt** — ergänzen, nicht ersetzen.
5. **Lokal-first & Datensparsamkeit** — Audio lokal transkribieren; so wenig
   personenbezogene Daten wie möglich, Auszüge statt Volltext.
6. **Erfolg** = freiwillige Weiternutzung, nicht „technisch beeindruckend".

## Architektur (drei Verantwortlichkeiten)

- **Ohr & Wecker** — `channels/` (Signal-Listener), später Scheduler.
- **Gehirn** — `agent/` (Pydantic-AI-Agent + Tools).
- **Gedächtnis** — `db/` (SQLite, Quelle der Wahrheit) + `logs/` (Markdown-Verlauf).
- **Verdrahtung** — `orchestrator.py`. **Transkription** — `transcription/`.

Backends sind hinter **Interfaces** entkoppelt (`Transcriber`, `Channel`), damit
Komponenten einzeln und ohne externe Dienste testbar bleiben.

## Tech-Stack & Konventionen

- **uv** für alles. Niemals `pip` direkt; Dependencies via `uv add` / `uv add --dev`.
- **Python ≥ 3.12**, `src`-Layout, vollständige Typannotationen.
- **Pydantic v2** doppelt nutzen: LLM-Output-Schema *und* DB-Schema-Grundlage.
- **LLM modell-agnostisch** über [`config.py`](src/kollege/config.py). Default
  lokal-first **Ollama** (tool-fähiges Modell, z. B. `qwen2.5:7b-instruct` —
  das installierte `gemma4:e2b` ist für Tool-Calls evtl. zu klein).
- **Secrets** nur via `.env` / Umgebungsvariablen (Präfix `KOLLEGE_`), nie im Repo.
- Deutsche Domänenbegriffe in Modellen/Enums beibehalten (`anfrage`, `waiting_on` …).

## Arbeitsweise

- **Test-driven, wo sinnvoll:** deterministische Logik (DB, Logs, Tools, Parsing)
  erst als Test, dann Implementierung. LLM-Aufrufe **nicht** im CI gegen echte
  Modelle — Pydantic-AI `TestModel`/`FunctionModel` nutzen; zusätzlich ein kleines
  Eval-Set mit Fixtures (Smoke/Schwellen statt strikter Gleichheit).
- **Ein Roadmap-Schritt pro Session.** Scope eng halten (Risiko: Scope Creep).
- Vor Commit muss **alles grün** sein:

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
```

- `uv run pre-commit install` einmalig; Hooks laufen dann automatisch.

## Git-Workflow (obligatorisch)

Jede Session arbeitet auf einem **Feature-Branch**, nie direkt auf `main`:

1. Zu Beginn: `git checkout -b feat/<kurzname>` (z. B. `feat/schritt-3-markdown-logs`).
2. Am Ende: Branch pushen und einen **Pull Request gegen `main`** öffnen:
   ```bash
   git push -u origin feat/<kurzname>
   gh pr create --base main --title "..." --body "..."
   ```
3. Merge erst wenn CI grün und PR reviewed (auch im Solo-Projekt als Doku-Artefakt).

## Ritual am Ende JEDER Session (wichtig)

1. **[PROJECT_LOG.md](PROJECT_LOG.md)** ergänzen: Datum, was getan, Entscheidungen,
   offene Punkte (neuester Eintrag oben).
2. **[ROADMAP.md](ROADMAP.md)** aktualisieren: Status-Tabelle + Abschnitt
   **„▶ NÄCHSTER SCHRITT"** auf den nächsten konkreten Schritt setzen.
3. Sicherstellen, dass die CI-Kette grün ist.
4. Commit auf Feature-Branch, PR öffnen (siehe Git-Workflow oben).

## Grenzen & bewusste Auslassungen

- **WhatsApp**: zurückgestellt (Meta-Policy seit 15.01.2026 + dedizierte Nummer nötig).
- Kein autonomes Planen durch den Agenten — Wert ist **rechtzeitiges Erinnern**.
- Kein großes externes PM-Tool im MVP.
- **Echte Kunden-/Gemeindedaten** erst nach erfolgreichem Trockenlauf mit Fake-Daten.
