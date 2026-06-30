# Projekt-Log — Kollege

Chronologisches Log der Arbeit. Neuester Eintrag oben. Pro Session ergänzen
(siehe Ritual in [CLAUDE.md](CLAUDE.md)).

---

## 2026-06-30 — Signal-Live-Inbetriebnahme (Schritt 6/7 gehärtet)

Erste **echte** Verknüpfung mit Signal und End-to-End-Test mit dem Live-Bot
(zuvor nur Trockenlauf mit `MemoryChannel`). Dabei mehrere Live-only-Bugs
gefunden und behoben. Vollständige Einweisung für die nächste Test-Session:
[docs/live-testing-guide.md](docs/live-testing-guide.md).

**Getan:**
- **Signal verknüpft** — Container gestartet, als Linked Device am eigenen Konto
  angemeldet (QR via `/v1/qrcodelink` als PNG, kein `qrencode` nötig).
- **[`scripts/run_signal.py`](scripts/run_signal.py)** — Live-Launcher: verdrahtet
  echten `SignalChannel` + DB + Whisper + Orchestrator, mit Vorab-Checks (Health,
  Verknüpfung, Config) und klaren Fehlermeldungen.
- **[`scripts/signal_debug_receive.py`](scripts/signal_debug_receive.py)** —
  Diagnose-Tool: schneidet rohe WebSocket-Envelopes mit (war zentral fürs Debuggen).
- **End-to-End verifiziert:** Notiz an mich → Vorschlag → „ja" → Task in
  `data/kollege.db`.

**Live-only-Bugfixes:**
- **Note-to-Self statt fremder Nachrichten:** `_parse_envelope` verarbeitet jetzt
  ausschließlich `syncMessage.sentMessage` an die eigene Nummer; eingehende
  `dataMessage` anderer Personen werden bewusst ignoriert (Datensparsamkeit).
- **Persistente WebSocket-Verbindung:** Batch-Connect/Disconnect verlor im
  json-rpc-Modus Nachrichten in den Verbindungslücken (Bot lief, reagierte nie).
  Verbindung wird jetzt offen gehalten und pro Poll geleert; Reconnect bei Fehler.
- **SQLite-Thread-Safety:** Pydantic-AI führt Tools nebenläufig in Worker-Threads
  auf einer geteilten Connection aus → `InterfaceError`/Crash. Reentranter Lock
  (`@_synchronized`) serialisiert alle Repository-Operationen. Regressionstest mit
  8 Threads × 25 Ops.
- **Aktuelles Datum injiziert:** dynamischer `@agent.system_prompt` gibt heutiges
  Datum + Wochentag; „07.07" → korrekt `2026-07-07` (vorher Raten ~Okt 2023).
- **Doku [docs/signal-setup.md](docs/signal-setup.md):** Health = `204` korrigiert,
  QR-als-PNG, Abschnitte „Bot starten" und „Mit Kollege reden (Note-to-Self)".

