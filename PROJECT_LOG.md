# Projekt-Log — Kollege

Chronologisches Log der Arbeit. Neuester Eintrag oben. Pro Session ergänzen
(siehe Ritual in [CLAUDE.md](CLAUDE.md)).

---

## 2026-06-29 — Persistenz-Layer (Schritt 2)

**Getan:**
- [`src/kollege/db/repository.py`](src/kollege/db/repository.py) mit `Repository`-Klasse
  (stdlib `sqlite3`, kein ORM): `upsert_contact`, `get_or_create_project`, `update_project`,
  `create_task`, `query_open_items`, `query_waiting_on`.
- [`src/kollege/db/__init__.py`](src/kollege/db/__init__.py): öffentliche API + `open_repository`-Factory.
- [`tests/test_db.py`](tests/test_db.py): 18 neue Tests (alle gegen `:memory:`-SQLite), decken
  Round-Trip, Dedup, Queries und Fehlerfälle ab.
- 33 Tests gesamt grün; ruff + mypy-strict sauber.

**Entscheidungen:**
- Dedup für `upsert_contact`: **exakter Namensabgleich** im MVP. Bestehende Felder werden
  *nicht* überschrieben, wenn der neue Extrakt `None` liefert (konservativ, verhindert Datenverlust).
  Fuzzy-Matching kommt in Schritt 13 (Onboarding-Mining).
- `depends_on` in `tasks`-Tabelle als JSON-String gespeichert (Pydantic parst zurück zu `list[int]`).
- `Task` bewusst ohne `updated_at` — Tasks sind append-only im MVP; Status wird direkt per SQL
  gesetzt (kein `update_task`-Method), bis Schritt 7 den Bestätigungs-Loop braucht.
- Schema idempotent via `CREATE TABLE IF NOT EXISTS`; Foreign Keys per `PRAGMA` aktiviert.

**Offene Punkte / für später:**
- `update_task`-Methode (für Status-Wechsel nach Bestätigung, Schritt 7).
- Eval-Strategie für nicht-deterministische LLM-Extraktion (Schritt 4).
- Pending-State & Reaktions-Handling für Bestätigungs-Loop (Schritt 7).

**Nächster Schritt:** Schritt 3 — Markdown-Verlaufslogs pro Projekt.

---

## 2026-06-29 — Projekt-Setup (Schritte 0 & 1)

**Getan:**
- Repository initialisiert, Remote `github.com/mengerj/kollege` verbunden.
- Scaffolding: uv-Projekt (`src`-Layout), `ruff` (Lint+Format), `mypy --strict`,
  `pytest` (+`pytest-cov`), `pre-commit`, GitHub-Actions-CI.
- Steuerungsdoku: [README.md](README.md), [ROADMAP.md](ROADMAP.md),
  [CLAUDE.md](CLAUDE.md), dieses Log; `.env.example`.
- **Schritt 1 (Datenmodell)** umgesetzt: [`models.py`](src/kollege/models.py) mit
  Enums, Extraktionsmodellen (`Extracted*`, `ExtractionResult`) und Domänen-
  Entitäten (`Contact`, `Project`, `Task`); [`config.py`](src/kollege/config.py)
  via pydantic-settings (lokal-first Defaults).
- Interfaces als Stubs: `Transcriber`/`StubTranscriber`, `Channel`/`MemoryChannel`.
- 15 Tests grün; ruff + mypy-strict sauber.

**Entscheidungen (in dieser Session geklärt):**
- Whisper-Backend: **Interface jetzt, echtes Backend später** (Schritt 5).
- LLM in Entwicklung: **Ollama lokal von Anfang an** (modell-agnostisch gebaut).
  Hinweis: lokal verfügbar ist `gemma4:e2b` (klein) — für Tool-Calls in Schritt 4
  ein tool-fähiges Modell ziehen (z. B. `qwen2.5:7b-instruct`).
- Signal: **Docker vorhanden**; Kern wird trotzdem zuerst hinter Channel-Interface
  gebaut, Signal angedockt in Schritt 6.
- CI/Qualität: ruff + mypy(strict) + pytest; pre-commit ergänzend.

**Offene Punkte / für später:**
- Dedup-Strategie für `upsert_contact` (Schritt 2).
- Eval-Strategie für nicht-deterministische LLM-Extraktion konkretisieren (Schritt 4).
- Pending-State & Reaktions-Handling für Bestätigungs-Loop (Schritt 7).

**Nächster Schritt:** Schritt 2 — Persistenz-Layer (SQLite-Repository).
