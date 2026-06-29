# Roadmap — Kollege

Arbeitsdokument zur kontinuierlichen Entwicklung. Jeder Schritt ist so
geschnitten, dass er in **einer Session** abgearbeitet werden kann, mit klarer
*Definition of Done* (DoD). Nach jedem Schritt: [PROJECT_LOG.md](PROJECT_LOG.md)
ergänzen und unten **NÄCHSTER SCHRITT** aktualisieren.

> Vorgehen pro Schritt: wo sinnvoll **test-driven** (erst Test, dann Code),
> alles muss `ruff`/`mypy`/`pytest` grün lassen. Details: [CLAUDE.md](CLAUDE.md).

---

## ▶ NÄCHSTER SCHRITT

**Schritt 4 — Pydantic-AI-Agent + Tools (Ollama).**
Modul `kollege/agent/`: Agent mit `output_type=ExtractionResult`, Tools
(`upsert_contact`, `create_task`, `update_project_status`, `query_open_items`)
auf dem Repository. Provider modell-agnostisch via `config.py`.
TDD mit `TestModel`/`FunctionModel` (kein echter LLM im CI).

---

## Statusübersicht

| # | Schritt | Phase | Status |
|---|---|---|---|
| 0 | Projekt-Scaffolding (uv, CI, Tooling, Doku) | 0 | ✅ erledigt |
| 1 | Datenmodell (Pydantic) | 0 | ✅ erledigt |
| 2 | Persistenz-Layer (SQLite-Repository) | 1 | ✅ erledigt |
| 3 | Markdown-Verlaufslogs pro Projekt | 1 | ✅ erledigt |
| 4 | Pydantic-AI-Agent + Tools (Ollama) | 1 | ⏳ als Nächstes |
| 5 | Transkriptions-Backend wählen & implementieren | 1 | ⬜ offen |
| 6 | Signal-Kanal-Adapter (signal-cli-rest-api) | 1 | ⬜ offen |
| 7 | Orchestrator + Bestätigungs-Loop | 1 | ⬜ offen |
| 8 | End-to-End-Trockenlauf (Fake-Projekte) | 1 | ⬜ offen |
| 9 | IMAP read-only (t-online) | 2 | ⬜ offen |
| 10 | Task-Extraktion aus E-Mail + CommunicationLog | 2 | ⬜ offen |
| 11 | Scheduler (APScheduler) + Tagesbriefing | 2 | ⬜ offen |
| 12 | Statusabfragen per Chat | 2 | ⬜ offen |
| 13 | Onboarding-Mining bestehender Projekte | 2 | ⬜ offen |
| 14 | Kalender-Integration | 3 | ⬜ offen |
| 15 | Notizbuch-OCR | 3 | ⬜ offen |
| 16 | VPS-Migration & Betrieb (Hetzner) | 3 | ⬜ offen |
| 17 | DSGVO/AI-Act-Härtung | 3 | ⬜ offen |

---

## Phase 0 — Fundament

### Schritt 0 — Scaffolding ✅
uv-Projekt (`src`-Layout), `ruff` (Lint+Format), `mypy --strict`, `pytest`,
`pre-commit`, GitHub-Actions-CI, `.env.example`, Steuerungsdoku. Interfaces für
Transkription (`Transcriber` + `StubTranscriber`) und Kanal (`Channel` +
`MemoryChannel`) stehen als Platzhalter.
**DoD:** ✅ CI-Kette lokal grün, initialer Commit gepusht.

### Schritt 1 — Datenmodell ✅
Pydantic-Modelle in [`models.py`](src/kollege/models.py): Enums, Extraktions-
modelle (`Extracted*`, `ExtractionResult` als künftiges Agent-`output_type`) und
Domänen-Entitäten (`Contact`, `Project`, `Task`).
**DoD:** ✅ Modelle + Tests, mypy-strict-sauber.

---

## Phase 1 — Sprachnotiz-Kern (MVP)

*Ziel der Phase: Sie spricht eine Notiz ein und bekommt strukturierte,
bestätigte Aufgaben/Kontakte zurück. Läuft komplett lokal auf dem Air.*

### Schritt 2 — Persistenz-Layer (SQLite) ✅
Modul `kollege/db/`: Schema-Erzeugung aus den Modellen + Repository.
- Funktionen: `upsert_contact`, `create_task`, `update_project`,
  `query_open_items`, `query_waiting_on`.