**Erkanntes (noch offen, im Live-Guide §6 als Backlog):**
- 👍-**Reaktion** (Tapback) ≠ Textnachricht → wird noch nicht als Bestätigung
  erkannt (entspricht aber dem Design „Emoji 👍").
- `run_forever()` ohne Error-Handling → stürzt bei unbehandelter Exception ab.
- Geringe Beobachtbarkeit (Orchestrator loggt Empfang/Verarbeitung nicht).
- qwen2.5:7b **über-extrahiert** (mehrere überlappende Tasks, Duplikate, `due`
  inkonsistent) — Human-in-the-loop fängt es ab.

**Entscheidung:** Phase 1 erst im Alltag stabilisieren (Live-Tests + Härtung laut
Guide), **dann** Schritt 9 (IMAP). CI grün, 114 Tests.

---

## 2026-06-30 — End-to-End-Trockenlauf (Schritt 8)

**Getan:**
- **ffmpeg** via Homebrew installiert (OGG/Opus → WAV-Konvertierung für Whisper).
- **faster-whisper** via `uv sync --group transcription` installiert.
- **`qwen2.5:7b-instruct`** via `ollama pull` heruntergeladen (4,7 GB; ersetzt `gemma4:e2b`
  als Tool-Call-fähiges Modell).
- [`scripts/trockenlauf.py`](scripts/trockenlauf.py): lokale E2E-Simulation ohne echtes Signal.
  Verwendet `MemoryChannel` + `StubTranscriber`/echter Whisper + Ollama + SQLite.
  Drei Fake-Szenarien: Neuer Kontakt+Task, Kontakt+Projektstatus, einfaches To-Do.
- **Bugfix — Fallback-Pfad in `run_extraction`**: `qwen2.5:7b` ruft Domain-Tools
  korrekt auf, aber nicht das pydantic-ai-interne `final_result`-Tool für strukturierten
  Output. Neuer Fallback-Pfad: Agent mit `output_type=str` → Tools speichern in DB →
  `_rebuild_from_repo()` rekonstruiert `ExtractionResult` aus DB-Zustand.
  Frische Verbindung im Fallback verhindert Doppelschreibungen und Commit-Fehler.
- [`src/kollege/db/repository.py`](src/kollege/db/repository.py): `get_all_contacts()`
  und `get_all_projects()` als öffentliche Methoden ergänzt.
- [`src/kollege/agent/__init__.py`](src/kollege/agent/__init__.py): `_rebuild_from_repo()`
  und überarbeitete `run_extraction()` mit Primär-/Fallback-Logik.
- CI-Kette grün; alle 108 Tests bestehen.

**Trockenlauf-Ergebnis (3/3 Szenarien ✅):**

| Szenario | Extraktion | Bestätigung | DB-Effekt |
|---|---|---|---|
| Frau Müller / Bebauungsplan Grüne Mitte | ✅ Kontakt + Task erkannt | ✅ gespeichert | 1 Kontakt, 1 Task |
| Herr Schneider / Naturpark Feldweg | ✅ Kontakt + Task + Projektstatus | ✅ gespeichert | 1 Kontakt, 1 Task, 1 Projekt |
| Pflanzenliste Familie Wagner | ✅ Task erkannt | ✅ gespeichert | 1 Task |

Whisper-Test: Stille-WAV → leeres Transkript (korrekt erkannt). ffmpeg-Integration
für OGG/Opus-Konvertierung bereit.

**Entscheidungen:**
- **Fallback-Architektur**: Statt pydantic-ais Tool-Output-Modus (der `final_result`-Tool
  erfordert, das qwen2.5:7b ignoriert) kein Modellwechsel — stattdessen Fallback, der
  DB-Zustand nach Tool-Ausführung rekonstruiert. Tests bleiben unverändert, weil
  TestModel/FunctionModel den Primär-Pfad nutzen.
- **Frische Verbindung im Fallback**: verhindert Doppelschreibungen (Primär-Lauf
  schreibt schon via Tools → Fallback-Lauf schreibt erneut) und SQLite-Commit-Fehler.
- **Datum-Extraktion unkritisch**: qwen2.5:7b liefert teils falsche Jahreszahlen
  (z.B. 2023 statt 2026). Für Schritt 8 akzeptabel — Datum kann beim Bestätigungsdialog
  korrigiert werden.

**Offene Punkte / für später:**
- Echter Signal-Trockenlauf (manuell): `docker compose up -d` + Signal-Linking +
  echte Sprachnotiz. Erfordert laufenden Docker-Daemon.
- Datum-Kalibrierung des Prompts (CLAUDE.md nennt qwen2.5:7b als empfohlenes Modell;
  Prompt mit heutigem Datum könnte helfen).
- OGG/Opus-Testfixture mit echter Sprachaufnahme (bisher nur Stille-WAV).
- Bestätigungs-Timeout (alte PendingProposals aufräumen) — kein MVP-Blocker.

---

## 2026-06-30 — Orchestrator + Bestätigungs-Loop (Schritt 7)

**Getan:**
- [`src/kollege/orchestrator.py`](src/kollege/orchestrator.py): `Orchestrator`-Klasse
  vollständig implementiert. Verdrahtet Channel → Transcriber → Agent → Repository/Logs →
  Bestätigungsfrage. Öffentliche API: `handle_message()`, `run_once()`, `run_forever()`.
- `PendingProposal`-Dataclass (sender, transcript, result, created_at): Zwischenspeicher
  im Arbeitsspeicher bis zur Nutzerbestätigung.
- `format_proposal()`: Einzeleintrag → "ja/nein"-UX; mehrere Einträge → nummerierte
  Auswahl ("1 3") + "ja"/"nein". Emoji-Bestätigung 👍 wird erkannt.
- `persist_result()`: überträgt `ExtractionResult` (selektiv oder komplett) in das echte
  Repository. Kontakte zuerst (damit Tasks contact_id auflösen können), dann Projekt-Updates
  inkl. `open_project_log()`, dann Tasks.
- `_extract()`: Agent läuft intern gegen ein temporäres In-Memory-Repo — kein echter
  DB-Schreibzugriff während der Extraktion. Erst auf Bestätigung schreibt `persist_result`
  in das echte Repo.
- `Repository.update_task_status()`: in [`src/kollege/db/repository.py`](src/kollege/db/repository.py)
  ergänzt (für zukünftigen Task-Status-Wechsel z.B. → erledigt).
- [`tests/test_orchestrator.py`](tests/test_orchestrator.py): 25 neue Tests;
  `run_extraction` via `unittest.mock.patch` gemockt — CI-sicher, kein LLM.
  Abgedeckt: Vorschlag, alle Bestätigungsvarianten (ja/👍/JA/Zahlenauswahl),
  Ablehnung, Audio-Transkription, leere Extraktion, Rückfrage, Pending-Ersatz,
  Sender-Isolation, `run_once` mit mehreren Nachrichten, `update_task_status`.
- CI-Kette (ruff/mypy-strict/pytest) grün; 108 Tests, 1 slow deselected.

**Entscheidungen:**
- **Dry-Run-Extraktion via temporärem In-Memory-Repo:** Agent kann seine Tools normal
  ausführen (kein Mock), schreibt aber nur in ein Wegwerf-Repo. Auf Bestätigung
  werden die Extraktionsdaten aus `ExtractionResult` direkt via Repository-Methoden
  in das echte Repo geschrieben — kein zweiter LLM-Aufruf, keine Tool-Replay.
- **Pending-State per Absender (dict):** eine offene Bestätigung pro Nutzer.
  Neue Nachricht ohne ja/nein ersetzt den alten Vorschlag (natürliches Verhalten).
- **Sync statt async:** `run_forever()` nutzt `time.sleep()` im Polling-Loop.
  Signal-Channel hat bereits synchrone WebSocket-Unterstützung; async-Refactor
  ist Schritt 8 / Trockenlauf vorbehalten, wenn echter Daemonbetrieb nötig wird.
- **`_NUMS`-Regex:** nur Ziffern, Leerzeichen und Komma — "Neue Notiz" fällt durch
  und wird als neue Nachricht behandelt (kein versehentlicher Bestätigungs-Trigger).

**Offene Punkte / für später:**
- Signal-Emoji-Reaktionen (als `reactionMessage`-Envelope): aktuell werden nur
  Textnachrichten mit "👍" erkannt. Echte Signal-Reaktionen erfordern
  `IncomingMessage.reaction`-Feld und erweiterten `_parse_envelope` (Schritt 8).
- ffmpeg für OGG/Opus → WAV-Konvertierung vor Whisper (Schritt 8).
- `run_forever` in Produktionsbetrieb (Schritt 16): systemd-Service oder APScheduler.
- Bestätigungs-Timeout (alte PendingProposals aufräumen) — für jetzt kein MVP-Blocker.

---

## 2026-06-29 — Signal-Kanal-Adapter (Schritt 6)

**Getan:**
- [`src/kollege/channels/signal_channel.py`](src/kollege/channels/signal_channel.py):
  `SignalChannel` implementiert das `Channel`-Protocol vollständig.
  Empfang via WebSocket (`/v1/receive/{account}`), Senden via HTTP POST (`/v2/send`),
  Anhänge (OGG/Opus) werden lokal gespeichert (`_download_attachment` mit Cache).
  Lazy-Imports für `websockets` und `httpx` mit klaren Fehlermeldungen.
- [`src/kollege/channels/__init__.py`](src/kollege/channels/__init__.py):
  `Channel`-Protocol mit `@runtime_checkable` annotiert (Konsistenz mit `Transcriber`).
- [`pyproject.toml`](pyproject.toml): optionale Dependency-Gruppe `signal`
  (`httpx>=0.27`, `websockets>=13.0`); mypy-Override für `httpx` und `websockets.*`.
- [`docker-compose.yml`](docker-compose.yml): `bbernhard/signal-cli-rest-api` im
  `json-rpc`-Modus (WebSocket-Streaming), Port 8080, Config-Volume.
- [`docs/signal-setup.md`](docs/signal-setup.md): Schritt-für-Schritt-Linking-Anleitung
  (QR-Code, Smartphone-Scan, Testbefehl), Sicherheitshinweise.
- [`.gitignore`](.gitignore): `signal-cli-config/` (private Schlüssel) eingetragen.
- [`tests/test_signal_channel.py`](tests/test_signal_channel.py): 14 neue Tests;
  Protocol-Konformität, Text/Audio-Empfang, Mehrfachnachrichten, Anhang-Cache,
  URL-Konstruktion, Import-Fehler — alle gegen Mocks, kein echter Container.
- CI-Kette (ruff/mypy-strict/pytest) grün; 83 Tests, 1 slow deselected.

**Entscheidungen:**
- Batch-Modus für `receive()`: verbindet, liest bis `TimeoutError` (Standard: 0.5 s),
  trennt dann. Für Dauerprozess kommt der async-Orchestrator in Schritt 7.
- Lazy-Import-Pattern: identisch mit `FasterWhisperTranscriber` — kein `ImportError`
  beim Import des Moduls, nur beim ersten Aufruf; `uv sync --group signal` als Hinweis.
- WebSocket-URL aus HTTP-URL ableiten (str-Replace); so bleibt nur `signal_api_url`
  in der Config (kein separates `signal_ws_url`).
- Attachment-Dateiname `att-{id}.ogg` / `att-{id}.bin` — eindeutig, cachefreundlich.

**Offene Punkte / für später:**
- Echter Integrations-Test gegen lokalen Container (manuell: `docker compose up -d`,
  dann `uv run pytest -m integration`, noch nicht implementiert).
- ffmpeg für OGG/Opus → WAV-Konvertierung vor Whisper (Schritt 8 / Trockenlauf).
- Reaktionsempfang (Signal-Emoji-Reaktionen) für den Bestätigungs-Loop (Schritt 7).
- `receive_timeout` könnte über Settings konfigurierbar sein — für Schritt 7 entscheiden.

---

## 2026-06-29 — Transkriptions-Backend faster-whisper (Schritt 5)

**Getan:**
- [`src/kollege/transcription/faster_whisper.py`](src/kollege/transcription/faster_whisper.py):
  `FasterWhisperTranscriber` implementiert das `Transcriber`-Protocol vollständig.
  Lazy-Loading des Modells (erster `transcribe()`-Aufruf), `language="de"`, `beam_size=5`.
- [`pyproject.toml`](pyproject.toml): optionale Dependency-Gruppe `transcription`
  (`faster-whisper>=1.0`); mypy-Override `ignore_missing_imports = true` für
  das optionale Paket; pytest-Marker `slow` registriert.
- [`tests/test_transcription.py`](tests/test_transcription.py): 5 neue Tests:
  Protocol-Konformität, `FileNotFoundError`, ImportError-Meldung (mock), Modell-Aufruf
  (mock), Segmente zusammenfügen (mock). Slow-Integration-Test mit `@pytest.mark.slow`
  (echter Whisper-Lauf auf Stille-WAV, `tiny`-Modell).
- CI-Kette (ruff/mypy-strict/pytest) grün; 69 Tests bestehen, 1 slow deselected.

**Entscheidungen:**
- Lazy Import in `_load_model()`: verhindert `ImportError` beim Importieren des Moduls
  wenn `faster-whisper` nicht installiert ist; Fehlermeldung enthält `uv sync --group`.
- `_model: Any` — für optionale Drittbibliothek ohne Stubs akzeptabel.
- Modell-Attribut intern (kein Property) — direkte Mock-Injektion in Tests ohne Patch.
- `language="de"` fest: Projekt ist nur in Deutsch, spart Auto-Detection-Overhead.
- OGG/Opus-Unterstützung erfordert ffmpeg; auf dem Entwicklungsrechner noch nicht
  installiert — WAV-Format für Tests reicht; Produktionseinsatz braucht ffmpeg.

**Offene Punkte / für später:**
- ffmpeg installieren wenn Signal-OGG-Nachrichten verarbeitet werden (Schritt 6/8).
- Echter Smoke-Test mit `tiny`-Modell und deutschsprachiger Audio-Fixture.

---

## 2026-06-29 — Pydantic-AI-Agent + Tools (Schritt 4)

**Getan:**
- [`src/kollege/agent/__init__.py`](src/kollege/agent/__init__.py): Modul `kollege/agent/` vollständig
  implementiert.
- Modul-Level-Agent `Agent[Repository, ExtractionResult]` mit `defer_model_check=True`
  (Modell erst beim `run()`-Aufruf, ermöglicht Tests ohne LLM).
- Vier Tools: `upsert_contact`, `create_task`, `update_project_status`, `query_open_items`.
  Ungültige Enum-Werte werden mit `contextlib.suppress` toleriert (kein Crash).
- `build_model(settings)` — erzeugt OllamaModel, AnthropicModel oder OpenAIChatModel
  aus Config (lokal-first Default: Ollama).
- `run_extraction(transcript, repo, settings)` — synchroner Produktions-Einstiegspunkt.
- [`src/kollege/db/__init__.py`](src/kollege/db/__init__.py): `open_repository` mit
  `check_same_thread=False` — pydantic-ai führt sync Tools in ThreadPoolExecutor aus.
- [`tests/test_agent.py`](tests/test_agent.py): 13 neue Tests (gesamt 64), alle grün.
  ruff + mypy-strict + pytest grün.

**Entscheidungen:**
- `defer_model_check=True` am Agent: kein Modell-Zwang bei Konstruktion; Modell wird
  per `run(model=...)` übergeben — ermöglicht TestModel/FunctionModel im CI ohne LLM.
- Tool-Output-Mode: pydantic-ai nutzt intern `final_result`-Tool für strukturierten Output
  (kein Text-Modus). FunctionModel in Tests muss entsprechend antworten.
- `check_same_thread=False` an SQLite-Connection: pydantic-ai's ThreadPoolExecutor führt
  sync Tools in Worker-Threads aus — ohne dieses Flag crasht die DB.
- Enum-Toleranz in Tools: ungültige Werte (LLM-Fehler) werden mit `contextlib.suppress`
  ignoriert statt zu crashen; kein Retry-Loop im MVP.
- ModelMessage/ModelResponse aus `pydantic_ai.messages` importieren (nicht aus `models`).

**Offene Punkte / für später:**
- Echter Smoke-Test mit Ollama `qwen2.5:7b-instruct` lokal (braucht laufenden Ollama-Server).
- `run_extraction` ist synchron; für Orchestrator (Schritt 7) async-Variante bauen.
- Eval-Set erweitern wenn echter LLM getestet wird (Schritt 8).

**Nächster Schritt:** Schritt 5 — Transkriptions-Backend (faster-whisper).

---

## 2026-06-29 — Markdown-Verlaufslogs (Schritt 3)

**Getan:**
- [`src/kollege/logs/__init__.py`](src/kollege/logs/__init__.py): Modul `kollege/logs/`
  mit `ProjectLog`-Klasse und `open_project_log`-Factory.
- `ProjectLog.append_entry(text, source=None)` — UTC-Zeitstempel-Überschrift, append-only
  via `open("a")`.
- `ProjectLog.read_recent(n=5)` — letzte *n* Einträge für künftigen Agenten-Kontext.
- `open_project_log(project, log_dir)` — erstellt Verzeichnis + Datei (idempotent),
  setzt `project.markdown_log_path`.
- [`tests/test_logs.py`](tests/test_logs.py): 18 neue Tests gegen `tmp_path`, alle grün.
- 51 Tests gesamt; ruff + mypy-strict + pytest grün.

**Entscheidungen:**
- Dateiname: `<slug>-<id>.md` wenn ID vorhanden, sonst `<slug>.md`.
  Slug: Kleinbuchstaben, Sonderzeichen (`&`, `.`, …) entfernt, Leerzeichen → `-`.
- Header wird nur beim ersten Anlegen geschrieben (idempotent-Check via `path.exists()`).
- `markdown_log_path` wird am Projekt-Objekt in-place gesetzt; Aufrufer persistiert via
  `Repository.update_project` — saubere Trennung Logs ↔ DB.
- `read_recent` splittet auf `## YYYY-` Regex; erster Abschnitt = Header, Rest = Einträge.

**Offene Punkte / für später:**
- Integration `open_project_log` in Orchestrator (Schritt 7): automatisch aufrufen,
  wenn ein Projekt erstmals angelegt wird.
- Aufbewahrungsfrist / Archivierung langer Logs (Phase 3 / DSGVO, Schritt 17).

**Nächster Schritt:** Schritt 4 — Pydantic-AI-Agent + Tools (Ollama).

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
