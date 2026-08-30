# Kollege

Ein persönlicher KI-Projektassistent für eine selbstständige
Landschaftsarchitektin. Er überführt Sprachnotizen **automatisch** in
strukturierte Aufgaben, Kontakte und Projektstände — ohne manuelle Datenpflege —
und wächst gerade zu einem CRM- und Projektmanagement-System mit eigener
Datenbank, API und Weboberfläche.

> Lern- und Experimentierprojekt: **lokal-first, passive Erfassung,
> Human-in-the-loop.** Produktkontext im
> [Planungsdokument](docs/Planungsdokument_KI-Projektassistent.md), Arbeitsweise
> in [CLAUDE.md](CLAUDE.md).

## Wo das Projekt steht

Der Agent funktioniert und speichert in SQLite — dieser Stand ist als Branch
**`version0`** eingefroren und lauffähig. Auf `main` entsteht daraus ein
Monorepo mit Postgres als gemeinsamer Datenbank für mehrere Clients.

Das ist kein Umbau um des Umbaus willen: der aktuelle Schwerpunkt liegt darauf,
Postgres und Fullstack-TypeScript wirklich zu lernen, nicht darauf, schnell
Funktionen zu liefern.

## Aufbau

```
apps/
  agent_client/   Pydantic-AI-Agent, Signal, lokale Transkription  → läuft (SQLite)
  db/             Postgres: Compose-Setup und SQL-Migrationen      → aktueller Fokus
  server/         API zwischen Datenbank und Clients (TypeScript)  → leer
  frontend/       CRM-/PM-Oberfläche (TypeScript)                  → leer
libs/             geteilte Typdefinitionen                         → leer
docs/             Produktkontext; docs/archiv/ = Roadmap und Log der ersten Phase
```

Jede App hat eine eigene README mit Stand, Kommandos und offenen Fragen:
[agent_client](apps/agent_client/README.md) ·
[db](apps/db/README.md) ·
[server](apps/server/README.md) ·
[frontend](apps/frontend/README.md) ·
[libs](libs/README.md)

## Loslegen

Voraussetzungen: [`uv`](https://docs.astral.sh/uv/), Python ≥ 3.12, Docker.
Für den Agenten zusätzlich [Ollama](https://ollama.com/) mit einem
tool-fähigen Modell (`ollama pull qwen2.5:7b-instruct`).

Alle Kommandos laufen aus dem Wurzelverzeichnis — dort liegen `.env`, `data/`
und der uv-Workspace.

```bash
uv sync
```

```bash
cp .env.example .env
```

Prüfkette für den Python-Code:

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
```

Datenbank starten:

```bash
docker compose -f apps/db/docker-compose.yml up -d
```

Den Agenten live betreiben (Signal, Ollama, Bot-Prozess): siehe
[apps/agent_client/README.md](apps/agent_client/README.md).

## Datenschutz

Echte Kunden- und Gemeindedaten kommen erst nach einem sauberen Trockenlauf mit
erfundenen Daten ins Spiel. `.env`, `data/`, `signal-cli-config/` und
`docs/privat/` sind aus gutem Grund nicht eingecheckt.