- `stdlib sqlite3` reicht (kein ORM-Zwang); Pydantic-Modelle als
  Serialisierungsschicht.
- **Designfrage (im Schritt entscheiden):** Dedup-Logik für `upsert_contact`
  (Name-Matching) — exaktes Matching im MVP, Fuzzy später. Doppelte Kontakte
  sind ein Vertrauenskiller.
- **TDD:** Repository gegen In-Memory-SQLite (`:memory:`) vollständig testbar.
**DoD:** Repository mit Tests, Round-Trip Modell↔DB, mypy/ruff/pytest grün.

### Schritt 3 — Markdown-Verlaufslogs ✅
Modul `kollege/logs/`: pro Projekt eine Markdown-Datei (Verlauf/Notizen),
append-only, menschenlesbar, später als Agenten-Kontext nutzbar.
- Pfad in `Project.markdown_log_path` ablegen.
- **TDD:** gegen `tmp_path`.
**DoD:** ✅ Anlegen/Anhängen getestet, Pfadverwaltung robust. 18 Tests grün.

### Schritt 4 — Pydantic-AI-Agent + Tools ⬜
Modul `kollege/agent/`: Agent mit `output_type=ExtractionResult`, Tools
(`upsert_contact`, `create_task`, `update_project_status`, `query_open_items`)
auf dem Repository. Provider modell-agnostisch via [`config.py`](src/kollege/config.py).
- **Lokal-first-Hinweis:** `gemma4:e2b` ist klein; für Tool-/Structured-Output
  ein tool-fähiges Modell ziehen (z. B. `ollama pull qwen2.5:7b-instruct`).
  Falls lokale Structured-Output-Qualität nicht reicht → Prompt-Output-Mode
  oder vorübergehend Cloud-Provider zum Vergleich.
- Agent **fragt bei Unklarheiten nach** (`clarification`) statt zu raten.
- **TDD/Eval:** deterministische Logik mit Pydantic-AI `TestModel`/`FunctionModel`
  (kein echter LLM im CI). Zusätzlich kleines **Eval-Set** aus Beispiel-Transkripten
  → erwartete Felder (kein striktes Assert wegen Nichtdeterminismus, sondern
  Schwellen/Smoke).
**DoD:** Agent extrahiert auf Fixtures plausibel; Tool-Aufrufe schreiben in DB;
CI ohne Netz/LLM grün.

### Schritt 5 — Transkriptions-Backend ⬜
Echtes Backend hinter dem bestehenden `Transcriber`-Protocol wählen und bauen
(Default-Empfehlung: `faster-whisper`, rein Python; Alternative `whisper.cpp`
mit Metal). Modell `medium` für Eigen-/Ortsnamen.
- Optionale Dependency-Gruppe in `pyproject.toml`, nicht im Core-Install.
- **Test:** mit kurzer Fixture-Audiodatei (markiert als `slow`/optional, nicht im
  Standard-CI-Lauf).
**DoD:** OGG/Opus-Sprachnachricht → Text, hinter dem Protocol austauschbar.

### Schritt 6 — Signal-Kanal-Adapter ⬜
`signal-cli-rest-api` (Docker) als Linked Device anbinden; `Channel`-Protocol
implementieren (Empfang via WebSocket/JSON-RPC, Senden via POST, Medien beidseitig).
- `docker-compose.yml` für den Container; Linking-Anleitung dokumentieren.
- **Test:** Adapter-Logik gegen gemockte HTTP/WS-Antworten; echter Container nur
  manuell/integration.
**DoD:** Text + Sprachnachricht empfangen und Antwort senden gegen lokalen Container.

### Schritt 7 — Orchestrator + Bestätigungs-Loop ⬜
`kollege/orchestrator.py`: verdrahtet Channel → (Audio→Transcriber) → Agent →
Repository/Logs → Bestätigungsfrage zurück.
- **Bestätigungs-UX:** Emoji-Reaktion (👍) als Standard, **nummerierte Auswahl**
  bei mehreren Optionen. Erfordert Pending-State (Vorschlag ↔ `message_id`) und
  Verarbeitung eingehender **Reaktionen** — als eigenes Teilstück planen.
