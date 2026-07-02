# Roadmap — Kollege

Arbeitsdokument zur kontinuierlichen Entwicklung. Jeder Schritt ist so
geschnitten, dass er in **einer Session** abgearbeitet werden kann, mit klarer
*Definition of Done* (DoD). Nach jedem Schritt: [PROJECT_LOG.md](PROJECT_LOG.md)
ergänzen und unten **NÄCHSTER SCHRITT** aktualisieren.

> Vorgehen pro Schritt: wo sinnvoll **test-driven** (erst Test, dann Code),
> alles muss `ruff`/`mypy`/`pytest` grün lassen. Details: [CLAUDE.md](CLAUDE.md).

---

## ▶ NÄCHSTER SCHRITT

**Schritt 8.14 — Vollständige Historie pro Pending-Proposal.**

Aus einem Live-Test (mistral3.1-medium via OpenRouter) kam ein Bündel an
Erkenntnissen; daraus ein priorisierter Block **8.14 → 8.15 → 8.16 → 8.17**,
der vor der E-Mail-Integration (Schritt 9) abgearbeitet wird. Details je Schritt
weiter unten; Herleitung siehe [PROJECT_LOG.md](PROJECT_LOG.md) (Eintrag 2026-07-02).

Jetzt konkret **Schritt 8.14**: Korrektur- und Rückfrage-Läufe scheitern an
Referenzen wie *„…die Telefonnummer wie in der letzten Nachricht"*, weil
[`run_revision`](src/kollege/agent/__init__.py) und
[`run_clarification_response`](src/kollege/agent/__init__.py) **kein Gedächtnis
über die Turns einer Interaktion** haben — sie sehen nur (Ursprungstranskript +
aktueller Vorschlag + ein Korrekturtext). `PendingProposal`/`PendingClarification`
bekommen eine `history` (alle Turns *einer* Interaktion), die den Läufen
mitgegeben wird. Details unten in Schritt 8.14.

> **Reihenfolge-Regel bestätigt (Nutzerin):** neue Nachricht = neue Notiz;
> Korrektur/Antwort **nur** über die Zitat-Antwort-Funktion. Slash-Commands auf
> Deutsch. Bei 8.17 Erkennung+Abgleich in **einem** Extraktionslauf (Variante A).
>
> **Schritt 8.12 (EU-LLM-Anbieter)** bleibt offen, ist aber hinter den 8.14–8.17-
> Block zurückgestellt: der Schreib-/Abfragepfad soll erst stabil sein. Für Tests
> reicht vorerst OpenRouter.
>
> **IMAP/E-Mail (Schritt 9 ff.) zurückgestellt**, bis Phase 1.5 rund läuft.
> Schritt 8.5 (restliche Live-Edge-Cases) läuft parallel weiter.

---

## Statusübersicht

| # | Schritt | Phase | Status |
|---|---|---|---|
| 0 | Projekt-Scaffolding (uv, CI, Tooling, Doku) | 0 | ✅ erledigt |
| 1 | Datenmodell (Pydantic) | 0 | ✅ erledigt |
| 2 | Persistenz-Layer (SQLite-Repository) | 1 | ✅ erledigt |
| 3 | Markdown-Verlaufslogs pro Projekt | 1 | ✅ erledigt |
| 4 | Pydantic-AI-Agent + Tools (Ollama) | 1 | ✅ erledigt |
| 5 | Transkriptions-Backend wählen & implementieren | 1 | ✅ erledigt |
| 6 | Signal-Kanal-Adapter (signal-cli-rest-api) | 1 | ✅ erledigt |
| 7 | Orchestrator + Bestätigungs-Loop | 1 | ✅ erledigt |
| 8 | End-to-End-Trockenlauf (Fake-Projekte) | 1 | ✅ erledigt |
| 8.5 | Signal-Live-Betrieb + Härtung | 1.5 | ⏳ läuft (Live-Tests/Edge-Cases) |
| 8.6 | Korrektur-/Revisions-Schleife (natürlichsprachig) | 1.5 | ✅ erledigt |
| 8.7 | Bekannte Namen abgleichen (LLM-seitig) | 1.5 | ✅ erledigt |
| 8.8 | Sofort-Quittung / gefühlte Reaktionszeit | 1.5 | ✅ erledigt |
| 8.9 | Robuster Dauerbetrieb (Dienst, Warm-Start, Verlust-Schutz) | 1.5 | ✅ erledigt |
| 8.10 | Eval-Set für Extraktionsqualität | 1.5 | ✅ erledigt |
| 8.11 | Modell-Benchmark-System (Extraktion + Revision) | 1.5 | ✅ erledigt |
| 8.12 | DSGVO-konforme EU-LLM-Anbieter evaluieren & anbinden | 1.5 | ⬜ offen (hinter 8.14–8.17 zurückgestellt) |
| 8.13 | Rückfrage-Antwort-Schleife + robuste 👍/👎-Erkennung | 1.5 | ✅ erledigt |
| 8.14 | Vollständige Historie pro Pending-Proposal | 1.5 | ▶ nächster Schritt |
| 8.15 | Query-Funktionen + deutsche Slash-Commands | 1.5 | ⬜ offen |
| 8.16 | Projekt-Markdown-Logs füllen (append_entry verdrahten) | 1.5 | ⬜ offen |
| 8.17 | Erledigungen aus Freitext erkennen & abgleichen | 1.5 | ⬜ offen |
| 9 | IMAP read-only (t-online) | 2 | 🅿️ zurückgestellt bis Phase 1.5 (Branch liegt) |
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

### Schritt 4 — Pydantic-AI-Agent + Tools ✅
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

