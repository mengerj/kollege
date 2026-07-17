# Roadmap-Archiv — Kollege

Detail-Begründungen, Umsetzungsnotizen und DoD der **abgeschlossenen** Roadmap-
Schritte. Ausgelagert aus [ROADMAP.md](ROADMAP.md), um die aktive Roadmap schlank
und token-effizient zu halten (Session-Start liest nur die aktive Roadmap).

**Wann hierher schauen:** nur wenn die Historie/Begründung eines *bereits
erledigten* Schritts gebraucht wird. Der chronologische Verlauf steht in
[PROJECT_LOG.md](PROJECT_LOG.md); die Status-Übersicht in
[ROADMAP.md](ROADMAP.md). Wird ein Schritt fertig, wandert sein Detailblock aus
der Roadmap hierher.

---

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

**Stufe B — Korrektur bereits gespeicherter Einträge:** analog, aber die Zitat-
Antwort/Notiz zielt auf einen persistierten Eintrag. **Aufgaben-Teil in
[Schritt 8.19](#schritt-819--bestehende-aufgaben-bearbeiten-stufe-b-nur-aufgaben-)
umgesetzt** (`update_task`, `edits`-Feld, Log-Konsistenz; adressiert über den
Offene-Aufgaben-Kontext statt über eine persistierte `LastPersistedBatch`-Referenz).
**Noch offen:** Kontakt-Umbenennung (`rename_contact`/`update_contact`) mit Merge-
Semantik (`upsert_contact` dedupt per Name → „Schnitt"→„Schmidt" könnte zwei Einträge
zusammenführen).

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
     **konforme** Produktions-Anbindung ist bewusst getrennt (Schritt 9.1, war 8.12).
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

> **Schritt 8.12 wurde zu [Schritt 9.1](#schritt-91--dsgvo-konforme-eu-llm-anbieter-evaluieren--anbinden-) (Phase 2) verschoben** —
> aktuell nicht in naher Zukunft; `mistral-medium-3.1` trägt den Betrieb.

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

### Schritt 8.14 — Vollständige Historie pro Pending-Proposal ✅

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

**DoD.** ✅ Ein `FunctionModel`-Test
(`test_run_revision_uses_history_to_resolve_earlier_reference`) zeigt: dieselbe
Korrektur liefert ohne `history` keinen Wert zurück, mit `history` (die frühere
Korrektur-Nachricht) landet der referenzierte Wert im Ergebnis. `history` ist als
zusätzliches optionales Argument an `run_revision()`/`run_clarification_response()`
angehängt (statt `original_transcript`/`correction`/`answer` zu ersetzen) und wird
in `_revise()`/`_answer_clarification()` bei jedem Übergang fortgeschrieben.
`ruff`/`mypy`/`pytest` grün (224 Tests), kein echter LLM-Aufruf im CI.

### Schritt 8.15 — Query-Funktionen + deutsche Slash-Commands ✅

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

**DoD.** ✅ Command-Routing + jede Query mit `MemoryChannel` getestet; `/erledigt <id>`
schließt genau eine Aufgabe; unbekanntes/fehlerhaftes Kommando → freundlicher
Hinweis + `/hilfe`. Ein Kommando hat Vorrang vor einem offenen Vorschlag/einer
offenen Rückfrage und lässt diese unangetastet (reiner Seitenkanal). 249 Tests
grün, `ruff`/`mypy` sauber.

### Schritt 8.16 — Projekt-Markdown-Logs füllen ✅

**Problem.** [`open_project_log`](src/kollege/logs/__init__.py) legt die
Log-Datei an (`data/projects/<slug>-<id>.md`), aber `ProjectLog.append_entry()`
wurde **nirgends** aufgerufen — die Logs enthielten nur den Header (daher die leere
`kräutergarten-aibling-1.md`). Prinzip 4 („Notizbuch bleibt — ergänzen") war damit
nur halb verdrahtet.

**Umsetzung.** [`persist_result`](src/kollege/orchestrator.py) schreibt bei jeder
bestätigten Projekt-Statusänderung / `phase_note` / `next_action` / `waiting_on`
sowie bei jeder projektbezogenen Aufgabe einen menschenlesbaren, datierten Eintrag
via `ProjectLog.append_entry(text, source="Sprachnotiz")` — Hilfsfunktionen
`_format_project_update_entry` / `_format_task_entry` formatieren den Text.
`open_project_log()` bleibt reine Anlage/Öffnung (idempotent); `repo.update_project()`
läuft weiterhin nur, wenn der Log-Pfad neu gesetzt wurde.

**DoD.** ✅ Nach Bestätigung eines projektbezogenen Vorschlags enthält der Log einen
neuen datierten Eintrag; drei Tests in
[`test_orchestrator.py`](tests/test_orchestrator.py) prüfen Inhalt (nicht nur
Existenz) inkl. append-only bei zwei aufeinanderfolgenden Änderungen. 252 Tests
grün, `ruff`/`mypy` sauber.

### Schritt 8.17 — Erledigungen aus Freitext erkennen & abgleichen ✅

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

**Umgesetzt.**
- [`models.py`](src/kollege/models.py): `ExtractedCompletion` (`task_id`,
  `task_title`); `ExtractionResult.completed` + `is_empty()` berücksichtigt es.
- [`agent/__init__.py`](src/kollege/agent/__init__.py):
  `build_open_tasks_context()`/`get_open_tasks_context()` (analog zu 8.7) formatieren
  offene Aufgaben mit IDs als Kontext-Block; `run_extraction()` bekommt den Parameter
  `open_tasks_context`; System-Prompt weist zum Abgleich an, bei Unsicherheit/
  Mehrdeutigkeit `clarification` statt raten.
- [`orchestrator.py`](src/kollege/orchestrator.py): `_extract()` lädt den Kontext aus
  dem echten Repo; neuer Eintragstyp „✅ Aufgabe schließen: #N Titel" in
  `_result_items`/`dedupe_result`/`persist_result`; Bestätigung → `mark_task_done`.
  Fallback-Pfad (Tool-Only-Modus für schwache Modelle) unterstützt `completed` bewusst
  **nicht** — der Temp-Repo dort kennt die real offenen Aufgaben nicht.

**DoD.** ✅ `FunctionModel`-Test
(`test_run_extraction_function_model_detects_completion` in
[`test_completions.py`](tests/test_completions.py)): eine Erledigungs-Notiz mit
passender offener Aufgabe im Kontext erzeugt einen `completed`-Eintrag mit aus dem
Kontext übernommener `task_id`; Orchestrator-Tests zeigen „schließen"-Vorschlag →
Bestätigung setzt Status auf `erledigt`; mehrdeutiger Fall → Rückfrage statt falsches
Schließen. 268 Tests grün, `ruff`/`mypy --strict` sauber.

### Schritt 8.18 — Zwei-Durchgang-Extraktion + deutsche Datumsanzeige ✅

**Ziel.** Aus dem Live-Test: Der einstufige One-Shot lässt gelegentlich Dinge
liegen — eine Aufgabe ohne Fälligkeit, obwohl der Text ein Timing nahelegt; eine
Aufgabe ohne Projektzuordnung, obwohl andere Einträge derselben Nachricht dazu
gehören; oder eine Aufgabe wird ganz übersehen. Der Assistent soll die Lücke
**proaktiv selbst schließen**, statt eine Korrektur der Nutzerin abzuwarten.
Zusätzlich: Datumsangaben an die Nutzerin lesbar auf Deutsch (Wochentag + Tag,
Monat, Jahr, z. B. **„Do. 2. Juli 2026"**).

**Kern-Einsicht.** Der Bestätigungs-Loop macht ein **begründetes Raten sicher**:
Jeder Vorschlag wird vor der Persistenz gezeigt und lässt sich per Zitat-Antwort
korrigieren. Der zweite Durchgang soll darum Lücken bevorzugt mit einer guten
Vermutung füllen (im Vorschlag sichtbar) und nur bei **echter, wesentlicher**
Unklarheit eine `clarification` stellen — genau der Punkt, der die häufigen
Korrekturen vermeidet, ohne die Nutzerin mit Rückfragen zu überziehen.

**Umsetzung.**
- [`agent/__init__.py`](src/kollege/agent/__init__.py): neue Funktion
  `run_gap_check(transcript, first_result, …)` — bekommt Transkript **und**
  Erstergebnis, prüft auf (1) Übersehenes, (2) fehlende Frist, (3) fehlende
  Projekt-/(4) Kontaktzuordnung und liefert ein **vollständiges, ergänztes**
  `ExtractionResult`. Reuse: baut wie `run_revision` einen zusammengesetzten
  Prompt und ruft `run_extraction` auf (Primär-/Fallback-Pfad + Namensabgleich +
  offene-Aufgaben-Kontext unverändert). Fehlende Felder werden im Prompt explizit
  als Lücke markiert („OHNE Fälligkeitsdatum"/„OHNE Projektzuordnung").
- [`orchestrator.py`](src/kollege/orchestrator.py): `_extract()` ist jetzt
  **zweistufig** — erster Durchgang (`_extract_first_pass`, bisheriger One-Shot
  mit Retry), dann `run_gap_check`. **Immer zwei Durchgänge**, außer der erste
  stellt bereits eine Rückfrage (die hat Vorrang). Scheitert der zweite Durchgang,
  wird das Erstergebnis genutzt (best-effort, kein Abbruch). Korrektur-/Rückfrage-
  Läufe bleiben einstufig (bereits nutzergesteuert).
- **Datumsanzeige:** `format_date_de(date)` in `orchestrator.py`
  (`"Do. 2. Juli 2026"`, ohne führende Null) — verwendet in `format_proposal`,
  `format_open_tasks` und den Markdown-Log-Einträgen. **Intern/gegenüber dem LLM
  bleibt ISO** (`YYYY-MM-DD`), damit relative Fristen weiter korrekt aufgelöst
  werden.

**DoD.** ✅ `run_gap_check`-Prompt-Test (Transkript + Erstergebnis + explizite
Lücken + durchgereichter Kontext); Orchestrator-Tests: zweiter Durchgang
reichert an und trägt Übersehenes nach, Rückfrage im ersten Durchgang überspringt
den zweiten, Fehler im zweiten Durchgang fällt aufs Erstergebnis zurück;
`format_date_de`-Beispiele inkl. Umlaut-Monat + Anzeige in Vorschlag/`/offen`.
275 Tests grün, `ruff`/`mypy --strict` sauber.

### Schritt 8.19 — Bestehende Aufgaben bearbeiten (Stufe B, nur Aufgaben) ✅

**Auslöser (Live-Test).** Die Nutzerin sah per `/offen`, dass Aufgabe #6 „Bad
Eibling" statt „Bad Aibling" hieß, und wollte den Eintrag per Notiz korrigieren.
Die Rückfrage war vielversprechend (das LLM bot die Korrektur an), nach dem 👍 kam
aber „Ich konnte nichts Konkretes erkennen". **Ursache:** die Extraktion hatte
weder ein Schema-Feld noch eine Repo-Methode, um eine *bestehende* Aufgabe zu
ändern (`ExtractionResult` kannte nur neue Kontakte/Aufgaben/Updates/Erledigungen;
Repository nur `create_task`/`update_task_status`). Das ist die in [8.6](#schritt-86)
bewusst zurückgestellte **Stufe B** — hier für **Aufgaben** umgesetzt (Kontakt-
Umbenennung mit Merge-Semantik bleibt zurückgestellt).

**Umsetzung (spiegelt 8.17 „Erledigungen").**
- [`models.py`](src/kollege/models.py): neues `ExtractedTaskEdit` (`task_id`,
  `task_title` unverändert aus der Liste offener Aufgaben; optionale
  `new_title`/`new_due`/`new_project` — nur gesetzte Felder ändern). `edits`-Feld in
  `ExtractionResult`, in `is_empty()` berücksichtigt.
- [`repository.py`](src/kollege/db/repository.py): neue `update_task(task_id, …)`
  (nur nicht-`None`-Felder schreiben; `ValueError` bei fehlender Aufgabe) +
  öffentliche `get_project_by_id` (für Log-Konsistenz).
- [`agent/__init__.py`](src/kollege/agent/__init__.py): System-Prompt +
  `build_open_tasks_context`-Hinweis erklären Änderungen (edits-Feld, task_id aus
  der Liste, bei Mehrdeutigkeit `clarification`). **Wichtig für den Live-Pfad:**
  `run_revision`/`run_clarification_response` reichen jetzt `open_tasks_context`
  mit — sonst kennt der Lauf *nach* der Rückfrage die Aufgaben-IDs nicht mehr (genau
  der Bug oben). Interne Formatter (Revision/Gap-Check) listen edits mit.
- [`orchestrator.py`](src/kollege/orchestrator.py): neuer Vorschlagstyp
  „✏️ Aufgabe ändern: #N Titel — Titel → «…», Frist → …" (`_result_items`,
  `_edit_changes`); `dedupe_result` dedupt edits per `task_id`; `persist_result`
  ruft `update_task` und vermerkt die Korrektur **append-only** im Projekt-Log
  (Prinzip 4); nicht mehr vorhandene Aufgabe wird übersprungen.

**Bewusste Grenzen.** Kontakt-Umbenennung (Merge/Dedup) weiter offen. Adressierung
nur über die Liste offener Aufgaben (der Offene-Aufgaben-Kontext) — keine
persistierte „Last-Batch"-Referenz. Fallback-Pfad (schwache Modelle) unterstützt
edits wie schon `completed` nicht (Temp-Repo kennt die realen Aufgaben nicht).

**DoD.** ✅ `FunctionModel`-Test: Korrektur-Notiz + passende offene Aufgabe → `edits`
mit übernommener `task_id`; Repo-`update_task`-Tests (Titel/Frist/Projekt, `None`=
unverändert, unbekannte ID → `ValueError`, Status bleibt offen); `persist_result`
ändert Titel + schreibt Log-Korrektur; Orchestrator: Edit-Notiz → „ändern"-Vorschlag
→ Bestätigung ändert die DB; Rückfrage-Antwort-Lauf reicht `open_tasks_context` durch.
289 Tests grün, `ruff`/`mypy --strict` sauber.

### Schritt 8.20 — Korrektur-Lauf: Erledigungen bleiben erhalten (Bugfix aus Live-Test) ✅

**Vorfall (Live-Test 2026-07-02, `mistral-medium-3.1` via OpenRouter).** Lange
Sprachnotiz mit neuen Aufgaben und **drei** Erledigungs-Aussagen:
1. Erster Vorschlag: zwei der drei Erledigungen erkannt (plus die neuen Aufgaben).
2. Zitat-Antwort *„prüf, ob noch eine Aufgabe erledigt wurde"* → **derselbe**
   Vorschlag kam zurück.
3. Zitat-Antwort mit **expliziter Nennung** der fehlenden Erledigung → der
   revidierte Vorschlag enthielt nur noch diese eine — **die zwei zuvor erkannten
   Erledigungen waren verschwunden**.

**Ursache (im Code deterministisch belegbar).**
[`_format_result_for_revision`](src/kollege/agent/__init__.py) rendert den
„Bisherigen Vorschlag" für den `[KORREKTUR-LAUF]`-Prompt aus Kontakten, Aufgaben,
Projekt-Updates und Edits — **aber nicht aus `result.completed`**. Das LLM hat die
bereits erkannten Erledigungen im Korrektur-Lauf also **nie gesehen**. Da jeder
Korrektur-Lauf ein frischer One-Shot ist, der den gesamten Vorschlag neu erzeugt
(kein Chat-Gedächtnis), sind nicht gezeigte Einträge de facto gelöscht — es sei
denn, das Modell leitet sie zufällig erneut aus dem Ursprungstranskript ab. Genau
das erklärt die Nicht-Determinismen: In Runde 2 hat es die Erledigungen neu
abgeleitet (gleicher Vorschlag), in Runde 3 nicht (Einträge weg). Die
Schwesterfunktion [`_format_result_for_gap_check`](src/kollege/agent/__init__.py)
listet `completed` korrekt — beim Nachrüsten von 8.17/8.19 wurde nur die
Revisions-Variante vergessen. Runde 2 scheiterte zusätzlich strukturell: eine
Meta-Aufforderung ohne neue Information trifft auf exakt dieselben Inputs wie
Lauf 1 (siehe „Bewusst offen" unten).

**Umsetzung (erledigt).**
- **Formatter vereinheitlicht:** `_format_result_for_prompt(result, *, mark_gaps)`
  in [`agent/__init__.py`](src/kollege/agent/__init__.py) ersetzt die getrennten
  `_format_result_for_revision`/`_format_result_for_gap_check` (eine Quelle der
  Wahrheit). Beide Läufe listen jetzt **alle** Kategorien inkl. `completed`
  („Erledigung: #id Titel") und `edits` (mit Änderungsdetails via
  `_format_edit_changes`); `mark_gaps=True` behält die explizite Lücken-Markierung
  („OHNE Fälligkeitsdatum"/„OHNE Projektzuordnung") des Gap-Checks bei.
- **Revisions-Prompt geschärft** ([`run_revision`](src/kollege/agent/__init__.py)):
  „Übernimm alle Einträge des bisherigen Vorschlags unverändert, die von der
  Korrektur nicht betroffen sind — auch bereits erkannte Erledigungen und
  Änderungen. Entferne einen Eintrag nur, wenn die Korrektur das ausdrücklich
  verlangt."
- **Regression abgesichert (test-driven):**
  - Prompt-Inspektions-Test (`test_run_revision_prompt_includes_completed_and_edits`):
    `completed` + Edit-Zieltitel + Übernahme-Anweisung im Revisions-Prompt sichtbar.
  - Verhaltens-Test (`test_run_revision_prompt_completed_survive_reflecting_model`):
    ein „treues" FunctionModel, das nur die im Prompt sichtbaren IDs zurückgibt,
    behält dank des Fixes die zwei alten Erledigungen + die neue.
  - Orchestrator-Test (`test_revision_keeps_prior_completions`): echter
    Revisions-Pfad über Quote-Reply → Pending-Result behält `{6, 7}` und ergänzt `8`.
  - **Benchmark-Fixture** (Wachstumspfad 8.11):
    `tests/fixtures/eval_revision/03_erledigungen_bleiben_erhalten.json` (Vorfall:
    2 erkannte + 1 nachgereichte Erledigung → erwartet alle 3). Deklarativer Scorer
    um `min_completed` + `must_contain_task_ids` erweitert (je ein optionaler Key +
    ein Zweig).

**Bewusst offen / nicht im Scope (Entscheid Nutzerin 2026-07-02).**
- **Deterministischer Merge** („verlorene Einträge automatisch behalten"):
  zurückgestellt. Kernproblem: das System kann ohne LLM **nicht wissen**, welcher
  Teil des Vorschlags von der Korrektur betroffen war — ein stumpfer Merge würde
  auch **bewusste Löschungen** („Nummer 2 streichen") wieder hineinmergen.
  Leichtgewichtige Alternative, falls der Prompt-Fix live nicht reicht:
  **sichtbarer Diff** im revidierten Vorschlag („Nicht mehr enthalten: …" —
  deterministisch berechenbar aus altem vs. neuem Result), sodass die Nutzerin
  Verluste sofort sieht und per weiterer Korrektur zurückholen kann
  (Human-in-the-loop statt Raten). Entscheidung nach Live-Erfahrung mit dem Fix.
- **„Prüf nochmal"-Meta-Korrekturen** auf `run_gap_check` routen (semantisch ist
  das ein erneuter Lücken-Check, kein Revisions-Lauf): zurückgestellt, erst
  angehen, falls das Bedürfnis wieder auftaucht.

**DoD.** ✅
- ✅ Revisions-Prompt zeigt `completed` (und Edit-Details) des bisherigen Vorschlags;
  Übernahme-Anweisung ergänzt.
- ✅ Prompt-Test + Verhaltens-Test + Orchestrator-Regressionstest grün; neues
  Revisions-Fixture reproduziert die Fehlerklasse messbar (Scorer um `min_completed`/
  `must_contain_task_ids` erweitert, via `scripts/benchmark_models.py` nutzbar).
- ✅ CI-Kette grün (`ruff` / `mypy --strict` / `pytest`, 294 Tests).

### Schritt 8.21 — Live-Debugging-Observability: LLM-Traces + lückenloses Verlaufs-Log ✅

**Motiv (aus der 8.20-Analyse).** Der Vorfall war **nicht aus Aufzeichnungen
rekonstruierbar**, sondern nur durch Code-Lektüre: Es gibt kein Protokoll, welchen
Kontext das LLM bekam, welche Tools es (mit welchen Argumenten) aufrief, was es
zurückgab, ob Primär- oder Fallback-Pfad lief. Dazu Lücken im normalen Logging:
die INFO-Zeilen „Extraktion:/Korrektur-Lauf: %d Kontakt(e), %d Aufgabe(n), %d
Projekt-Update(s)" zählen **`completed` und `edits` nicht mit** (genau die
Kategorie des Vorfalls war unsichtbar), und der Bot-Output ging nur an das
Terminal (kein `kollege.log` beim Vordergrund-Start). Ziel: Eine Live-Testsession
soll im Nachhinein vier Fragen vollständig beantworten:
1. **Was kam an und wie wurde geroutet?** (Text/Audio/Reaktion; Command /
   Bestätigung / Korrektur / Rückfrage-Antwort / neue Notiz)
2. **Welchen exakten Kontext bekam das LLM je Lauf?** (System-Prompts,
   Kontext-Blöcke, zusammengesetzter Prompt)
3. **Welche Tool-Calls mit welchen Argumenten und Rückgaben?** (inkl. Retries und
   Primär-/Fallback-Umschaltung)
4. **Was wurde vorgeschlagen, bestätigt, persistiert?**

**Baustein 1 — Trace-Modul `src/kollege/trace.py` (opt-in, Volltext).**
- `TraceWriter`-Protocol mit `NoopTraceWriter` (Default) und `JsonlTraceWriter`:
  eine Datei pro Tag (`data/traces/2026-07-02.jsonl`, append-only), ein
  JSON-Objekt pro Zeile: `ts` (ISO, UTC), `event`, `run_id`, `payload`.
- **Konfiguration:** `Settings.trace_enabled` (env `KOLLEGE_TRACE`, Default aus)
  und `Settings.trace_dir` (Default `data/traces`). **Datensparsamkeit
  (Prinzip 5):** Traces enthalten Volltexte (Transkripte, Prompts) → nur für
  Debugging-Phasen aktivieren; `data/` ist bereits gitignored; Lösch-Hinweis in
  der Doku. Keine Audio-Dateien, nur Text.
- **LLM-Lauf-Erfassung in [`run_extraction`](src/kollege/agent/__init__.py)** —
  dem Trichter, durch den alle vier Laufarten gehen. Neuer expliziter Parameter
  `kind` (`extraktion | gap_check | revision | clarification_response`), von den
  Wrappern (`run_gap_check`/`run_revision`/`run_clarification_response`)
  durchgereicht. Pro Lauf ins Trace:
  - `kind`, Modell + Provider, Latenz, Primär- oder Fallback-Pfad,
    Token-`usage` (liefert pydantic-ai mit).
  - Der **komplette augmentierte User-Prompt** (Bekannte-Namen-Block,
    Offene-Aufgaben-Block, `[NOTIZ]`/`[KORREKTUR-LAUF]`/…-Prompt).
  - **Alle Messages des Laufs** via `result.all_messages()`, serialisiert mit
    `pydantic_ai.messages.ModelMessagesTypeAdapter` → enthält System-Prompts,
    jeden **Tool-Call mit Argumenten**, jede Tool-Rückgabe, Retries und die
    finale Antwort. **Wichtig für Fehlerfälle:** Läufe, die mit
    `UnexpectedModelBehavior` o. ä. abbrechen, mit
    `pydantic_ai.capture_run_messages()` umschließen, damit gerade die
    **gescheiterten** Läufe (die interessanten) ihre Messages ins Trace schreiben.
  - Exceptions mit Typ + Text als eigenes Event.
- **Orchestrator-Ereignisse** (gleiche Datei — macht den Faden end-to-end lesbar):
  `message_received` (Art: Text/Audio/Reaktion, Transkript), `routing`
  (Command/ja/nein/Auswahl/Korrektur/Rückfrage-Antwort/neue Notiz),
  `proposal_sent` (formatierter Vorschlagstext), `clarification_sent`,
  `confirmed` (Indizes)/`rejected`, `persisted` (Anzahl + Item-Labels), `error`.
  Übergabe des Writers an den `Orchestrator`-Konstruktor (Default `Noop` — Tests
  und Bestand bleiben unberührt).

**Baustein 2 — Dauer-Logging-Lücken schließen (immer an, inhaltsfrei).**
- INFO-Zeilen in [`orchestrator.py`](src/kollege/orchestrator.py) um
  `completed`/`edits`-Zähler ergänzen (Extraktion, Rückfrage-Antwort,
  Korrektur-Lauf — alle drei Stellen).
- [`scripts/run_signal.py`](scripts/run_signal.py): zusätzlich zum Konsolen-Handler
  einen `FileHandler` auf `kollege.log` konfigurieren, damit der Verlauf auch beim
  Vordergrund-Start ohne Shell-Redirect persistiert (der Vorfalls-Prozess lief
  ohne Redirect → Log weg beim Schließen des Terminals).
- Klare Trennung dokumentieren: **Dauer-Log = inhaltsfrei** (Datensparsamkeit),
  **Trace = opt-in mit Volltext** für Debugging-Phasen.

**Baustein 3 — Trace-Viewer `scripts/show_trace.py`.**
- CLI: `--date 2026-07-02` (Default: heute), `--last N` (letzte N Läufe),
  `--run <run_id>` (ein Lauf komplett), `--full` (Prompts ungekürzt).
- Menschenlesbare Ausgabe: chronologische Ereignisliste; pro LLM-Lauf Kind,
  Modell, Kontext-Blöcke, Tool-Call-Sequenz mit Argumenten → Rückgaben, finales
  `ExtractionResult`, Tokens/Latenz/Pfad. Zweck: in einer Live-Session in
  Sekunden beantworten, *warum* ein Eintrag fehlte oder verschwand.
- [`docs/live-testing-guide.md`](docs/live-testing-guide.md) §3 um Abschnitt
  „e) LLM-Traces" erweitern (Aktivieren, Anschauen, Löschen).

**Umgesetzt — Design-Entscheidungen (im Schritt getroffen).**
- **`run_id`-Umfang:** eine `run_id` pro **eingehender Nachricht**
  (`Orchestrator.handle_message`), geteilt von *allen* Orchestrator-Ereignissen
  **und** allen darin ausgelösten LLM-Läufen dieser einen Nachricht (z. B.
  Erst-Extraktion **und** Lücken-Prüfung tragen dieselbe `run_id`, unterschieden
  über `kind`). Dadurch zeigt die Standard-Ansicht (`--date`, kein `--run`)
  bereits den **kompletten Faden** über mehrere Nachrichten hinweg (Nachricht →
  Vorschlag → Korrektur → Bestätigung sind ohnehin chronologisch in derselben
  Tagesdatei); `--run <id>` zoomt gezielt in **eine** Nachricht/einen
  Verarbeitungszyklus.
- **Env-Name `KOLLEGE_TRACE`** (nicht `KOLLEGE_TRACE_ENABLED`): das
  Präfix-Schema von pydantic-settings hätte automatisch Letzteres erzeugt;
  `Field(validation_alias="KOLLEGE_TRACE")` erzwingt den kurzen, in der Planung
  festgelegten Namen.
- Primär- **und** Fallback-Pfad in `run_extraction` sind je in einen eigenen
  `capture_run_messages()`-Block gefasst (nicht einen gemeinsamen), damit auch
  ein scheiternder Fallback-Lauf seine Messages ins Trace schreibt, bevor die
  Exception weitergereicht wird.

**Abwägungen.**
- **Pydantic Logfire** (von pydantic-ai nativ unterstützt) böte UI/Spans, ist aber
  ein Cloud-Dienst → für Volltext-Traces gegen lokal-first/Datensparsamkeit.
  Lokale JSONL zuerst; Logfire-Selfhost/OTel bei VPS-Betrieb (Schritt 16) neu
  bewerten.
- **Warum nicht einfach mehr INFO-Logging?** Prompts und Tool-Argumente gehören
  nicht in ein dauerhaft aktives Log. Die Zweiteilung (inhaltsfreies Dauer-Log +
  opt-in-Trace) hält Prinzip 5 ein und liefert trotzdem volle Tiefe, wenn man sie
  braucht.

**Vorgehen (test-driven, ohne LLM im CI).**
- `JsonlTraceWriter` gegen `tmp_path`: append-only, valides JSONL, Tagesdatei.
- Serialisierung der Lauf-Messages mit `FunctionModel`: Tool-Call-Argumente und
  finales Result landen im Trace; Fehlerpfad mit `capture_run_messages` getestet.
- Orchestrator-Events mit `MemoryChannel` + `JsonlTraceWriter` (voller Faden:
  Nachricht → Vorschlag → Korrektur → Bestätigung → persisted).
- Viewer: reine Parse-/Format-Funktionen unit-getestet.

**DoD.** ✅
- ✅ Mit `KOLLEGE_TRACE=1` erzeugt der Ablauf Nachricht → Vorschlag → Korrektur →
  Bestätigung eine Trace-Datei, aus der `scripts/show_trace.py` den kompletten
  Faden lesbar rendert — inkl. exaktem LLM-Kontext und allen Tool-Calls je Lauf,
  auch bei gescheiterten Läufen (manuell smoke-getestet mit einem echten
  `FunctionModel`-Lauf gegen ein `tmp`-Trace-Verzeichnis).
- ✅ INFO-Zeilen zählen `completed`/`edits` mit (alle drei Stellen: Erst-Extraktion,
  Rückfrage-Antwort, Korrektur-Lauf); `kollege.log` wird via zusätzlichem
  `FileHandler` in [`scripts/run_signal.py`](scripts/run_signal.py) auch ohne
  Shell-Redirect geschrieben.
- ✅ Guide §3e dokumentiert Nutzung + Datensparsamkeits-Hinweis (Aktivieren/
  Anschauen/Löschen); CI-Kette grün (`ruff`/`ruff format`/`mypy --strict`/`pytest`,
  328 Tests: neue [`test_trace.py`](tests/test_trace.py),
  [`test_show_trace.py`](tests/test_show_trace.py), Erweiterungen in
  `test_agent.py`/`test_orchestrator.py`/`test_config.py`).

---

### Schritt 8.22 — Löschen von Einträgen (Kontakte/Projekte/Aufgaben) ✅

**Motiv (aus Live-Test 2026-07-03, Trace `data/traces/2026-07-03.jsonl`).** Die
Nutzerin bat *„Lösche alle gespeicherten Kontakte und Projekte"*. Das Modell
stellte korrekt eine Rückfrage (destruktive Aktion), auf *„Alles. Das waren bis
jetzt nur Tests"* lief der `clarification_response`-Lauf aber ins **Leere**: ein
komplett leeres `ExtractionResult`, **keine Aktion, keine Rückmeldung**. Ursache:
Es existierte **keine Lösch-Funktion** — weder ein Repository-Verb noch ein
Command noch ein Tool. Das `ExtractionResult`-Schema kann „Löschen" gar nicht
ausdrücken, also verschwand die Absicht kommentarlos — ein Vertrauensbruch
(Prinzip 3/6): die Nutzerin dachte, etwas sei passiert.

**Designentscheidung — deterministisch per Slash-Command, nicht über die
LLM-Extraktion.** Löschen ist destruktiv und selten; es gehört **nicht** in den
probabilistischen Extraktionspfad (Über-/Fehl-Löschung wäre fatal). Konsistent zu
Schritt 8.15 (Queries = deterministische Commands ohne LLM-Entscheidungsdruck).

**Umgesetzt.**
- **Repository** ([`db/repository.py`](src/kollege/db/repository.py)):
  `delete_contact(id)`, `delete_project(id)`, `delete_task(id)`, `reset_all()`
  sowie die Hilfsmethoden `get_task_by_id`, `get_tasks_by_project`,
  `get_all_tasks`. Referentielle Regeln bewusst asymmetrisch festgelegt:
  ein gelöschter **Kontakt** löst nur die Zuordnung (`contact_id` auf
  Projekten/Aufgaben wird `NULL`, nichts wird mitgelöscht — Notizbuch-Prinzip:
  ergänzen, nicht ersetzen); ein gelöschtes **Projekt** reißt seine Aufgaben mit
  (Cascade — sie gehören inhaltlich dazu, ein verwaister Rest wäre verwirrender
  als ihr Wegfall). Unbekannte IDs werfen `ValueError` (wie bei
  `update_task`/`mark_task_done`).
- **Deutsche Commands** ([`orchestrator.py`](src/kollege/orchestrator.py)):
  `/loeschen kontakt|projekt|aufgabe <id>` und `/zuruecksetzen` (alles), im
  bestehenden Dispatcher.
- **Zwei-Schritt-Bestätigung (Prinzip 3):** neuer Pending-Zustand
  `PendingDeletion` (dritter, exklusiver Zustand neben `PendingProposal`/
  `PendingClarification` — genau einer pro Absender). Die Commands zeigen zuerst
  eine Vorschau (Name/Titel; bei einem Projekt zusätzlich die Anzahl
  mitgelöschter Aufgaben) und warten auf ein explizites 👍/„ja" (auch als
  Tapback-Reaktion); „nein"/👎 verwirft. Eine neue, unbeantwortete Notiz lässt
  eine offene Lösch-Bestätigung stillschweigend verfallen (wie beim Ersetzen
  eines offenen `PendingProposal`); ein Race (Ziel zwischen Vorschau und
  Bestätigung anderweitig verschwunden) wird freundlich gemeldet statt
  abzustürzen.
- **Extraktionspfad gesprächsfähig, aber löschfrei**
  ([`agent/__init__.py`](src/kollege/agent/__init__.py)): neuer Absatz im
  System-Prompt weist das Modell an, bei erkannter Lösch-Absicht **nichts**
  anzulegen und **kein** Tool aufzurufen, sondern das `clarification`-Feld mit
  einem Hinweis auf die passenden Commands zu setzen — damit eine Lösch-Absicht
  nie mehr stumm im Leeren endet.
- `/hilfe` listet die neuen Commands.

**Bewusst nicht im Scope.** Fuzzy-Matching/Mehrfachauswahl beim Löschen (z. B.
„lösche alle Aufgaben von Müller"), Undo/Soft-Delete — reine ID-basierte
Einzel-Löschung plus `reset_all()` für die Testdaten-Situation reicht für den
aktuellen Bedarf.

**DoD.** ✅
- ✅ Repository-Löschverben test-driven (In-Memory-SQLite; referentielle Regeln
  für Kontakt-Unlink vs. Projekt-Cascade geprüft, inkl. unbekannter IDs).
- ✅ Commands im Dispatcher mit Zwei-Schritt-Bestätigung getestet (Vorschau,
  ja/nein, 👍/👎-Tapback, Race-Handling, Invarianten-Tests: Lösch-Command
  verwirft offenen Vorschlag/offene Rückfrage; neue Notiz verwirft offene
  Lösch-Bestätigung).
- ✅ Extraktionspfad bleibt löschfrei; System-Prompt-Instruktion durch
  Regressionstest abgesichert (echte LLM-Verifikation nicht in CI, siehe
  CLAUDE.md).
- ✅ `/hilfe` listet `/loeschen` und `/zuruecksetzen`.
- ✅ CI-Kette grün (`ruff`/`ruff format`/`mypy --strict`/`pytest`, 357 Tests).

### Schritt 8.23 — Kontext-Deduplizierung + Gap-Check-Gating (Token-Sparen) ✅

**Motiv (Trace-Analyse 2026-07-03).** `data/traces/2026-07-03.jsonl` zeigte: der
zweite Extraktions-Durchgang (`run_gap_check`, Schritt 8.18) läuft bei *jeder*
Notiz, verdoppelt dabei fast den kompletten Prompt-Kontext und lieferte für eine
reine Erledigungs-Notiz (nur `completed`, sechs Einträge) ein **byte-identisches**
Ergebnis bei vollem zweiten LLM-Call — 3107 → 3662 Input-Tokens für nichts.

**Umgesetzt.**
- **Gating** ([`models.py`](src/kollege/models.py)):
  `ExtractionResult.has_gap_check_candidates()` — `True` nur wenn `contacts`/
  `tasks`/`project_updates`/`locations` nicht leer sind (bewusst **ohne**
  `completed`/`edits`: die referenzieren nur IDs bestehender Aufgaben, es gibt
  dort keine Frist-/Zuordnungs-Lücke zu füllen — genau der Trace-Fall).
  [`orchestrator.py`](src/kollege/orchestrator.py): `_extract()` überspringt
  `run_gap_check`, wenn das Erstergebnis keine Kandidaten hat (nach dem
  bestehenden `clarification`-Vorrang-Check), schreibt dafür ein
  `routing`-Trace-Ereignis.
- **Kontext-Kompaktierung im Gap-Check** ([`agent/__init__.py`](src/kollege/agent/__init__.py)):
  `_format_result_for_prompt()` bekommt `compact_task_refs` — referenziert
  Erledigungen/Änderungen im „Erster Vorschlag" nur noch per `#task_id` statt
  vollem Titel, sobald `open_tasks_context` (wo der Titel bereits steht)
  tatsächlich mitgeschickt wird (`run_gap_check` setzt das Flag automatisch
  über `bool(open_tasks_context)`) — ohne Kontext bleibt der volle Titel
  erhalten, kein Informationsverlust.
- **Trace-Redundanz behoben** ([`agent/__init__.py`](src/kollege/agent/__init__.py)):
  `_serialize_messages()` ersetzt die `user-prompt`-Part (identisch mit
  `llm_run_start.payload.prompt` desselben Laufs) durch einen Verweis-Marker
  statt sie erneut abzulegen. `scripts/show_trace.py` unverändert lauffähig
  (Struktur bleibt, nur der Inhalt ist jetzt ein Verweis).
- **Benchmark (8.11) um Zwei-Durchgang-Modus erweitert**
  ([`scripts/benchmark_models.py`](scripts/benchmark_models.py)): neues
  `--two-pass`-Flag misst Erstextraktion **+** gegateten Gap-Check — der
  bestehende Benchmark maß bis dahin nur die Erstextraktion, obwohl die
  Produktion seit 8.18 zweistufig läuft. Rückwärtskompatibel (Default
  unverändert).

**Bewusst nicht im Scope.** Die „Instruktionen entdoppeln"-Idee (completed/
edits/clarification-Anweisung steht mehrfach im System-Prompt *und* in den
Kontextblöcken) wurde nicht angefasst — das Risiko, dass kleinere/lokale
Modelle auf die Wiederholung angewiesen sind, ließ sich in dieser Session
nicht sauber live verifizieren (Produktionsmodell-Zugriff blockiert, siehe
unten); die DoD verlangt „messbar reduziert", nicht „vollständig behoben".
Bleibt Folge-Idee für einen künftigen Schritt.

**Messung — mit Einschränkung.** Der 8.11-Benchmark gegen das
**Produktionsmodell** (`openrouter:mistralai/mistral-medium-3.1`) scheiterte
an einem **OpenRouter-Konto-Problem** (siehe PROJECT_LOG 2026-07-17 — dieses
Modell wird kontoseitig aktuell für *jede* Anfrage abgelehnt, unabhängig von
diesem Schritt). Ausgewichen auf `qwen2.5:7b-instruct` (lokal) mit
`--two-pass --runs 2`: **83 % pass_rate, 0 % error_rate** über 6 Fixtures × 2
Läufe (`benchmarks/results/2026-07-17_qwen2.5-7b-instruct-two-pass.md`). Da
alle 6 Extraktions-Fixtures mindestens eine Aufgabe/einen Kontakt/ein
Projekt-Update/einen Ort liefern, griff das Gating bei keinem der 12 Läufe —
die 0 %-Fehlerrate zeigt aber, dass der neue Zwei-Durchgang-Pfad end-to-end
fehlerfrei läuft. Die eigentliche Gating-Kernbehauptung (identischer Output
bei reiner Erledigungs-Notiz) stützt sich stattdessen auf den **echten**
Produktions-Trace vom 2026-07-03 (siehe Motiv oben) plus die neuen
deterministischen Unit-Tests — bewusst kein teurer Blindflug-Benchmark für
einen Fall, der bereits mit echten Daten belegt ist.

**Nebenfund.** Ein direkter Test entdeckte, dass OpenRouter das
Produktionsmodell `mistral-medium-3.1` kontoseitig blockiert (404 „No
endpoints available matching your guardrail restrictions and data policy"),
während andere Modelle über denselben Key funktionieren — vermutlich eine
Datenschutz-/Guardrail-Einstellung unter openrouter.ai/settings/privacy.
Potenziell ein stiller Produktionsausfall, falls der Bot live läuft. Kein
Code-Fix (Konto-Einstellung) — als eigene Aufgabe ausgelagert, siehe
PROJECT_LOG 2026-07-17.

**DoD.** ✅
- ✅ Gap-Check läuft nur noch bei tatsächlichem Bedarf (`has_gap_check_candidates`,
  Gating per Unit-Test + Orchestrator-Integrationstest abgesichert).
- ✅ Kontext-Redundanz im Gap-Check messbar reduziert: Trace-Ebene (Prompt nicht
  mehr doppelt gespeichert, per Test verifiziert) + Prompt-Ebene (kompakte
  Aufgaben-Referenzen im Gap-Check, per Test verifiziert). Instruktions-Redundanz
  im System-Prompt bewusst nicht angefasst (siehe oben).
- ✅ Trace speichert den Prompt nicht mehr doppelt; Viewer (`show_trace.py`)
  weiterhin funktionsfähig (keine Änderung nötig).
- ✅ Benchmark zeigt keine Qualitäts-Regression (0 % Fehlerrate im
  `--two-pass`-Lauf; Einschränkungen zur Aussagekraft oben dokumentiert).
- ✅ CI-Kette grün (`ruff`/`ruff format`/`mypy --strict`/`pytest`, 459 Tests,
  13 neu).

### Schritt 8.25 — Neue Projekte in Vorschlag & Bestätigung sichtbar ✅

**Motiv (Live-Beobachtung Nutzer).** Legt eine Aufgabe implizit ein neues
Projekt an (`get_or_create_project` in `persist_result`), tauchte das weder im
Vorschlag noch in der Bestätigung auf — gezählt und angezeigt wurden nur die
`_result_items` (Kontakte/Aufgaben/Projekt-Updates/…). Die Nutzerin erfuhr
nicht, dass ein Projekt entstanden ist → Human-in-the-loop-Lücke
(Designprinzip 3): sie bestätigte etwas, dessen Nebeneffekt sie nicht sah.

**Umgesetzt.**
- **Repository** ([`db/repository.py`](src/kollege/db/repository.py)):
  nicht-anlegende `get_project_by_title(title)` ergänzt; `get_or_create_project`
  nutzt sie intern (Konsistenz-Refactor, analog zu `get_contact_by_name` in
  `upsert_contact`).
- **Vorschlag** ([`orchestrator.py`](src/kollege/orchestrator.py)):
  `_unknown_project_names(result, repo)` ermittelt, welche `task.project`-/
  `project_updates.project`-Namen noch nicht in der DB existieren;
  `_result_items`/`format_proposal` markieren sie im Label als
  `[Projektname — neu]` bzw. `📁 Projekt: Name — neu`. `format_proposal` bekommt
  dafür ein optionales `repo`-Argument (ohne Repo — z. B. isolierte
  Formatierungstests — keine Markierung, Rückwärtskompatibilität).
- **Persistenz**: neue `PersistSummary`-Dataclass (`count` + `new_projects`)
  ersetzt den nackten `int`-Rückgabewert von `persist_result`. Vor jedem
  `get_or_create_project`-Aufruf (Projekt-Update, Aufgabe, Aufgaben-Edit mit
  `new_project`) prüft `persist_result` per `get_project_by_title`, ob das
  Projekt schon existiert, und sammelt neu angelegte Titel — dedupliziert sich
  dadurch selbst (nach der ersten Anlage liefert die Prüfung beim nächsten
  Vorkommen desselben Namens nicht mehr „unbekannt"). Das ist bewusst die
  **einzige Stelle der Wahrheit**: zwischen Vorschlag und Bestätigung kann ein
  Projekt anderweitig entstehen (Race) — der Vorschlag markiert nur eine
  Momentaufnahme, `persist_result` entscheidet verbindlich.
- **Bestätigung**: `_confirm` hängt bei nicht-leerer `new_projects`-Liste einen
  Zusatzsatz an die bisherige „✅ N Eintrag/Einträge gespeichert."-Meldung an
  (z. B. `Neues Projekt angelegt: "Neuer Kundengarten".`), Singular/Plural
  („Neues Projekt(e) angelegt") je nach Anzahl.

**Bewusst nicht im Scope.** Eigene `📁 Neues Projekt: X`-Zeile als Alternative
zur Inline-Markierung (Roadmap nannte beide Varianten zur Wahl) — Inline-Marker
gewählt, weil er 1:1 bei den bestehenden, indexbasierten `_result_items`
bleibt (keine zusätzliche, nicht-auswählbare Zeile, die die Nummerierung der
Auswahl verwirren könnte).

**DoD.** ✅
- ✅ `get_project_by_title` test-driven (fehlend → `None`, vorhanden → Treffer).
- ✅ `format_proposal`: unbekanntes Projekt (Aufgabe *und* Projekt-Update) wird
  markiert; bestehendes Projekt nicht; ohne `repo`-Argument keine Markierung.
- ✅ `persist_result`/`PersistSummary`: `new_projects` für neues Projekt
  gefüllt, für bestehendes Projekt leer, bei zwei Aufgaben im selben neuen
  Projekt nur einmal gelistet (Dedup).
- ✅ Orchestrator-E2E (gemockte `run_extraction`): unbekanntes Projekt → Marker
  im Vorschlag *und* Namensnennung in der ✅-Bestätigung; bestehendes Projekt →
  keine Markierung, unveränderte Zählung.
- ✅ CI-Kette grün (`ruff`/`ruff format`/`mypy --strict`/`pytest`, 369 Tests).

---

### Schritt 8.26 — Vierte Entität „Örtlichkeit" (Name/Adresse/Flurnummer) ✅

**Motiv.** Landschaftsarchitektur arbeitet ortsbezogen (Grundstücke,
Flurstücke, Baustellen). Neben Kontakt/Projekt/Aufgabe sollte eine vierte
Entität **Örtlichkeit** erfasst werden können: `name` (Pflicht), `adresse` und
`flurnummer` (optional), verknüpfbar mit Kontakten und Projekten.

**Umgesetzt.**
- **Datenmodell** ([`models.py`](src/kollege/models.py)): `Ort` (DB-Modell:
  `id`, `name`, `adresse`, `flurnummer`, `created_at`, `updated_at`) +
  `ExtractedOrt` (LLM-Schema: `name`, `adresse`, `flurnummer`, plus `contact`/
  `project` zur Namensauflösung wie bei `ExtractedTask`) + `locations`-Feld in
  `ExtractionResult` (zählt in `is_empty()` mit). Verknüpfung wie in der
  Roadmap vorgezeichnet: `Project.ort_id`/`Contact.ort_id` (je höchstens ein
  Ort), kein n:m.
- **Repository** ([`db/repository.py`](src/kollege/db/repository.py)): neue
  `orte`-Tabelle (exact-name-Dedup wie Kontakte); `get_or_create_ort`,
  `get_ort_by_name`/`get_ort_by_id`, `list_orte` (alphabetisch, `/orte`),
  `get_all_orte` (Bekannte-Namen-Kontext), `link_contact_ort`/
  `link_project_ort`, `delete_ort` (löst Zuordnung in Kontakten/Projekten,
  kein Cascade — wie `delete_contact`). **Schema-Migration**: `_DDL_CONTACTS`/
  `_DDL_PROJECTS` bekommen `ort_id` für frische DBs; `_migrate_ort_columns`
  prüft `PRAGMA table_info` und fährt `ALTER TABLE … ADD COLUMN` nach, falls
  die Spalte auf einer bestehenden DB-Datei noch fehlt (SQLite kennt kein
  `ADD COLUMN IF NOT EXISTS`). `reset_all` räumt jetzt auch `orte` leer.
- **Extraktion** ([`agent/__init__.py`](src/kollege/agent/__init__.py)):
  neues Tool `link_ort` (Namens-Dedup + optionale Kontakt-/Projekt-
  Verknüpfung — Projekt wird bei Bedarf angelegt wie bei `create_task`,
  Kontakt nur bei bereits bestehendem Kontakt aufgelöst). System-Prompt und
  Lücken-Prüfungs-Prompt (`run_gap_check`) erwähnen Örtlichkeiten.
  `filter_known_names`/`build_known_names_context`/`get_known_names_context`
  auf eine Drei-Wege-Aufteilung (Kontakte/Projekte/Orte, je `max_names // 3`)
  umgestellt — **Breaking Change** an `filter_known_names`s Rückgabetyp
  (2-Tuple → 3-Tuple), bewusst in Kauf genommen; `build_known_names_context`
  bleibt rückwärtskompatibel (`ort_names` optional). `_format_result_for_prompt`
  zeigt Örtlichkeiten inkl. Adresse/Flurnummer/Kontakt-/Projekt-Referenz —
  sonst gälte für Revisions-/Lücken-Prüfungs-Läufe dieselbe Verlust-Gefahr wie
  bei Erledigungen/Änderungen vor dem 8.20-Fix. `_rebuild_from_repo`
  (Fallback-Pfad für kleinere Modelle ohne `final_result`-Tool) rekonstruiert
  Örtlichkeiten inkl. Kontakt-/Projekt-Referenz aus dem DB-Zustand.
- **Oberfläche** ([`orchestrator.py`](src/kollege/orchestrator.py)): neue
  `📍 Örtlichkeit: …`-Zeile in `_result_items` inkl. Neu-Markierung (analog
  8.25, jetzt auch für referenzierte Orte *und* über Örtlichkeiten referenzierte
  neue Projekte); `dedupe_result` dedupliziert Örtlichkeiten nach Namen;
  `persist_result` legt Örtlichkeiten an und verknüpft sie (nach Kontakten/
  Projekten, damit eine Verknüpfung auf einen im selben Vorschlag neu
  angelegten Kontakt/Projekt greift); `format_orte` + Kommando `/orte`;
  `/loeschen ort <id>` mit Bestätigung (gleicher Zwei-Schritt-Flow wie
  Kontakt/Projekt/Aufgabe); `/zuruecksetzen`-Vorschau und `reset_all` zählen
  Örtlichkeiten mit; `/hilfe` aktualisiert.
- **Qualität**: zwei neue Eval-Fixtures
  ([`06_garten_hinterberger_flurstueck.json`](tests/fixtures/eval/06_garten_hinterberger_flurstueck.json),
  [`07_streuobstwiese_berger_ohne_adresse.json`](tests/fixtures/eval/07_streuobstwiese_berger_ohne_adresse.json)
  — mit/ohne Adresse+Flurnummer, Projekt- bzw. Kontaktverknüpfung);
  `ExtractionExpectation`/`score_result` um `min_locations`/`max_locations`/
  `location_names` ergänzt (gleiches deklaratives Muster wie bestehende
  Felder); `runner.py` unverändert kompatibel (kennt nur `FixtureScore`).

**Bewusst nicht im Scope.** Geokodierung/Karten; Stufe-B-Bearbeitung von Orten
(Umbenennen/Merge, wie bei Kontakten erst bei realem Bedarf); n:m-Verknüpfungen
(FK reicht für ein Projekt/einen Kontakt an höchstens einem Ort).

**DoD.** ✅
- ✅ E2E-Test (gemockte `run_extraction`): Sprachnotiz mit Ort (Adresse +
  Flurnummer + neue Projektverknüpfung) → Vorschlag mit „— neu"-Markierung →
  Bestätigung → Ort und verknüpftes Projekt landen korrekt in der DB.
- ✅ Ort↔Projekt- und Ort↔Kontakt-Verknüpfung wird extrahiert (`link_ort`-Tool,
  `persist_result`) und ist via `/orte` abfragbar.
- ✅ Löschung mit Bestätigung (`/loeschen ort <id>`) funktioniert, referentielle
  Regel wie bei Kontakten (Zuordnung lösen, kein Cascade).
- ✅ Migrationstest: bestehende DB-Datei ohne `ort_id`-Spalte öffnet und
  funktioniert nach dem Upgrade weiter (idempotent bei erneutem Öffnen).
- ✅ Eval-Fixtures ergänzt (2 neue, CI-Modus grün).
- ✅ CI-Kette grün (`ruff`/`ruff format`/`mypy --strict`/`pytest`, 414 Tests).

---

### Schritt 8.27 — Proaktive Erinnerungen mit konfigurierbarem Zeitplan ✅

**Motiv.** Wert des Assistenten ist rechtzeitiges Erinnern (siehe „Grenzen &
bewusste Auslassungen" in ROADMAP.md) — letzter der drei Testphasen-Features
(8.25 → 8.26 → 8.27). Zwei Nachrichtentypen: kurzer Nachfrage-Ping („Gibt es
Neues?") und formatierte Liste aller offenen Aufgaben, Zeitplan frei
konfigurierbar (Wochentage + Uhrzeit je Regel) ohne Code anzufassen.

**Umgesetzt.**
- **Neues Modul** ([`reminders.py`](src/kollege/reminders.py)): `ReminderRule`
  (Pydantic: `typ` (`ping`/`liste`), `wochentage` (Kürzel `Mo`…`So`), `uhrzeit`)
  + `load_reminder_rules()` (stdlib `tomllib`, keine neue Dependency; fehlende
  Datei → leere Regelliste, kein Fehler) + `due_reminders()` (reine Logik,
  zeitmockbar). **Nachhol-Entscheidung** (Roadmap ließ offen: „gar nicht" vs.
  „höchstens jüngste"): `due_reminders` holt je Regel **höchstens die jüngste**
  verpasste Instanz nach (Suche bis zu 8 Tage zurück), nie mehrere gestapelt —
  robust gegen einen schlafenden Laptop, ohne bei langer Downtime eine Flut
  alter Erinnerungen nachzuliefern.
- **Scheduler-Entscheidung:** schlanker eigener Ticker statt `APScheduler` —
  `Orchestrator.check_reminders()` wird von `run_forever()` nach jedem
  Poll-Zyklus aufgerufen. Kriterium aus der Roadmap (Testbarkeit/Zeit mocken,
  keine Doppel-Sendung bei Neustart) war mit einer injizierbaren `now`-Zeit +
  Repository-Persistenz einfacher zu erfüllen als mit einer zusätzlichen
  Scheduler-Dependency; `APScheduler` bleibt für Schritt 11 vorgemerkt (dort
  kommt IMAP-Polling dazu, das eher zu einem echten Scheduler passt).
- **Zeitbasis bewusst lokale Wanduhrzeit** (naive `datetime`, keine TZ) statt
  des sonst im Projekt üblichen UTC — die Nutzerin denkt in „8 Uhr morgens" auf
  ihrem eigenen Laptop, nicht in UTC; eine TZ-Umrechnung wäre hier eher
  Fehlerquelle als Nutzen (Single-User, Single-Host).
- **Repository** ([`db/repository.py`](src/kollege/db/repository.py)): neue
  Tabelle `reminder_state(key, last_sent)` + `get_reminder_last_sent`/
  `set_reminder_last_sent` (Upsert) — Neustart-Sicherheit über die DB statt
  eine zusätzliche State-Datei, konsistent mit „SQLite ist Quelle der
  Wahrheit". Bewusst **nicht** Teil von `reset_all` (Scheduler-Zustand, keine
  Nutzerdaten).
- **Config** ([`config.py`](src/kollege/config.py)): `reminders_config_path`
  (Default `data/reminders.toml` — liegt unter dem gitignored `data/`, daher
  committetes Beispiel unter
  [`docs/reminders.example.toml`](docs/reminders.example.toml) zum Kopieren).
- **Orchestrator** ([`orchestrator.py`](src/kollege/orchestrator.py)):
  `check_reminders(now=None)` lädt die Konfig-Datei bei **jedem** Aufruf frisch
  (Zeitplan-Änderungen wirken ohne Neustart), liest/schreibt `last_sent` nur für
  tatsächlich fällige Regeln, sendet über den bestehenden Channel an
  `settings.signal_number` (Note-to-Self) und bricht früh ab, wenn
  `signal_number` leer oder keine Regeln geladen sind. Rührt `self._pending`/
  `self._pending_clarifications`/`self._pending_deletions` nirgends an — eine
  Erinnerung ist immer nur eine zusätzliche Nachricht. Neue Formatierung
  `format_reminder_list()` (anders als die knappe `format_open_tasks`) zeigt zu
  jeder Aufgabe Projekt-/Kontakt-/Ort-Bezug (Ort via `Project.ort_id` bzw.
  `Contact.ort_id`, Projekt hat Vorrang) und Fälligkeit; der Aufrufer sortiert
  via `repo.query_open_tasks(sort_by_due=True)` (überfällig zuerst).
  `run_forever()` ruft `check_reminders()` nach jedem `run_once()` auf, mit
  eigenem Try/Except (ein Fehler in der Erinnerungs-Prüfung darf den
  Dauerbetrieb nicht abbrechen — analog zur bestehenden Poll-Schleifen-Härtung).
- **Live-Betrieb** ([`scripts/run_signal.py`](scripts/run_signal.py)):
  Start-Banner zeigt an, ob eine Konfig-Datei gefunden wurde und wie viele
  Regeln geladen sind.
- **Doku:** neuer Abschnitt „f) Proaktive Erinnerungen konfigurieren" in
  [`docs/live-testing-guide.md`](docs/live-testing-guide.md) (§3f).

**Bewusst nicht im Scope.** Konfiguration per Chat-Command (Datei reicht in der
Testphase); IMAP-Polling (Schritt 11, dort auch `APScheduler`); „intelligente"
Auswahl, welche Aufgaben erinnert werden (schlicht alle offenen).

**DoD.** ✅
- ✅ Zeitplan-Konfig-Datei (`[[erinnerung]]`-Einträge, `typ`/`wochentage`/
  `uhrzeit`) mit committetem Beispiel + Doku.
- ✅ Deterministische Tests für die Auslöse-Logik (gemockte `now`, keine
  Doppel-Sendung fürs selbe Vorkommen, Neustart-sicher via zweitem
  Orchestrator auf demselben Repository, Nachhol-Logik "höchstens jüngste
  verpasste Instanz").
- ✅ Liste zeigt Projekt-/Kontakt-/Ort-Bezug + Fälligkeit (inkl. „(kein
  Datum)").
- ✅ Läuft im Dauerbetrieb (`run_forever` ruft `check_reminders` jeden Zyklus,
  eigenes Fehler-Containment).
- ✅ CI-Kette grün (`ruff`/`ruff format`/`mypy --strict`/`pytest`, 446 Tests).