- Async-Architektur (Listener-Dauerprozess) festlegen.
**DoD:** Vorschlag → Nutzerbestätigung → erst dann Persistenz; abgelehnt → verworfen.

### Schritt 8 — End-to-End-Trockenlauf ⬜
Komplettkette mit **Jos eigenem Signal-Konto und Fake-Projekten**, lokalem LLM.
Keine echten Kunden-/Gemeindedaten.
**DoD:** „Funktioniert Signal → Whisper → Extraktion → DB → Bestätigung sauber?"
dokumentiert beantwortet; Beobachtungen im Log.

---

## Phase 2 — E-Mail & Übersicht

*Ziel: Der Assistent beantwortet „bei wem muss ich mich melden?".*

### Schritt 9 — IMAP read-only (t-online) ⬜
`secureimap.t-online.de:993` SSL, strikt lesend. E-Mail-Passwort aus Config/Secrets.
**DoD:** Mails lesen ohne jede Schreiboperation (kein Flag/Move).

### Schritt 10 — Task-Extraktion aus E-Mail + CommunicationLog ⬜
Agent auf E-Mail-Text anwenden; `CommunicationLog`-Modell (Auszug statt Volltext,
**Datensparsamkeit**, Aufbewahrungsfrist als TODO).
**DoD:** Mail → Vorschläge mit Bestätigungs-Loop; Drittpersonen-Daten minimiert.

### Schritt 11 — Scheduler + Tagesbriefing ⬜
`APScheduler`: IMAP-Poll alle X Minuten; Tagesbriefing (z. B. 7 Uhr): „wer
wartet auf Antwort, was ist fällig". Nutzt `query_waiting_on` + Fälligkeiten.
**DoD:** Briefing wird zur Zeit X via Signal gesendet.

### Schritt 12 — Statusabfragen per Chat ⬜
Frage-Tools (z. B. „Was ist offen bei Familie Müller?") über das Repository.
**DoD:** Freitextfrage → korrekte Antwort aus der DB.

### Schritt 13 — Onboarding-Mining ⬜
Postfach nach bestehenden Projekten durchsuchen; **strukturierte Rückfragen zu
DB-Lücken** stellen. Ergänzend per Sprachnachricht.
**DoD:** geführter Onboarding-Dialog füllt Kontakte/Projekte.

---

## Phase 3 — Erweiterung & Betrieb

### Schritt 14 — Kalender-Integration ⬜
Erst wenn Tasks/Status stabil sind. Fälligkeiten/Fenster → Kalender.

### Schritt 15 — Notizbuch-OCR ⬜
Abfotografierte Seite per OCR aufnehmen — Ergänzung, kein Ersatz.

### Schritt 16 — VPS-Migration & Betrieb ⬜
Hetzner (DE), `systemd`-Timer statt APScheduler, „immer erreichbar".
Backups (SQLite + Markdown), Monitoring/Logfire.

### Schritt 17 — DSGVO/AI-Act-Härtung ⬜
AVV (Anbieter + Nutzerin), Löschfristen umsetzen, KI-Transparenzhinweis,
Gemeinde-Daten besonders behandeln, Secrets-Review. Siehe Checkliste unten.

---

## Querschnitt: DSGVO / EU-AI-Act (laufend mitführen)

- [ ] Audio **lokal** transkribieren (kein Audio in die Cloud).
- [ ] Datensparsamkeit: Auszüge statt Volltext; Lösch-/Aufbewahrungsfristen.
- [ ] Secrets nie im Klartext im Repo (E-Mail-Passwort, Signal-Link, API-Keys).
- [ ] Bei Cloud-LLM: AVV + möglichst EU/DE-Verarbeitung; sonst Ollama lokal.
- [ ] KI-Transparenz: Assistent gibt sich als KI zu erkennen (sobald Dritte interagieren).
- [ ] Gemeinde-Daten (öffentliche Stellen) besonders sensibel.
- [ ] Transportverschlüsselung überall (IMAP SSL, HTTPS).

## Bewusst zurückgestellt

- **WhatsApp** — Meta verbietet seit 15.01.2026 universelle KI-Chatbots; Business-API
  bräuchte dedizierte Nummer. Signal ersetzt WhatsApp als Assistenz-Kanal.