### Schritt 5 — Transkriptions-Backend ✅
Echtes Backend hinter dem bestehenden `Transcriber`-Protocol wählen und bauen
(Default-Empfehlung: `faster-whisper`, rein Python; Alternative `whisper.cpp`
mit Metal). Modell `medium` für Eigen-/Ortsnamen.
- Optionale Dependency-Gruppe in `pyproject.toml`, nicht im Core-Install.
- **Test:** mit kurzer Fixture-Audiodatei (markiert als `slow`/optional, nicht im
  Standard-CI-Lauf).
**DoD:** OGG/Opus-Sprachnachricht → Text, hinter dem Protocol austauschbar.

### Schritt 6 — Signal-Kanal-Adapter ✅
`signal-cli-rest-api` (Docker) als Linked Device anbinden; `Channel`-Protocol
implementiert (Empfang via WebSocket, Senden via POST, Audio-Download).
- `docker-compose.yml` + `docs/signal-setup.md` (Linking-Anleitung).
- Lazy-Imports `httpx` + `websockets` in optionaler Dep-Gruppe `signal`.
- **Test:** 14 Tests gegen Mocks; echter Container nur manuell.
**DoD:** ✅ Text + Sprachnachricht empfangen und Antwort senden (gegen Mocks); 83 Tests grün.

### Schritt 7 — Orchestrator + Bestätigungs-Loop ✅
`kollege/orchestrator.py`: verdrahtet Channel → (Audio→Transcriber) → Agent →
Repository/Logs → Bestätigungsfrage zurück.
- **Bestätigungs-UX:** Emoji-Reaktion (👍) als Standard, **nummerierte Auswahl**
  bei mehreren Optionen. Erfordert Pending-State (Vorschlag ↔ `message_id`) und
  Verarbeitung eingehender **Reaktionen** — als eigenes Teilstück planen.
- Async-Architektur (Listener-Dauerprozess) festlegen.
**DoD:** Vorschlag → Nutzerbestätigung → erst dann Persistenz; abgelehnt → verworfen.

### Schritt 8 — End-to-End-Trockenlauf ✅
Lokale Simulation (MemoryChannel) + echter Ollama (qwen2.5:7b-instruct) + Whisper (tiny).
3/3 Szenarien erfolgreich. Fallback-Pfad für Modelle ohne final_result-Tool implementiert.
Echter Signal-Trockenlauf (mit Docker + Smartphone) steht noch aus, ist aber kein Blocker.
**DoD:** ✅ Extraktion → DB → Bestätigung sauber dokumentiert beantwortet (siehe PROJECT_LOG.md).

---

## Phase 1.5 — Verflüssigung des Sprachnotiz-Kerns *(vor Phase 2)*

*Ziel der Phase: Der bestehende Kern (Sprachnotiz → Vorschlag → Bestätigung → DB)
soll sich im Alltag **flüssig, schnell genug und vertrauenswürdig** anfühlen.
Maßstab ist nicht „mehr Features", sondern **freiwillige Weiternutzung**
(Designprinzip 6). Erst danach kommt E-Mail (Phase 2).*

