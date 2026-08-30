# apps/agent_client — der Agent

Der Pydantic-AI-Agent: nimmt Sprachnotizen über Signal entgegen, transkribiert
lokal mit Whisper, extrahiert Aufgaben/Kontakte/Projektstände und lässt sie
bestätigen. Bis vor dem Monorepo-Umbau **war** dieser Code das ganze Projekt.

**Datenhaltung: aktuell noch SQLite** (`data/kollege.db`) plus Markdown-Logs.
Die Umstellung auf Postgres (siehe [`apps/db`](../db/README.md)) ist ein
späterer, eigener Schritt — bis dahin läuft der Agent unverändert weiter.

> Der letzte Stand vor dem Umbau, mit allem im Repo-Wurzelverzeichnis, liegt auf
> dem Branch **`version0`**. Wenn du die Testphase mit der Nutzerin startest,
> bevor hier Postgres angebunden ist: `git checkout version0`.

## Aufbau

| Pfad | Rolle |
| --- | --- |
| `src/kollege/channels/` | **Ohr** — Signal-Listener |
| `src/kollege/transcription/` | lokale Transkription (faster-whisper) |
| `src/kollege/agent/` | **Gehirn** — Pydantic-AI-Agent samt Tools |
| `src/kollege/db/`, `src/kollege/logs/` | **Gedächtnis** — SQLite + Markdown-Verlauf |
| `src/kollege/orchestrator.py` | Verdrahtung der drei Teile |
| `src/kollege/eval/`, `benchmarks/` | Eval-Set und Modellvergleiche |

Backends stecken hinter Interfaces (`Transcriber`, `Channel`), damit jeder Teil
ohne externe Dienste testbar bleibt.

## Kommandos

Alle Kommandos laufen aus dem **Repo-Wurzelverzeichnis** — dort liegen `.env`,
`data/` und der uv-Workspace.

```bash
uv sync                                            # Abhängigkeiten + venv
uv run pytest                                      # Tests
uv run mypy                                        # Typprüfung (strict)
uv run ruff check . && uv run ruff format --check . # Lint + Format
```

## Live-Betrieb (Signal)

Drei Prozesse müssen laufen — `docker compose` startet nur den ersten:

```bash
ollama serve
```

```bash
docker compose -f apps/agent_client/docker-compose.yml up -d
```

```bash
uv run python apps/agent_client/scripts/run_signal.py
```

Erst nach dem dritten Schritt werden eingehende Nachrichten beantwortet;
der Prozess läuft im Vordergrund, Beenden mit `Strg-C`.

Erstmalige Einrichtung (Nummer verknüpfen, `.env` befüllen):
[docs/signal-setup.md](docs/signal-setup.md). Monitoring und Live-Test:
[docs/live-testing-guide.md](docs/live-testing-guide.md). Modellvergleiche:
[docs/benchmark.md](docs/benchmark.md).

### Schnelldiagnose, wenn nichts antwortet

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8080/v1/health
```

```bash
pgrep -fl run_signal.py
```

`204` bei der Bridge und ein Treffer bei `pgrep` heißt: beide Voraussetzungen
stehen. Kein `pgrep`-Treffer ist die häufigste Ursache für ausbleibende
Antworten — dann läuft der Bot-Prozess schlicht nicht.

### Dauerbetrieb (macOS)

```bash
cp apps/agent_client/deploy/de.mengerj.kollege.plist ~/Library/LaunchAgents/
```

Details und Deinstallation im Kommentarkopf der
[plist](deploy/de.mengerj.kollege.plist). Ollama und der Docker-Container
müssen auch hier separat laufen.