### Schritt 8.5 — Signal-Live-Betrieb + Härtung ⏳
Echter Bot verknüpft, §6-Backlog umgesetzt und live verifiziert (👍-Reaktion,
Absturz-Resistenz, Logging, Audio-E2E, Dedup, „(kein Datum)"). Verbleibend: restliche
Edge-Cases (Guide §4) live gegenprüfen.
**DoD:** Edge-Case-Tabelle (Guide §4) reproduzierbar grün im Alltag.

### Schritt 8.6 — Korrektur-/Revisions-Schleife (natürlichsprachig) ✅

**Motiv.** Transkription (auch mit größeren Whisper-Modellen) und das LLM machen
gelegentlich Fehler — typisch ein **falsch verstandener Name** („Herr Schnitt"
statt „Schmidt") oder ein verrutschtes Datum. Statt den Vorschlag zu verwerfen und
neu einzusprechen, soll die Nutzerin **in natürlicher Sprache korrigieren**:
*„Das ist nicht Herr Schnitt, sondern Schmidt"* → das System aktualisiert den/die
Einträge. Stark im Sinne der Designprinzipien (passive Erfassung, Human-in-the-loop,
keine manuelle DB-Pflege).

**Leitmechanismus — Signal-Quote-Reply (zentral, vom Nutzer gewünscht).** Wenn die
Nutzerin **auf den Vorschlag antwortet** (Signal „Antworten"/Zitat), trägt das
Envelope ein `quote` mit `targetSentTimestamp`. Das löst das sonst schwierige
**Intent-Problem elegant**: eine Zitat-Antwort *auf meinen Vorschlag* ist
eindeutig eine **Korrektur** zu genau diesem Vorschlag — kein LLM-Klassifikator
nötig. Eine *frische* Nachricht (ohne Zitat) bleibt wie heute eine **neue Notiz**.

**Stufe A — Korrektur des offenen Vorschlags (MVP, höchster Wert):**
1. Nutzerin zitiert den Vorschlag und schreibt/spricht die Korrektur
   („das ist nicht Herr Schnitt, sondern Schmidt"; „Datum ist Freitag").
2. Orchestrator erkennt am `quote` → Revisions-Lauf statt neue Extraktion: das LLM
   bekommt (Ursprungstranskript + aktuelles `ExtractionResult` + Korrekturtext) und
   erzeugt ein revidiertes `ExtractionResult`, das **erneut als Vorschlag** gezeigt
   wird. Nichts ist bis zur Bestätigung persistiert — risikoarm, iterierbar.

**Technische Voraussetzungen (im Schritt klären):**
- **Vorschlag-Timestamp merken:** `channel.send()` muss den Sende-Timestamp des
  Vorschlags zurückgeben (signal-cli `/v2/send` liefert ihn), damit
  `PendingProposal` ihn speichert und `targetSentTimestamp` darauf gematcht werden
  kann. (Minimal-Variante ohne Match: jede Zitat-Antwort bei offenem Vorschlag =
  Korrektur — reicht, weil pro Absender nur ein Vorschlag offen ist.)
- **Quote-Envelope mitschneiden** (`signal_debug_receive.py`), um Feldnamen
  (`quote.id`/`quote.author`/`quote.text`) sicher zu kennen, bevor geparst wird.
- **Korrektur per Sprachnachricht:** Zitat-Antwort kann auch Audio sein → erst
  transkribieren, dann als Korrekturtext verwenden (gleicher Pfad).

**Stufe B — Korrektur bereits gespeicherter Einträge (später):** analog, aber die
Zitat-Antwort zielt auf eine zuvor gesendete Bestätigung/ein Item. Erfordert eine
Referenz auf persistierte Items (`LastPersistedBatch`), neue Repo-Methoden
(`rename_contact`/`update_contact`, gezieltes `update_task`) **inkl. Markdown-Log-
Konsistenz** und Merge-Semantik bei Kontakt-Umbenennung (`upsert_contact` dedupt per
Name → „Schnitt"→„Schmidt" könnte zwei Einträge zusammenführen). Scope bewusst hinter A.

**DoD (Stufe A):** ✅ Eine Zitat-Antwort auf den Vorschlag revidiert den Vorschlag
sichtbar; Bestätigung speichert die korrigierte Fassung; frische Nachricht bleibt
neue Notiz. Quote-Parsing + Revisions-Branch test-driven; 148 Tests grün.

### Schritt 8.7 — Bekannte Namen abgleichen (LLM-seitig statt Whisper-Prompt) ✅

**Motiv.** Whisper verhört **Eigennamen** am häufigsten („Herr Schnitt" statt
„Schmidt"). Naheliegend wäre, die DB-Namen Whisper als `initial_prompt`-Vokabular
mitzugeben — **verworfen**, weil dieser Hebel zu schwach ist: `initial_prompt` ist
auf ~224 Tokens begrenzt, biast nur probabilistisch (Whisper kann trotzdem verhören)
und hilft per Definition **nicht beim ersten Auftreten** eines neuen Namens (der noch
nicht in der DB steht — genau dann zählt die richtige Schreibweise am meisten).

**Besserer Ort: das LLM, nicht das Audio.** Der Agent bekommt das *Transkript* und
hat ein **großes Kontextfenster** (Tausende Tokens — kein 224-Limit). Gibt man ihm
die **bekannten Kontakt-/Projektnamen als Kontext**, kann er „Herr Schnitt" gegen die
Liste abgleichen und „Schmidt" vorschlagen — die Bestätigung (Human-in-the-loop)
fängt Fehlentscheidungen ohnehin ab. Das überlappt sauber mit der Korrektur-Schleife
(8.6) und der Quote-Reply-Revision.

**Ansatz.**
- Vor der Extraktion bekannte Namen aus dem Repo laden und dem Agenten als Kontext
  geben (System-Prompt-Anhang oder ein Tool `lookup_known_names()`); der Agent
  normalisiert/verknüpft gegen bestehende Einträge statt blind neu anzulegen.
- Mehrdeutigkeit → `clarification` bzw. Vorschlag mit erkennbarer Zuordnung, nie
  stilles Überschreiben.
- **DSGVO:** lokal (Ollama), Namen verlassen das Gerät nicht.

**Grenzen / Risiken (im Schritt entscheiden).** Auch der LLM-Kontext skaliert nicht
unbegrenzt — bei großer DB die Kandidaten **vorfiltern** (kürzlich aktiv / grobe
Ähnlichkeit per einfachem Fuzzy-Match), statt die ganze Liste zu schicken. Gefahr des
**Über-Korrigierens** (echter neuer „Schnitt" wird fälschlich zu „Schmidt") → im
Zweifel nachfragen, Eval-Set (8.10) als Wächter.

**DoD:** ✅ Bekannte Kontakt- und Projektnamen werden vor jeder Extraktion als
Kontext-Block dem Transkript vorangestellt; `filter_known_names` priorisiert
kürzlich aktive Einträge (max 80); unbekannte Namen bleiben unverändert.
Abgleich-/Vorfilter-Logik test-driven; LLM-Teil via `TestModel`/`FunctionModel`.
164 Tests grün.

### Schritt 8.8 — Sofort-Quittung / gefühlte Reaktionszeit ⬜
Cold-Start + Whisper + LLM erzeugen spürbare Latenz; ohne Rückmeldung wirkt das wie
„nichts passiert" (live so erlebt). Eine **knappe Sofort-Bestätigung** beim Eingang
(z. B. „🎤 hab ich, ich verarbeite das kurz …") nimmt die Unsicherheit, bevor der
eigentliche Vorschlag kommt. Optional: Hinweis bei ungewöhnlich langem Lauf.
**DoD:** Jede eingehende Notiz wird binnen ~1 s quittiert; der Vorschlag folgt wie
gehabt. Kein Doppel-Senden mehr aus Ungeduld.

### Schritt 8.9 — Robuster Dauerbetrieb ✅
Der Bot läuft **unbeaufsichtigt** und übersteht Störungen:
- **launchd-Service** [`deploy/de.mengerj.kollege.plist`](deploy/de.mengerj.kollege.plist):
  `KeepAlive = true`, `ThrottleInterval = 60 s`, gemeinsame Log-Datei.
- **Pre-Warm**: `pre_warm_model()` lädt das Ollama-Modell beim Dienststart;
  Cold-Start-Latenz trifft nicht mehr die erste Sprachnotiz.
- **Retry in `_extract()`**: 3 Versuche mit 10 s Abstand bei transientem Ausfall
  (Ollama/Container temporär weg); erst dann Fehlermeldung an Absender.
- **Nachrichten-Verlust**: kein stilles Verlustrisiko im Normalbetrieb —
  signal-cli puffert, Signal-Server queued ~30 Tage (analysiert, dokumentiert).
**DoD:** ✅ 173 Tests grün; Pre-Warm, Retry-Logik und launchd-Plist implementiert.

### Schritt 8.10 — Eval-Set für Extraktionsqualität ✅
5 Fixture-Transkripte in [`tests/fixtures/eval/`](tests/fixtures/eval/) mit
erwartetem Output. [`tests/test_eval.py`](tests/test_eval.py) mit `@pytest.mark.eval`:
- CI: `FunctionModel`-Mocks → Schema + Mindest-Counts.
- Manuell: `pytest -m eval --real-llm -s` → Trefferquote pro Fixture (Schwellenwert 50 %).
**DoD:** ✅ `uv run pytest -m eval --real-llm -s` zeigt Trefferquote; 175 Tests grün.

### Schritt 8.11 — Modell-Benchmark-System (Extraktion + Revision) ✅

**Motiv (aus dem Live-Debugging 2026-07-01).** Eine triviale Rechtschreibkorrektur
(„Es heißt Aibling, nicht Eibling") auf einen offenen Vorschlag lief live ins Leere
(„Nach der Korrektur konnte ich nichts Konkretes erkennen"). Die reproduzierte
Ursachenanalyse ergab drei Dinge:
1. Das Modell **versteht** die Korrektur inhaltlich einwandfrei (roher Fließtext ist
   in allen Varianten korrekt, mit und ohne Bekannte-Namen-Kontext).
2. Der **Primär-Pfad** (strukturierter `final_result`-Output) scheitert bei `ornith:9b`
   praktisch **immer** (`UnexpectedModelBehavior: Exceeded maximum output retries`).
   Alles hängt am Fallback-Pfad (freies Tool-Calling), der **nicht-deterministisch**
   ist: mal korrekt, mal Über-Extraktion, mal **leer** → „nichts erkannt".
3. Ein A/B-Test gegen `qwen2.5:7b-instruct` zeigte **dieselbe** Flakiness inkl. des
   Leer-Fehlerfalls. „Struktur einhalten" ist eine **Protokoll-Fähigkeit** (sauber
   geformte Tool-Calls), getrennt vom Sprachverständnis — genau hier sind kleine
   lokale Modelle schwach.

**Konsequenz:** Die Wahl zwischen lokalen und API-Modellen darf **nicht** aus dem
Bauch getroffen werden. Es braucht eine **messbare, wiederholbare Grundlage**. Das
Eval-Set (8.10) reicht dafür nicht: es testet nur die Erstextraktion, in **einem**
Lauf (Flakiness bleibt unsichtbar), nur mit `min_*`-Schwellen (Über-Extraktion wird
sogar belohnt), ohne Revisions-Pfad und ohne Modellvergleich.

**Ziel.** Ein **wachstumsfähiges, gut dokumentiertes** Benchmark-System, das mehrere
Modelle (lokal *und* API) reproduzierbar auf **Extraktions- und Korrektur-Qualität**
vergleicht — mit Fokus auf die vier real beobachteten Fehlerklassen: **Flakiness,
Über-Extraktion, „nichts erkannt", nicht angewandte Korrektur**.

**Architektur — vier Bausteine.**

1. **Eval-Paket `src/kollege/eval/`** (Single Source of Truth, ohne LLM testbar):
   - `fixtures.py` — Laden + **Schema-Validierung** der JSON-Fixtures (beide Familien),
     Kategorien/Tags.
   - `scoring.py` — **deklarativer** Scorer: aus dem `expected`-Block → `FixtureScore`
     (hits/total + Flags `empty`, `over_extraction`, `forbidden_hit`). Neue Prüfung =
     ein optionaler Key + ein Zweig.
   - `runner.py` — **N-Wiederholungen** pro Fixture + Aggregation: `pass_rate`,
     `mean_score`, `empty_rate`, `over_extraction_rate`, Latenz-Median.
   - [`tests/test_eval.py`](tests/test_eval.py) importiert daraus (kein Logik-Duplikat,
     bestehende Fixtures bleiben gültig).

2. **Erweitertes Fixture-Schema** (abwärtskompatibel — alle neuen Keys optional):
   - Extraktion (`tests/fixtures/eval/`): zusätzlich `max_contacts`, `max_tasks`,
     `max_project_updates` (Über-Extraktion), `forbidden_keywords`, `must_not_be_empty`.
   - **Revision (neu, `tests/fixtures/eval_revision/`):** `original_transcript`,
     `current_result`, `correction`, `known_names`, `expected`. **Erster Fixture = der
     heutige Aibling-Fall** (`forbidden_keywords: ["Eibling"]`, `max_tasks: 1`,
     `must_not_be_empty: true`) — bindet die konkrete Fehlerklasse als Wächter ein.

3. **Benchmark-Runner `scripts/benchmark_models.py`:**
   - CLI: `--models qwen2.5:7b-instruct,ornith:9b`, `--runs 5`, `--suite extraction,revision`,
     `--out benchmarks/results/`.
   - Modell-/Provider-Override via `Settings(llm_provider=…, llm_model=…)` → deckt lokale
     (Ollama) **und** API-Modelle (Anthropic/OpenAI) ab; `build_model()` kann das bereits.
   - **OpenRouter als bequemes Benchmark-Backend** (OpenAI-kompatibel, ein Key, viele
     Modelle inkl. Mistral/Qwen/DeepSeek/GLM). Hier **datenschutzrechtlich unkritisch**,
     weil die Fixtures **synthetisch** sind (keine echten personenbezogenen Daten) —
     passt zu CLAUDE.md („echte Daten erst nach Trockenlauf mit Fake-Daten"). Die
     **konforme** Produktions-Anbindung ist bewusst getrennt (Schritt 8.12).
   - Nutzt exakt den **Produktions-Pfad** (`run_extraction` / `run_revision`) → misst, was
     live passiert (inkl. Primär-→Fallback-Verhalten).
   - Ausgabe: **Vergleichs-Matrix** (Modell × Suite → pass_rate) + Per-Fixture-Aufschlüsselung
     + Ø/Median-Latenz, gut lesbar im Terminal.
   - **Historie:** kompakte Zusammenfassung nach `benchmarks/results/<datum>_<modell>.md`
     (eingecheckt → Fortschritt/Regression über Modell-Versionen sichtbar); Rohläufe gitignored.

4. **Dokumentation `docs/benchmark.md`:** was gemessen wird und **warum** (die vier
   Fehlerklassen, verlinkt auf diese Analyse), **wie man Fixtures ergänzt** (der
   Wachstumspfad, beide Familien), wie man ein Modell registriert, alle Befehle,
   **Ergebnis-Interpretation** (niedrige `pass_rate` vs. `empty_rate` vs.
   `over_extraction_rate` bedeuten Verschiedenes), Schwellenwerte + Begründung,
   Ablage der Historie. Querverweis aus [`docs/live-testing-guide.md`](docs/live-testing-guide.md) §5.

**Wachstums-Prinzipien (bewusst so entworfen — das ist die Kernanforderung).**
- Fixtures sind **Daten, nicht Code** → neues Szenario = neue JSON-Datei, kein Code-Diff.
- Scorer **deklarativ** → neue Prüfung = optionaler `expected`-Key + ein Zweig.
- Modell-Liste als **CLI/Config** → neues Modell = eine Zeile, kein Code-Diff.
- Ergebnisse **append-only** → echtes Regressions-/Fortschritts-Tracking.
- Kategorien/Tags an Fixtures → Suites filterbar, ohne Umbau.

**Vorgehen (test-driven, wo deterministisch — CLAUDE.md).**
- Scorer + Aggregation **zuerst als Unit-Tests** (deterministische Inputs, kein LLM).
- Fixture-Loader mit Schema-Validierung (fehlerhafte Fixtures früh fangen).
- **CI bleibt LLM-frei:** FunctionModel-Smoke prüft auch die neuen Keys; Real-LLM /
  Benchmark laufen nur manuell (`scripts/benchmark_models.py`, `pytest -m eval --real-llm`).

**Bewusst nicht im Scope (Backlog, später).** Automatische CI-Gates gegen echte
Modelle; Kosten-/Token-Tracking pro API-Modell; semantische Ähnlichkeit statt
Keyword-Match; Whisper-Transkriptions-Benchmark (hier nur Text-Fixtures).

**DoD.** ✅
- ✅ `uv run python scripts/benchmark_models.py --models ornith:9b,qwen2.5:7b-instruct --runs 5`
  erzeugt eine Vergleichs-Matrix inkl. `pass_rate`, `empty_rate`, `over_extraction_rate`
  und Latenz — für **Extraktion und Revision** (gegen einzelne lokale Modelle manuell
  verifiziert; der volle 2-Modell-Lauf ist teuer, siehe Kosten-Hinweis in `docs/benchmark.md`).
- ✅ Mind. ein Revisions-Fixture (Aibling-Fall) reproduziert die heutige Fehlerklasse messbar
  (`tests/fixtures/eval_revision/01_aibling_rechtschreibkorrektur.json`).
- ✅ `src/kollege/eval/`-Scorer + Aggregation test-driven; `tests/test_eval.py` nutzt das Paket;
  CI-Kette grün (`ruff` / `mypy` / `pytest`, 199 Tests).
- ✅ [`docs/benchmark.md`](docs/benchmark.md) erklärt Nutzung **und** Wachstumspfad; erste
  Baseline in `benchmarks/results/` eingecheckt — **fünf OpenRouter-Modelle**
  (`mistral-medium-3-5`, `mistral-medium-3`, `mistral-small-2603`, `qwen-2.5-7b-instruct`,
  `glm-4.5-air`) statt des lokalen ornith/qwen-Paars, weil das schneller und billiger ist
  (netzwerkgebunden + `--concurrency`, kein GPU-Engpass) und dieselbe Fragestellung
  beantwortet: `mistral-medium-3-5` ist auf beiden Suiten bei 100 % pass_rate und
  niedrigster Latenz (2–4 s median), `qwen-2.5-7b-instruct` (über OpenRouter) scheiterte
  komplett (100 % error_rate, vermutlich Formatierungs-/Endpoint-Problem — nicht weiter
  untersucht, da außerhalb des Scopes), `mistral-small-2603` zeigt hohe `empty_rate`
  (40 % Extraktion) — der lokale ornith/qwen-Vergleich aus dem Live-Vorfall bleibt jederzeit
  mit demselben Befehl nachvollziehbar.

### Schritt 8.12 — DSGVO-konforme EU-LLM-Anbieter evaluieren & anbinden ⬜

**Motiv.** Designprinzip 5 (lokal-first & Datensparsamkeit). Falls lokale Modelle
qualitativ nicht reichen (siehe 8.11), soll **nicht** blind ein US-Key (OpenAI/
Anthropic direkt) genutzt werden. Bevorzugt: Modelle auf **deutschen/europäischen
Servern**, **DSGVO-konform mit AVV** (Auftragsverarbeitungsvertrag). Dieser Schritt
klärt die Anbieter-Landschaft, wählt 1–2 Kandidaten und bindet sie an — **8.11
liefert die Mess-Grundlage** für die Auswahl.

**Leitstrategie — „erst entdecken, dann konform hosten" (vom Nutzer gewünscht).**
Modell-*Auswahl* und rechtskonformes *Hosting* werden **getrennt**:
1. **Entdeckung:** mit dem bestehenden **OpenRouter**-Account und **synthetischen**
   Benchmark-Fixtures (8.11) ein breites Feld testen — inkl. Mistral, chinesischer
   Open-Weight-Modelle (Qwen, DeepSeek, GLM) u. a. Ziel: herausfinden, *welches Modell
   qualitativ überzeugt*. Datenschutzrechtlich hier unkritisch (keine echten Daten).
2. **Konforme Anbindung:** das gewählte Modell **erst für die Produktion** DSGVO-konform
   re-hosten (siehe Landschaft/Kernabwägung). So bleibt die Entscheidung datengetrieben,
   ohne früh von Hosting-Fragen ausgebremst zu werden.

**Landschaft (Recherche-Ergebnis 2026-07-01, im Schritt aktualisieren/verifizieren).**
- **EU-Lab mit eigenen (auch proprietären) Modellen — bester Fit:**
  - **Mistral** (FR, „La Plateforme"): proprietäres, tool-fähiges Modell (Mistral
    Large) **und** Open-Weight; EU-Firma, AVV, EU-Server; **OpenAI-kompatible API** →
    passt nahezu direkt in [`build_model()`](src/kollege/agent/__init__.py).
  - **Aleph Alpha** (DE): Souveränitäts-Fokus, DE-Hosting; Tool-Calling-Reife prüfen.
- **Frontier-Modelle mit EU-Region + AVV über Hyperscaler** (US-Prozessor, aber
  EU-Datenresidenz): **Claude auf AWS Bedrock** (`eu-central-1` Frankfurt) / **GCP
  Vertex** (`europe-west`); **GPT auf Azure OpenAI** (EU Data Boundary). Erstklassiges
  Tool-Calling, löst die 8.11-Fehlerklasse voraussichtlich vollständig.
- **EU-Souverän-Hoster für Open-Weight-Modelle:** IONOS AI Model Hub (DE), Scaleway
  Generative APIs (FR), OVHcloud AI Endpoints (FR). Hier gilt: **nur Open-Source-Modelle**.
- **Chinesische Open-Weight-Modelle (Qwen, DeepSeek, GLM):** stark und offen → als
  **offene Gewichte auf EU-Hostern** (obige Souverän-Hoster oder self-host) DSGVO-fähig.
  **Wichtig:** **niemals** über die chinesischen **Vendor-APIs** direkt (Daten nach China,
  kein Angemessenheitsbeschluss → DSGVO-Verstoß). Für die reine *Entdeckung* via
  OpenRouter (synthetische Daten) hingegen unproblematisch.
- **Aggregatoren:** **OpenRouter** ist ein **US-Intermediär** — **ideal für die
  Entdeckungsphase** (ein Key, viele Modelle, synthetische Daten), aber als DSGVO-
  Catch-all für Produktion fraglich (Daten laufen über US-Firma; Provider-Filter/
  No-Logging vorhanden, aber kein sauberer EU-AVV auf Router-Ebene). **Nicht** als
  Produktions-Compliance-Fundament einplanen — dort das gewählte Modell konform re-hosten.

**Kernabwägung (Antwort auf „dann nur Open-Source?").** Nein. Nur bei rein EU-nativen
Souverän-Hostern (IONOS/Scaleway/OVH) ist man auf Open-Weight beschränkt. Mit EU-AVV +
EU-Region bei einem Hyperscaler (Bedrock/Vertex/Azure) sind proprietäre Frontier-
Modelle auf EU-Servern nutzbar. **Mistral** vereint beides (EU-Firma + eigenes
proprietäres, tool-fähiges Modell, EU-gehostet).

**Ansatz.**
- [`build_model()`](src/kollege/agent/__init__.py) um Provider erweitern — Mistral ist
  via OpenAI-kompatiblem Endpoint trivial; Bedrock via pydantic-ai `BedrockModel`.
  Keys/Region über `.env` (Präfix `KOLLEGE_`), nie im Repo.
- **8.11-Benchmark als Auswahl-Werkzeug:** Kandidaten gegeneinander messen (pass_rate/
  empty_rate/Latenz) **plus eine Datenschutz-Spalte** in der Ergebnis-Doku: AVV (ja/nein),
  Region, Open-Weight vs. proprietär.
- Datensparsamkeit bleibt (Auszüge statt Volltext); EU-Region explizit pinnen; AVV je
  gewähltem Anbieter abschließen/ablegen.

**Bewusst nicht im Scope.** Anbindung *aller* genannten Anbieter; produktive
AVV-Verträge (das ist ein organisatorischer, kein Code-Schritt — hier nur vorbereiten
und dokumentieren). Siehe auch Querschnitt DSGVO und Schritt 17.

**DoD.**
- [`build_model()`](src/kollege/agent/__init__.py) unterstützt mind. **einen**
  EU-/DSGVO-Anbieter live (Kandidat: Mistral); Config rein über `.env`.
- Benchmark-Vergleich **lokal vs. EU-API** mit 8.11 durchgeführt und in
  `benchmarks/results/` + kurzer Notiz (AVV/Region/Open-vs-proprietär) dokumentiert.
- Empfehlung für das produktive Standard-Modell schriftlich festgehalten (PROJECT_LOG).

---

### Schritt 8.13 — Rückfrage-Antwort-Schleife + robuste 👍/👎-Erkennung ✅

**Motivation (aus Live-Test).** Eine Rückfrage (`clarification`) war bisher eine
Sackgasse: Der Bot fragte nach (z. B. *„Soll der Kontakt ›Kräutergarten Aibling‹
als neuer Dienstleister angelegt werden?"*), speicherte aber **keinen** Pending-
Zustand. Ein 👍 oder „ja" darauf lief ins Leere (`pending=False` → „Reaktion
ignoriert" bzw. neue Extraktion „nichts erkannt"). Die „bei Unklarheit nachfragen"-
Verzweigung (Designprinzip 3) konnte die Antwort also nie entgegennehmen.

**Umgesetzt.**
- Neuer Zustand `PendingClarification` (Ursprungstranskript + gestellte Frage).
  Pro Absender ist **genau ein** offener Zustand erlaubt: Vorschlag *oder* Rückfrage.
- Die nächste Nachricht (Freitext, Sprache **oder** 👍-Tapback) gilt als Antwort und
  wird über `run_clarification_response()` mit dem Ursprungstranskript neu extrahiert
  (analog zur Revisions-Schleife 8.6). Ergebnis → normaler Vorschlag/Bestätigungs-Loop;
  bleibt es unklar → erneute Rückfrage; „nein"/👎 → verwerfen (ohne LLM-Lauf).
- 👍-Erkennung gehärtet: Basis-Codepoint-Vergleich statt exaktem String, damit
  `👍`, `👍️` (Variation-Selector) und `👍🏼` (Hautton) gleich gelten; zusätzlich
  `👌`/`✅` als Zustimmung und `👎`/`❌`/`🚫` als Ablehnung (auch für Vorschläge).

**Dateien.** [`orchestrator.py`](src/kollege/orchestrator.py) (`PendingClarification`,
`_handle_reaction`, `_answer_clarification`, `_discard_clarification`, Emoji-Helfer),
[`agent/__init__.py`](src/kollege/agent/__init__.py) (`run_clarification_response`),
Tests in [`test_orchestrator.py`](tests/test_orchestrator.py) und
[`test_agent.py`](tests/test_agent.py).

**Bewusst nicht im Scope.** Zeitliches Ablaufen offener Rückfragen (TTL) und das
Zusammenführen mehrerer offener Zustände pro Absender.

---

## Schritte 8.14–8.17 — Nutzbarkeits-Block aus Live-Test (mistral3.1-medium)

*Priorisierter Block, abzuarbeiten **vor** der E-Mail-Integration (Schritt 9).
Herleitung und Live-Log siehe [PROJECT_LOG.md](PROJECT_LOG.md), Eintrag
2026-07-02. Jeder Schritt hält an den Designprinzipien fest: passive Erfassung,
Human-in-the-loop (extrahieren → vorschlagen → bestätigen), lokal-first,
Datensparsamkeit.*

### Schritt 8.14 — Vollständige Historie pro Pending-Proposal ▶

**Problem (aus Live-Test).** Die Nutzerin zitiert-antwortet auf einen Vorschlag
mit *„Ich möchte zusätzlich seine Telefonnummer einspeichern (wie in der letzten
Nachricht)"*. Die Korrektur wird korrekt als `_revise` geroutet, liefert aber den
Kontakt **ohne** Nummer — weil die Nummer in einer *früheren* Notiz stand.
[`run_revision`](src/kollege/agent/__init__.py) und
[`run_clarification_response`](src/kollege/agent/__init__.py) bauen ihren Prompt
nur aus (Ursprungstranskript + aktueller Vorschlag + ein Korrekturtext) — es gibt
**kein Gedächtnis über die Turns einer Interaktion**. Referenzen wie „wie vorhin"
laufen daher ins Leere.

**Umsetzung.**
- `PendingProposal` und `PendingClarification` (in
  [`orchestrator.py`](src/kollege/orchestrator.py)) bekommen ein Feld `history`:
  die geordnete Liste **aller Turns einer laufenden Interaktion** (Ausgangsnotiz →
  Rückfrage → Antwort → Vorschlag → Korrektur → …). Wird beim Übergang
  Rückfrage → Vorschlag mitgeführt.
- `run_revision()`/`run_clarification_response()` bekommen die `history` statt nur
  des letzten Transkripts und stellen sie dem Prompt voran.
- **Scope-Grenze (Datensparsamkeit, Prinzip 5):** Historie ist an *eine*
  Interaktion gebunden und wird bei Bestätigung/Ablehnung verworfen. **Kein**
  senderweites Dauergedächtnis, **keine** Cross-Notiz-Referenzen — deckt sich mit
  der bestätigten Regel „neue Nachricht = neue Notiz".

**DoD.** Ein `FunctionModel`-Test zeigt: eine Korrektur, die auf einen in einem
früheren Turn derselben Interaktion genannten Wert verweist, landet im Ergebnis.
`ruff`/`mypy`/`pytest` grün. Kein echter LLM-Aufruf im CI.

### Schritt 8.15 — Query-Funktionen + deutsche Slash-Commands ⬜

**Ziel.** Abfragen des DB-Standes über deterministische Kommandos — ohne LLM,
nimmt dem Modell Entscheidungsdruck (lokal-first, schnell, zuverlässig).

**Umsetzung.**
- Repository ([`repository.py`](src/kollege/db/repository.py)), rein &
  TDD-fähig: `query_open_tasks(sort_by_due=True)`, `list_contacts()`,
  `list_projects()`, `mark_task_done(task_id)` (nutzt vorhandenes
  `update_task_status`).
- **Dispatcher** am Anfang von
  [`handle_message`](src/kollege/orchestrator.py): feste Reihenfolge
  `Command? → offener Vorschlag/Rückfrage? → sonst neue Notiz`. Ersetzt das
  implizite „jeder Text ist eine Notiz".
- Kommandos (deutsch, mit `/`): `/offen`, `/dringend` (überfällige zuerst:
  `due <= heute`, dann nächste Fristen, ohne Datum ans Ende), `/kontakte`,
  `/projekte`, `/erledigt <id>`, `/hilfe`.
- Antworten knapp und mit IDs formatiert (IDs sind der Handle für `/erledigt`).

**DoD.** Command-Routing + jede Query mit `MemoryChannel` getestet; `/erledigt <id>`
schließt genau eine Aufgabe; unbekanntes/fehlerhaftes Kommando → freundlicher
Hinweis + `/hilfe`. Kette grün.

### Schritt 8.16 — Projekt-Markdown-Logs füllen ⬜

**Problem.** [`open_project_log`](src/kollege/logs/__init__.py) legt die
Log-Datei an (`data/projects/<slug>-<id>.md`), aber `ProjectLog.append_entry()`
wird **nirgends** aufgerufen — die Logs enthalten nur den Header (daher die leere
`kräutergarten-aibling-1.md`). Prinzip 4 („Notizbuch bleibt — ergänzen") ist damit
nur halb verdrahtet.

**Umsetzung.** In [`persist_result`](src/kollege/orchestrator.py) bei jeder
bestätigten Projekt-Statusänderung / `phase_note` / projektbezogenen Aufgabe einen
menschenlesbaren Eintrag via `append_entry` schreiben (Zeitstempel + Quelle +
Was). Beantwortet endgültig „wann wird angelegt / was kommt rein".

**DoD.** Nach Bestätigung eines projektbezogenen Vorschlags enthält der Log einen
neuen datierten Eintrag; Test prüft Inhalt (nicht nur Existenz). Kette grün.

### Schritt 8.17 — Erledigungen aus Freitext erkennen & abgleichen ⬜

**Ziel.** Beschreibt die Nutzerin im Freitext, was sie erledigt hat („Heute den
Zaun bei Müller gestrichen und das Angebot an die Gemeinde rausgeschickt"), sollen
die passenden **offenen Aufgaben** erkannt und — nach Bestätigung — geschlossen
werden. Bleibt eine normale Notiz; der **Dispatcher** routet sie in die Extraktion.
Die Intelligenz „getan vs. zu tun" sitzt in der Extraktion, nicht im Routing.

**Umsetzung (Variante A — Erkennung + Abgleich in einem Lauf, bestätigt).**
- `ExtractionResult` (in [`models.py`](src/kollege/models.py)) bekommt ein Feld
  `completed` (erkannte Erledigungs-Aussagen inkl. optionaler Projekt-/
  Kontakt-/ID-Zuordnung).
- **Offene-Aufgaben-Kontext einspeisen**, analog zu
  [`get_known_names_context`](src/kollege/agent/__init__.py): aktuell offene
  Aufgaben (mit IDs) werden dem Transkript vorangestellt, damit der Lauf die
  Erledigung einer bestehenden Aufgabe zuordnen kann.
- Neuer **Eintragstyp im Bestätigungs-Loop** („Aufgabe #N schließen") in
  `_result_items`/`format_proposal`/`persist_result`; Bestätigung →
  `mark_task_done(id)` (aus 8.15).
- **Vertrauensschutz (Prinzip 3):** nie automatisch schließen — immer über den
  Vorschlag, mit ID + Titel sichtbar. Bei unsicherer/mehrdeutiger Zuordnung
  **Rückfrage** statt raten (nutzt vorhandene `clarification`-Mechanik).

**Abhängigkeit.** Baut auf 8.15 (`mark_task_done`, offene-Aufgaben-Query) auf →
daher zuletzt.

**DoD.** `FunctionModel`-Test: eine Erledigungs-Notiz mit passender offener Aufgabe
erzeugt einen „schließen"-Vorschlag; Bestätigung setzt Status auf `erledigt`;
ohne guten Treffer → Rückfrage statt falsches Schließen. Kette grün.

---

## Phase 2 — E-Mail & Übersicht *(zurückgestellt bis Phase 1.5 rund läuft)*

*Ziel: Der Assistent beantwortet „bei wem muss ich mich melden?".*

> **Bewusst zurückgestellt.** Erst wenn sich der Sprachnotiz-Kern im Alltag flüssig
> anfühlt (Phase 1.5), wird E-Mail angegangen. Der Schritt-9-Branch ist begonnen,
> liegt aber; die Reihenfolge wird danach neu bewertet.

### Schritt 9 — IMAP read-only (t-online) 🅿️ *(begonnen, separater Branch, pausiert)*
`secureimap.t-online.de:993` SSL, strikt lesend. E-Mail-Passwort aus Config/Secrets.
- Optionale Dependency-Gruppe `email` (`imapclient` o. ä.) in `pyproject.toml`.
- `Channel`-ähnliches Interface oder direktes Einlesen in den Orchestrator.
- Lazy-Import + Tests gegen Mocks; kein echter IMAP-Server im CI.
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
      → Anbieter-Evaluierung in **Schritt 8.12** (Mistral/Aleph Alpha/Bedrock-EU;
      OpenRouter als US-Intermediär bewusst **kein** DSGVO-Fundament).
- [ ] KI-Transparenz: Assistent gibt sich als KI zu erkennen (sobald Dritte interagieren).
- [ ] Gemeinde-Daten (öffentliche Stellen) besonders sensibel.
- [ ] Transportverschlüsselung überall (IMAP SSL, HTTPS).

## Bewusst zurückgestellt

- **WhatsApp** — Meta verbietet seit 15.01.2026 universelle KI-Chatbots; Business-API
  bräuchte dedizierte Nummer. Signal ersetzt WhatsApp als Assistenz-Kanal.
