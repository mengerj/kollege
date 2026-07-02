# Projekt-Log — Kollege

Chronologisches Log der Arbeit. Neuester Eintrag oben. Pro Session ergänzen
(siehe Ritual in [CLAUDE.md](CLAUDE.md)).

---

## 2026-07-02 — Schritt 8.15 — Query-Funktionen + deutsche Slash-Commands

**Ziel:** DB-Stand deterministisch abfragen können — ohne LLM, schnell, zuverlässig
(nimmt dem Modell Entscheidungsdruck, siehe Planungs-Eintrag 8.14–8.17 weiter unten).

**Getan:**
- [`repository.py`](src/kollege/db/repository.py): `query_open_tasks(sort_by_due=True)`
  (überfällige/nächste Fristen zuerst, kein Datum ans Ende; `sort_by_due=False` =
  Einfügereihenfolge für `/offen`), `list_contacts()`/`list_projects()` (alphabetisch
  sortiert — bewusst getrennt von `get_all_contacts()`/`get_all_projects()`, die
  weiterhin unsortiert für die interne Tool-Only-Rekonstruktion dienen), und
  `mark_task_done(task_id)` als dünner Wrapper um `update_task_status`.
- [`orchestrator.py`](src/kollege/orchestrator.py): fester **Dispatcher** am Anfang von
  `handle_message` — `Reaktion? → Slash-Command? → offener Vorschlag/Rückfrage? →
  sonst neue Notiz`. Ein Kommando wird **immer sofort** ausgeführt und lässt einen
  etwaig offenen Vorschlag/eine offene Rückfrage unangetastet (reiner Seitenkanal,
  keine Interferenz mit dem Bestätigungs-Loop).
- Kommandos: `/offen`, `/dringend`, `/kontakte`, `/projekte`, `/erledigt <id>`,
  `/hilfe`. Antworten als knappe ID-beschriftete Listen (`format_open_tasks`,
  `format_contacts`, `format_projects`) — IDs sind der Handle für `/erledigt`.
  Unbekanntes Kommando und `/erledigt` ohne/mit ungültiger ID → freundlicher
  Hinweis + Kommandoübersicht statt Absturz oder stiller Ignoranz.

**Tests:** 21 neue Tests in [`test_db.py`](tests/test_db.py) (Sortierlogik,
alphabetische Listen, `mark_task_done` inkl. unbekannter ID) und
[`test_orchestrator.py`](tests/test_orchestrator.py) (jedes Kommando einzeln,
Groß-/Kleinschreibung, Priorität vor offenem Vorschlag/offener Rückfrage,
Regression „normale Notiz ohne Slash bleibt Extraktion"). Gesamt grün:
249 passed (1 deselected: `eval`-Marker, real-LLM). Ruff + mypy sauber.

**Nächster Schritt:** **8.16** — Projekt-Markdown-Logs füllen (`append_entry`
verdrahten).

---

## 2026-07-02 — Schritt 8.14 — Vollständige Historie pro Pending-Proposal

**Auslöser:** siehe Planungs-Eintrag weiter unten (selber Tag). Der Live-Fall: eine
Zitat-Korrektur *„…Telefonnummer wie in der letzten Nachricht"* lief ins Leere, weil
`run_revision`/`run_clarification_response` nur (Ursprungstranskript + aktueller
Vorschlag + ein Korrekturtext) sahen — der Rohtext einer *vorherigen* Korrektur-
Runde derselben Interaktion ging beim Übergang zur nächsten Runde verloren.

**Getan:**
- `PendingProposal` und `PendingClarification` ([`orchestrator.py`](src/kollege/orchestrator.py))
  bekommen ein Feld `history: list[tuple[str, str]]` — (Label, Text)-Paare aller
  vorangegangenen Turns *dieser* Interaktion (Rückfrage/Antwort/Korrektur), in
  Reihenfolge, ohne das Ursprungstranskript (bleibt in `.transcript`) und ohne den
  aktuellen Turn (der wird weiterhin über die bestehenden Parameter übergeben).
- `run_revision()`/`run_clarification_response()` ([`agent/__init__.py`](src/kollege/agent/__init__.py))
  bekommen ein neues optionales `history`-Argument und stellen einen formatierten
  Historie-Block dem Prompt voran (`_format_history`), zusätzlich zum bisherigen
  Ursprungstranskript/aktuellen Vorschlag/aktueller Korrektur.
- Verdrahtung in `_revise()` und `_answer_clarification()`: history wird bei jedem
  Übergang (Korrektur→Korrektur, Rückfrage→Antwort→Vorschlag, Rückfrage→Antwort→
  neue Rückfrage) fortgeschrieben und an den jeweils nächsten Lauf weitergereicht.
- **Scope-Grenze eingehalten:** history lebt ausschließlich am Pending-Objekt im
  Arbeitsspeicher und wird bei Bestätigung/Ablehnung mit diesem verworfen — kein
  senderweites Dauergedächtnis, keine Cross-Notiz-Referenzen.

**Tests:** FunctionModel-Test (`test_run_revision_uses_history_to_resolve_earlier_reference`)
zeigt konkret: dieselbe Korrektur liefert ohne `history` keinen Telefonwert, mit
`history` (die frühere Korrektur-Nachricht mit der Nummer) liefert sie ihn korrekt —
belegt, dass die History der entscheidende Kanal ist. Dazu Prompt-Komposition-Tests
für beide Agent-Funktionen und Orchestrator-Tests für Akkumulation über mehrere
Korrektur-/Rückfrage-Runden hinweg (inkl. Übergang Rückfrage→Vorschlag→Korrektur).
Gesamt grün: 224 passed. Ruff + mypy sauber.

**Nächster Schritt:** **8.15** — Query-Funktionen + deutsche Slash-Commands.

---

## 2026-07-02 — Planung: Nutzbarkeits-Block 8.14–8.17 (aus Live-Test)

**Auslöser:** Live-Test mit `mistral3.1-medium` (via OpenRouter). Der Extraktions-
kern trägt, aber für den Alltag fehlt Nutzbarkeit. Diese Session war reine
**Planung + kritisches Feedback** (kein Code) — Ergebnis in ROADMAP als Block
8.14–8.17 festgehalten, abzuarbeiten **vor** der E-Mail-Integration (Schritt 9).

**Befunde aus dem Live-Log (korrigierte Diagnose):**
- Eine Zitat-Korrektur *„…Telefonnummer einspeichern (wie in der letzten
  Nachricht)"* wurde **korrekt** als `_revise` geroutet — meine erste Vermutung
  („Freitext ohne Zitat wird nicht als Korrektur erkannt") war **falsch**. Die
  echte Ursache: `run_revision`/`run_clarification_response` haben **kein
  Gedächtnis über die Turns einer Interaktion** (nur Ursprungstranskript +
  aktueller Vorschlag + ein Korrekturtext). Die referenzierte Nummer stand in einer
  früheren Notiz → kein Referent → Kontakt kam ohne Nummer zurück. → **Schritt 8.14**.
- `data/projects/kräutergarten-aibling-1.md` ist der Projekt-Markdown-Log, aber
  `ProjectLog.append_entry()` wird **nirgends** aufgerufen — Logs bleiben leer
  (nur Header). Feature ist halb verdrahtet. → **Schritt 8.16** (füllen, Prinzip 4).
- Es fehlt jeder **Lesepfad** (offene/dringende Aufgaben, Kontakte, Projekte) und
  jede Möglichkeit, Aufgaben zu **schließen** → offene Liste würde monoton wachsen.
  → **Schritt 8.15** (deterministische deutsche Slash-Commands, kein LLM).

**Entscheidungen der Nutzerin:**
- Beim Modell bleiben: *neue Nachricht = neue Notiz*; Korrektur/Antwort **nur**
  über die Zitat-Antwort-Funktion (kein Freitext-ohne-Zitat als Korrektur).
- Gedächtnis (8.14): **vollständige Historie einer Interaktion** genügt, kein
  senderweites Dauergedächtnis.
- Erledigtes muss auch aus **Freitext** erkannt werden („Tagesrückblick") und gegen
  offene Aufgaben abgeglichen werden → **Schritt 8.17**. Der Dispatcher routet das
  als normale Notiz; die „getan vs. zu tun"-Logik sitzt in der Extraktion.
  Erkennung + Abgleich in **einem** Lauf (Variante A).
- Slash-Commands auf **Deutsch**.

**Reihenfolge:** 8.14 → 8.15 → 8.16 → 8.17. Schritt 8.12 (EU-LLM-Anbieter) bleibt
offen, aber hinter diesem Block zurückgestellt (OpenRouter reicht zum Testen).

**Nächster Schritt:** 8.14 umsetzen (Details + DoD in [ROADMAP.md](ROADMAP.md)).

---

## 2026-07-01 — Schritt 8.13 — Rückfrage-Antwort-Schleife + robuste 👍/👎-Erkennung

**Auslöser:** Live-Test. Der Bot stellte eine Rückfrage (*„Soll der Kontakt
›Kräutergarten Aibling‹ als neuer Dienstleister angelegt werden? Aktuell ist nur
›Kindergarten Bad Aibling‹ bekannt."*). Ein 👍 darauf wurde ignoriert, ein „ja"
als neue (leere) Notiz behandelt.

**Diagnose:** Eine `clarification` war eine **Sackgasse** — der Orchestrator sendete
die Frage und kehrte zurück, **ohne** Pending-Zustand. Folge: `pending=False`, also
konnte weder Tapback noch Text als Antwort andocken. Sekundär: die 👍-Erkennung
verglich exakt gegen `👍` und wäre an Hautton-/Variation-Selector-Varianten zerbrochen.

**Getan:**
- Neuer Zustand `PendingClarification` (Ursprungstranskript + gestellte Frage);
  Invariante „genau ein offener Zustand pro Absender" (Vorschlag *oder* Rückfrage).
- Nächste Nachricht (Freitext / Sprache / 👍) → `run_clarification_response()`
  re-extrahiert mit Ursprungstranskript + Frage + Antwort (analog Revisions-Schleife 8.6).
  Konkretes Ergebnis → normaler Bestätigungs-Loop; weiter unklar → erneute Rückfrage;
  „nein"/👎 → verwerfen ohne LLM-Lauf.
- 👍/👎-Erkennung gehärtet: Basis-Codepoint-Vergleich (Modifier/Selektoren entfernt),
  `👍`/`👌`/`✅` = ja, `👎`/`❌`/`🚫` = nein — gilt auch für Vorschläge.
- Nebenbei: README um „Bot starten (Live-Betrieb)" + Schnelldiagnose ergänzt
  (`docker compose up` startet nur die Signal-Bridge, nicht den Bot-Prozess selbst).

**Tests:** +13 Orchestrator-Tests (Emoji-Varianten, 👎-Reject, komplette
Rückfrage-Antwort-Schleife inkl. erneuter Rückfrage) + 1 Agent-Test (Prompt-Komposition).
Gesamt grün: 213 passed. Ruff + mypy sauber.

**Offen / bewusst ausgelassen:** TTL für offene Rückfragen; Zusammenführen mehrerer
offener Zustände. Nächster regulärer Schritt bleibt **8.12** (EU-LLM-Anbieter).

---

## 2026-07-01 — Schritt 8.11 — Modell-Benchmark-System (Extraktion + Revision)

**Auslöser:** Live-Debugging desselben Tages — eine triviale Rechtschreibkorrektur
(„Es heißt Aibling, nicht Eibling") lief nicht-deterministisch ins Leere, reproduzierbar
bei `ornith:9b` **und** `qwen2.5:7b-instruct`. Das bestehende Eval-Set (8.10) konnte das
nicht sichtbar machen (Einzel-Lauf, nur `min_*`, kein Revisions-Pfad).

**Getan:**

### Eval-Paket `src/kollege/eval/` (Single Source of Truth)
- `fixtures.py` — Pydantic-Schema + Laden für beide Fixture-Familien (Extraktion +
  neu: Revision). Alle neuen Keys optional, abwärtskompatibel.
- `scoring.py` — deklarativer Scorer: `expected` → `FixtureScore` (hits/total + Flags
  `empty`, `over_extraction`, `forbidden_hit`).
- `runner.py` — `run_fixture_n_times()`: N Wiederholungen + Aggregation
  (`pass_rate`, `mean_score`, `empty_rate`, `over_extraction_rate`, `error_rate`,
  Latenz-Median). Optionales `max_workers` für parallele Wiederholungen bei
  netzwerkgebundenen Cloud-Providern.
- `tests/test_eval_scoring.py` — 24 deterministische Unit-Tests (kein LLM).

### Fixture-Schema erweitert
- Extraktion: `max_contacts/max_tasks/max_project_updates` (Über-Extraktion),
  `forbidden_keywords`, `must_not_be_empty`. Bestehende 5 Fixtures ergänzt.
- **`04_schneider_angebot.json` entfernt** — near-duplicate zu `01_wagner_pflanzplan`
  (beide „Kontakt + ein Task + Frist"), kein zusätzliches Signal fürs teure Benchmarking.
- **Neu: `tests/fixtures/eval_revision/`** — zwei Fixtures: der Aibling-Fall
  (`forbidden_keywords: ["Eibling"]`, `must_not_be_empty: true`) und ein
  Namenskorrektur-Fall (Schnitt→Schmidt, Motiv aus 8.6/8.7).

### Benchmark-CLI `scripts/benchmark_models.py`
- `--models` (Syntax `provider:modell`, Default-Provider `ollama`), `--runs`,
  `--suite extraction,revision`, `--out`, `--threshold`, `--concurrency`.
- Nutzt exakt den Produktions-Pfad (`run_extraction`/`run_revision`).
- Terminal-Vergleichs-Matrix + Markdown-Historie nach `benchmarks/results/`.
- **`--concurrency N`** parallelisiert Wiederholungen über Threads — nur für
  Nicht-Ollama-Provider wirksam (bei `ollama` erzwungen seriell: ein lokaler
  GPU-Server profitiert nicht von parallelen Anfragen).

### Neuer Provider: OpenRouter
- `LLMProvider.OPENROUTER` in `config.py` (+ `openrouter_base_url`/`openrouter_api_key`),
  `build_model()`-Zweig (OpenAI-kompatibel). Bewusst **kein** Produktions-Fundament
  (US-Intermediär, kein EU-AVV) — nur für die synthetische Benchmark-Entdeckungsphase,
  siehe 8.12.

### Dokumentation
- `docs/benchmark.md` — Motiv (vier Fehlerklassen), Architektur, Fixture-Wachstumspfad,
  Modell-Registrierung, Befehle, Ergebnis-Interpretation, Kosten-Hinweis (warum ein
  Benchmark-Lauf viele Modell-Aufrufe braucht: N Reps × Fixtures × Primär-/Fallback-Retries).
- Querverweis aus `docs/live-testing-guide.md` §5 auf den Aibling-Fall.

### Baseline eingecheckt
- Ursprünglich lokal (`ornith:9b` vs. `qwen2.5:7b-instruct`) gestartet, aber abgebrochen —
  auf einer GPU seriell und mit den bekannten Primär-Pfad-Retries pro Lauf zu teuer für eine
  schnelle Session-Baseline (5 Fixtures × 2 Suiten × 5 Runs × 2 Modelle, dazu bei `ornith`
  fast immer ein gescheiterter Primär-Versuch **vor** dem eigentlichen Fallback-Versuch).
  Stattdessen fünf **OpenRouter**-Modelle verglichen (netzwerkgebunden, mit
  `--concurrency` parallelisierbar, synthetische Fixtures → datenschutzrechtlich
  unkritisch): `mistral-medium-3-5`, `mistral-medium-3`, `mistral-small-2603`,
  `qwen-2.5-7b-instruct`, `glm-4.5-air`. In `benchmarks/results/` eingecheckt.
  - `mistral-medium-3-5`: 100 % pass_rate auf beiden Suiten, niedrigste Latenz (2–4 s median).
  - `mistral-medium-3`: 100 %/100 % pass_rate, etwas langsamer.
  - `glm-4.5-air`: 65 % pass_rate Extraktion (hohe `error_rate`, keine leeren/über-extrahierten
    Ergebnisse wenn erfolgreich), 100 % Revision.
  - `mistral-small-2603`: 55 % pass_rate Extraktion, 40 % `empty_rate` — zu schwach.
  - `qwen-2.5-7b-instruct` (über OpenRouter): 0 % — 100 % `error_rate` auf allen Fixtures,
    vermutlich ein Endpoint-/Formatierungsproblem bei diesem Modell auf OpenRouter (nicht
    weiter untersucht, außerhalb des Scopes dieses Schritts).
  - Der lokale ornith/qwen-Vergleich aus dem Live-Vorfall bleibt mit demselben Befehl
    (`--models ornith:9b,qwen2.5:7b-instruct`) jederzeit nachvollziehbar; die CLI wurde
    dagegen einzeln smoke-getestet (echter Ollama-Aufruf, korrekte Matrix/Markdown-Ausgabe).

### Tests
- **199 Tests grün** (vorher 198; +24 neue Scoring/Runner-Unit-Tests, +1 Revisions-Eval-Test
  über das neue Fixture-Set, −1 durch entfernte `schneider_angebot`-Fixture, +1 Build-Model-Test
  für OpenRouter). `ruff`/`mypy --strict`/`pytest` grün.

**Entscheidungen:**
- **Kein CI-Gate gegen echte Modelle** — Benchmark bleibt manuell (`scripts/benchmark_models.py`,
  `pytest -m eval --real-llm`), wie bei 8.10.
- **`--concurrency` nur für Cloud-Provider** — lokales Ollama läuft immer seriell, weil eine
  GPU ohnehin nur eine Anfrage gleichzeitig verarbeitet; Parallelität würde dort nur um
  dieselbe Ressource konkurrieren statt Zeit zu sparen.
- **Fixture-Set bewusst schlank gehalten** — ein Duplikat entfernt statt ergänzt, weil jeder
  zusätzliche Fixture die Benchmark-Kosten (N × Modelle) linear erhöht, ohne bei Redundanz
  zusätzliches Signal zu liefern.

**Offene Punkte:**
- Der lokale `ornith:9b`-vs-`qwen2.5:7b-instruct`-Vollständigkeits-Lauf (ursprünglich in der
  DoD als Baseline vorgesehen) wurde nicht zu Ende gefahren — bei Bedarf jederzeit mit
  `uv run python scripts/benchmark_models.py --models ornith:9b,qwen2.5:7b-instruct --runs 5`
  nachholbar.
- Warum `qwen-2.5-7b-instruct` über OpenRouter komplett fehlschlägt, ist ungeklärt.

---

## 2026-07-01 — Schritt 8.10 — Eval-Set für Extraktionsqualität (automatische Session)

**Ziel:** Kleines Fixture-Set aus Beispiel-Transkripten → erwartete Felder,
damit Modell-/Prompt-Wechsel messbar werden und Regressionen in
Dedup/Datumsauflösung/Vokabular-Bias frühzeitig auffallen.

**Getan:**

### Fixture-Dateien
- **5 JSON-Fixtures** in [`tests/fixtures/eval/`](tests/fixtures/eval/):
  1. `01_wagner_pflanzplan.json` — Privatkundin + Task + Projektbezug + Frist
  2. `02_stadtpark_gemeinde.json` — Projektstatus-Update, Gemeinde als Wartegrund
  3. `03_gartenprofi_anruf.json` — Dienstleister-Kontakt + konkreter Anruf-Task
  4. `04_schneider_angebot.json` — Kontakt mit Projektreferenz + termingebundener Task
  5. `05_zwei_aufgaben.json` — Zwei klar getrennte Aufgaben, zwei Kontakte
- Jedes Fixture: `{ id, description, transcript, expected: { min_contacts, contact_names, min_tasks, task_keywords, min_project_updates, project_names } }`

### Eval-Testmodul
- **[`tests/test_eval.py`](tests/test_eval.py)**: Parametrisierte Tests mit `@pytest.mark.eval`.
  - **CI-Modus (Standard):** `FunctionModel`-Mock gibt erwartetes Ergebnis zurück.
    Prüft Schema-Konformität und Mindest-Counts. Schnell, kein Netz, kein LLM.
  - **Real-LLM-Modus** (`pytest -m eval --real-llm`): Echter `run_extraction()`-Aufruf.
    `_score_result()` berechnet Trefferquote (Hits/Gesamt) über Mindestanzahlen und
    Schlüsselwort-Teilstrings (case-insensitive). Schwellenwert: 50 %.
    Detailliertes Print-Output zeigt extrahierte Kontakte/Tasks/Projekte pro Fixture.
- **`_score_result(result, expected) → (int, int)`**: Schwellenwert-Scoring statt
  striktem Equality-Assert — trägt LLM-Nichtdeterminismus Rechnung.

### conftest.py
- **[`tests/conftest.py`](tests/conftest.py)**: `--real-llm`-Option via `pytest_addoption`
  + `real_llm`-Fixture (bool), das in `test_eval.py` per Injection übergeben wird.

### Aufräumen
- Eval-Abschnitt aus [`tests/test_agent.py`](tests/test_agent.py) entfernt
  (wurde durch das neue `test_eval.py` ersetzt; `test_agent.py` bleibt auf
  Agent-Struktur-/Tool-Tests fokussiert).
- `eval`-Marker in [`pyproject.toml`](pyproject.toml) registriert.

### Tests
- **5 neue Eval-Tests** (`test_eval_extraction[…]`, parametrisiert) ersetzten 3 alte.
- **175 Tests grün**, ruff + mypy-strict sauber.

**Befehle:**
```bash
# CI-Modus (in Standard-Run enthalten):
uv run pytest -m eval

# Real-LLM-Modus (Trefferquote):
uv run pytest -m eval --real-llm -s
```

**Entscheidungen:**
- **Eval-Tests laufen in CI (kein Ausschluss aus `addopts`):** Die FunctionModel-Mocks
  validieren Pipeline und Schema auch ohne LLM — sinnvoller als stilles Überspringen.
- **Schwellenwert 50 %:** Konservativ genug für kleinere lokale Modelle (qwen2.5:7b,
  ornith:9b), aber erkennt grobe Regressionen zuverlässig. Anpassbar über
  `_QUALITY_THRESHOLD` in `test_eval.py`.
- **Teilstring-Match (case-insensitive):** Verhindert False Negatives bei Formulierungen
  wie „Frau Gartenprofi GmbH anrufen" vs. erwartetem Keyword „Gartenprofi".

**Offene Punkte / nächste Schritte:**
- Eval gegen echte Modelle (`ornith:9b`, `qwen2.5:7b`) manual laufen lassen und
  Trefferquoten dokumentieren (erster Messwert-Baseline).
- Schritt 8.10 abgeschlossen. Nächster Schritt: je nach Alltags-Feedback Schritt 8.5
  (Edge-Cases live) oder Phase 2 (IMAP, Schritt 9).

---

## 2026-07-01 — Schritt 8.9 — Robuster Dauerbetrieb (automatische Session)

**Ziel:** Den Bot unbeaufsichtigt und stabil laufen lassen: Auto-Restart,
Cold-Start abfedern, Fehlertoleranz bei transientem Ausfall von Ollama/Container,
Nachrichten-Verlust bei Verbindungslücke klären.

**Getan:**

### Pre-Warm Ollama-Modell beim Start
- **`pre_warm_model(settings: Settings) -> None`** in [`src/kollege/agent/__init__.py`](src/kollege/agent/__init__.py):
  Sendet einen leeren POST an `/api/generate` der nativen Ollama-API, damit das
  Modell beim Starten des Dienstes in den VRAM geladen wird — bevor die erste
  Sprachnotiz eintrifft. Scheitert das Vorladen (Ollama noch nicht bereit), wird
  nur gewarnt; der Bot startet trotzdem.
- `scripts/run_signal.py` ruft `pre_warm_model(settings)` jetzt zwischen den
  Vorab-Prüfungen und `run_forever()` auf.

### Retry bei transienten Fehlern
- **`_EXTRACTION_RETRIES = 3`** und **`_EXTRACTION_RETRY_DELAY = 10.0 s`** in
  [`src/kollege/orchestrator.py`](src/kollege/orchestrator.py): konstante Werte für Wiederholungen.
- **`Orchestrator._extract()`**: schlägt die Extraktion fehl (z. B. Ollama gerade
  nicht erreichbar nach RAM-Druck), wird sie bis zu dreimal wiederholt. Zwischen
  den Versuchen `retry_delay` Sekunden warten. Auf Ebene der Tests auf `0.0`
  setzbar über neuen `Orchestrator`-Parameter `retry_delay`.
- Frische `tmp_repo`-Verbindung pro Versuch verhindert Dopple-Schreibungen aus
  einem halb-abgearbeiteten Versuch.
- Sind alle Versuche erschöpft, propagiert die Exception zu `run_once()`, das die
  Fehlermeldung an den Absender sendet — wie bisher.

### launchd-Service für macOS
- **[`deploy/de.mengerj.kollege.plist`](deploy/de.mengerj.kollege.plist)**:
  launchd User Agent (macOS). Konfiguriert `KeepAlive = true` (Auto-Restart bei
  Absturz), `ThrottleInterval = 60 s` (Mindestabstand zwischen Neustarts),
  gemeinsame Log-Datei für stdout+stderr, korrekte PATH-Variable für `uv` und
  Homebrew-Tools. Mit Kommentaren für Installation, Starten/Stoppen und
  Deinstallation.

### Nachrichten-Verlust bei Verbindungslücke — Analyse
Kein eigenes Ack-Protokoll nötig:
- **WebSocket-Lücke** (Bot läuft, Connection bricht kurz): signal-cli puffert die
  Nachrichten im Arbeitsspeicher; bei Reconnect werden sie nachgeliefert.
- **signal-cli-Neustart** (Docker-Container neu): signal-cli verbindet sich mit
  dem Signal-Server neu und holt unquittierte Nachrichten ab (Signal hält
  Nachrichten für verknüpfte Geräte ~30 Tage).
- **Bot-Absturz/-Neustart**: launchd startet den Bot neu (≤ ThrottleInterval);
  bis zum Neustart gepufferte Nachrichten werden danach ausgeliefert.
- Einziges stilles Verlust-Risiko: Container **und** Bot beide offline **ohne je
  zu reconnecten** — unrealistisch im täglichen Betrieb. Dokumentiert in
  `scripts/run_signal.py`.

### Tests
- **9 neue Tests** in [`tests/test_dauerbetrieb.py`](tests/test_dauerbetrieb.py):
  - `pre_warm_model`: korrekte URL-Bildung (mit `/v1`-Strip), Cloud-Provider
    überspringen, graceful Fallback bei Connection Error und HTTP Error.
  - Retry-Logik: 2 Fehler → 3. Versuch erfolgreich; alle Versuche erschöpft →
    Exception; erster Versuch erfolgreich → kein Retry; `run_once()` fängt
    erschöpfte Retries und sendet Fehlermeldung.
- **173 Tests grün**, ruff + mypy-strict sauber.

**Entscheidungen:**
- **Retry in `_extract()`, nicht in `run_extraction()`:** Die Retry-Logik gehört
  in den Orchestrator, weil er den Channel (für Ack) kennt und den Kontext
  (Transcript, offene Proposals) hat. `run_extraction()` bleibt zustandslos.
- **`ThrottleInterval = 60 s`:** Kompromiss zwischen schnellem Neustart nach
  Ollama-Restart (~30 s) und Schutz vor Restart-Schleifen.
- **Kein eigenes Ack-Protokoll:** signal-cli's Puffer + Signal-Server-Queuing
  reichen aus; zusätzlicher Mechanismus wäre Over-Engineering.
- **Pre-Warm nur für Ollama:** Cloud-Provider (Anthropic, OpenAI) haben kein
  Cold-Start-Problem.

**Offene Punkte / nächste Schritte:**
- Schritt 8.10 — Eval-Set für Extraktionsqualität.
- Live-Test des launchd-Dienstes (manuell, erfordert `cp deploy/…plist ~/Library/LaunchAgents/`).
- Optional: Log-Rotation für `kollege.log` (z. B. via `newsyslog` oder `logrotate`).

---

## 2026-06-30 — Schritt 8.7 — Bekannte Namen abgleichen (LLM-seitig, automatische Session)

**Ziel:** Bekannte Kontakt- und Projektnamen aus der DB dem Agenten als Kontext
mitgeben, damit Whisper-Verhörer (z. B. „Herr Schnitt" → „Schmidt") schon bei
der Extraktion erkannt und normalisiert werden — ohne den Revisions-Schritt
bemühen zu müssen.

**Getan:**

- **`filter_known_names(contacts, projects, max_names=80)`**: Filtert bekannte
  Kontakt- und Projektnamen aus DB-Einträgen vor. Sortiert nach `updated_at`
  absteigend (kürzlich aktiv zuerst), begrenzt auf `max_names // 2` je Kategorie.
  Verhindert Kontext-Überschwemmung bei wachsender DB.
- **`build_known_names_context(contact_names, project_names)`**: Formatiert die
  gefilterten Namen als `[BEKANNTE NAMEN …]`-Block mit Normalisierungsanweisung an
  das LLM. Gibt leeren String zurück, wenn beide Listen leer sind.
- **`get_known_names_context(repo, max_names=80)`**: Kombiniert beide Funktionen —
  liest aus dem Repository und liefert den fertigen Kontext-String.
- **`run_extraction(..., known_names_context: str | None = None)`**: Neuer optionaler
  Parameter. Wenn nicht leer, wird der Kontext-Block dem Transkript mit `[NOTIZ]`-
  Separator vorangestellt, bevor der Agent aufgerufen wird. Primär- und Fallback-Pfad
  verwenden denselben augmentierten Text.
- **`run_revision(..., known_names_context: str | None = None)`**: Parameter
  durchgereicht an `run_extraction()`, damit auch der Korrektur-Lauf (Schritt 8.6)
  die bekannten Namen kennt.
- **`Orchestrator._extract()`**: Ruft nun `get_known_names_context(self._repo)` auf
  und übergibt den Kontext an `run_extraction()`. Das echte Repo wird gelesen, der
  Agent arbeitet weiterhin auf dem temporären In-Memory-Repo.
- **`Orchestrator._revise()`**: Analog — `get_known_names_context(self._repo)`
  und Weitergabe an `run_revision()`.
- **16 neue Tests** in [`tests/test_known_names.py`](tests/test_known_names.py):
  - `filter_known_names`: leere Liste, Untergrenze, Max-Limit, Sortierreihenfolge.
  - `build_known_names_context`: leer, nur Kontakte, nur Projekte, beides, Normalisierungshinweis.
  - `get_known_names_context`: leeres Repo, Repo mit Daten.
  - `run_extraction`: ohne Kontext, mit Kontext (Prompt-Injektion prüfen via FunctionModel),
    leerer Kontext (kein Wrapper).
  - Orchestrator-Integration: bekannter Kontakt landet im `known_names_context`-Argument;
    leeres Repo → kein Kontext.
- **164 Tests grün**, ruff + mypy-strict sauber.

**Entscheidungen:**
- **Prompt-Injektion statt Tool:** Bekannte Namen als Präambel des Transkripts, nicht als
  separates `lookup_known_names()`-Tool. Einfacher, kein zusätzlicher Tool-Aufruf nötig,
  das LLM kann die Liste direkt beim Lesen des Transkripts nutzen.
- **Max 80 Namen (40 Kontakte + 40 Projekte):** Reicht für den Alltag; bei Wachstum
  der DB werden die kürzlich aktiven priorisiert. Der Wert ist konfigurierbar über
  `max_names`-Parameter.
- **Leerer Kontext → kein Wrapper:** Wenn das Repo leer ist (Erstbetrieb), bleibt das
  Transkript exakt wie bisher — kein struktureller Overhead für leere Listen.
- **DSGVO:** Namen verlassen das Gerät nicht (Ollama lokal). Der Block heißt explizit
  „nur zur Normalisierung, nicht als neue Einträge extrahieren" — verhindert, dass das
  LLM DB-Namen als neue Tasks interpretiert.

**Offene Punkte / nächste Schritte:**
- Schritt 8.9 — Robuster Dauerbetrieb (launchd, Warm-Start, Verlust-Schutz).
- Schritt 8.10 — Eval-Set für Extraktionsqualität.
- Live-Verifikation des Namensabgleichs (erst wenn „Herr Schnitt" / ähnliches im
  Alltag auftaucht).

---

## 2026-06-30 — Schritt 8.6 — Korrektur-/Revisions-Schleife via Quote-Reply (automatische Session)

**Ziel:** Zitat-Antwort (Signal Quote-Reply) auf den Vorschlag löst einen
Revisions-Lauf aus statt eine neue Extraktion — kein Neu-Einsprechen nötig.

**Getan:**

- **`IncomingMessage.quote_target_timestamp`** (neues Feld, `int | None`):
  Trägert den `quote.id`-Wert aus dem Signal-Envelope, wenn die Nachricht
  eine Zitat-Antwort ist.
- **`Channel.send()` gibt `int | None` zurück**: signal-cli liefert bei
  `/v2/send` den Sende-Timestamp; der wird ab jetzt zurückgegeben und in
  `PendingProposal.sent_timestamp` gespeichert (Vorbereitung für Stufe B).
  `MemoryChannel` gibt `None` zurück (kein Netz).
- **`SignalChannel._http_send()`**: parst die JSON-Response und gibt
  `timestamp` zurück; `_parse_envelope()` extrahiert `sentMessage.quote.id`
  in `IncomingMessage.quote_target_timestamp`.
- **`PendingProposal.sent_timestamp`** (neues Feld): speichert den
  Timestamp der Vorschlags-Nachricht.
- **`run_revision()` im Agent-Layer** (`agent/__init__.py`): Thin-Wrapper,
  der Ursprungstranskript + aktuellen Vorschlag + Korrekturtext zu einem
  kombinierten Prompt zusammensetzt und `run_extraction()` aufruft —
  vollständiger Primär-/Fallback-Pfad wird wiederverwendet.
- **`Orchestrator._revise()`**: sendet Sofort-Quittung
  (`✏️ Korrektur erhalten …` / `🎤 Sprachkorrektur …`), transkribiert ggf.
  Audio, ruft `run_revision()` auf, aktualisiert `PendingProposal`.
- **`Orchestrator.handle_message()`**: neue Quote-Reply-Erkennung vor dem
  Normal-Ablauf (Stufe A: jede Zitat-Antwort bei offenem Vorschlag = Korrektur,
  da pro Absender maximal ein Vorschlag offen ist).
- **11 neue Tests**: Quote-Parsing in `_parse_envelope`, `send()` gibt
  Timestamp zurück, Revisions-Lauf, Audio-Korrektur, Bestätigung nach
  Revision, `sent_timestamp` in `PendingProposal`. Alle 148 Tests grün.
  ruff + mypy-strict sauber.

**Entscheidungen:**
- Minimal-Matching (Stufe A): jede Quote-Reply bei offenem Vorschlag = Korrektur.
  Kein Timestamp-Matching nötig, weil pro Absender nur ein Vorschlag offen ist.
  Timestamp wird trotzdem gespeichert (Stufe B vorbereitet).
- `run_revision()` nutzt denselben `run_extraction()`-Pfad mit kombiniertem Prompt —
  kein zweites Agent-Objekt, keine doppelte Fallback-Logik.
- YES-Text in einer Quote-Reply (z. B. zitiert + „ja") wird als Bestätigung
  gewertet (der YES-Check kommt vor dem Quote-Check).
- Audio-Korrektur (zitiert + Sprachnachricht): `_get_transcript()` wird aufgerufen,
  dann wie Text-Korrektur weiterverarbeitet.

**Offene Punkte / nächste Schritte:**
- Schritt 8.7 — Bekannte Namen aus DB als LLM-Kontext mitgeben.
- Schritt 8.9 — Robuster Dauerbetrieb (launchd, Warm-Start, Verlust-Schutz).
- Stufe B (Korrektur bereits persistierter Einträge via Zitat-Antwort auf
  Bestätigungs-Nachricht) — bewusst zurückgestellt.

---

## 2026-06-30 — Schritt 8.8 — Sofort-Quittung (automatische Session)

**Ziel:** Jede eingehende Notiz wird binnen ~1 s quittiert; der Vorschlag folgt
wie gehabt. Damit wird die Cold-Start-Latenz (Whisper + LLM) nicht mehr als
„nichts passiert" wahrgenommen.

**Getan:**
- **Sofort-Quittung in `Orchestrator.handle_message()`:** Unmittelbar nachdem
  erkannt wurde, dass es sich um eine neue Notiz (nicht um eine
  Bestätigungsantwort oder Reaktion) handelt, wird eine knappe Quittung gesendet
  — bevor `_get_transcript()` oder `_extract()` aufgerufen werden:
  - Sprachnachricht (Audio + Transcriber vorhanden): `"🎤 Sprachnotiz erhalten, ich verarbeite das kurz …"`
  - Textnachricht: `"📝 Notiz erhalten, ich verarbeite das kurz …"`
  - Audio ohne Transcriber: keine Quittung (Nachricht wird still verworfen, wie bisher).
- **Tests:** 6 neue Tests für das Sofort-Quittungs-Verhalten
  (`test_ack_is_first_message_for_text_note`, `test_ack_contains_audio_emoji_for_voice_note`,
  `test_no_ack_for_confirmation_ja`, `test_no_ack_for_confirmation_nein`,
  `test_no_ack_for_tapback_reaction`, `test_no_ack_for_audio_without_transcriber`);
  bestehende Tests angepasst (sent-Indizes, Anzahl-Checks).
- **CI grün:** 137 Tests, ruff + mypy-strict sauber.

**Entscheidungen:**
- Quittung erfolgt synchron vor der Slow-Path-Verarbeitung — kein zweiter Thread,
  kein Async nötig, da der Orchestrator ohnehin blockierend ist.
- Distinkte Emoji-Präfixe (🎤 vs. 📝) helfen beim Unterscheiden im Signal-Chat.
- Keine Quittung für Audio ohne Transcriber: eine Quittung ohne nachfolgende
  Antwort wäre schlechter als stilles Verwerfen.

**Offene Punkte / nächste Schritte:**
- Schritt 8.6 — Korrektur-/Revisions-Schleife via Signal-Quote-Reply.
- Schritt 8.7 — Bekannte Namen aus DB als LLM-Kontext.
- Restliche Edge-Cases (§4 des Live-Testing-Guide) weiter live prüfen.

---

## 2026-06-30 — Phase-1-Härtung + Live-Test mit ornith:9b

Zweite Live-Session gemäß [docs/live-testing-guide.md](docs/live-testing-guide.md):
den §6-Härtungs-Backlog umgesetzt, alles live durchgespielt, und einen
Modellwechsel auf `ornith:9b` getestet.

**Getan (Härtung §6):**
- **`run_forever`/`run_once` robust:** Fehler pro Nachricht werden geloggt, der
  Absender bekommt eine knappe Meldung, der Bot läuft weiter statt abzustürzen.
  Auch die Empfangs-/Poll-Schleife fängt Fehler ab. (§6.2)
- **Logging im Orchestrator:** Eingang (Absender/Typ), Extraktionsergebnis
  (Anzahl/Rückfrage), Persistenz, Fehler — datensparsam (keine Inhalte).
  `run_signal.py` konfiguriert `logging.basicConfig`. (§6.3)
- **`format_proposal` zeigt `due` immer** an, auch „(kein Datum)". (§6.4)
- **`dedupe_result`** entdoppelt über-extrahierte Einträge vor dem Vorschlag;
  System-Prompt Richtung „wenige, klar getrennte Tasks" geschärft. (§6.5)
- **👍-Tapback als Bestätigung:** `SignalChannel` parst das `reaction`-Feld,
  `IncomingMessage.is_reaction`, Orchestrator wertet 👍 auf offenen Vorschlag als
  „ja". **Live verifiziert** (Log: `Eingang … (Reaktion) → Persistiert`). (§6.1)
- **Audio-Anhang-Endung:** neuere Signal-Clients senden AAC/MP4 statt OGG;
  `_download_attachment` leitet die Endung aus dem contentType ab.

**Live verifiziert (Definition of Done §8):**
- Text-Notiz → Vorschlag → Bestätigung → korrekter DB-Eintrag (Kontakt+Task,
  Datum, Verknüpfung). ✓
- 👍-Reaktion bestätigt zuverlässig. ✓
- Sprachnachricht → Whisper-Transkript → Vorschlag (erstes Audio lädt
  `faster-whisper-medium`, ~4 Min einmalig). ✓
- Datumsauflösung „morgen"/„übermorgen" korrekt. ✓

**Modell `ornith:9b` (Erkenntnisse):**
- Tool-fähig, Extraktion korrekt (Datum, Verknüpfung, **keine** Über-Extraktion).
- **Ollama-Update nötig:** ornith:9b verlangt > 0.30.8; Server (Ollama.app) lief
  auf 0.30.8 → via Homebrew auf **0.30.11** gehoben, App-Server gestoppt, brew
  `ollama serve` gestartet. (Nach Reboot kommt die Ollama.app zurück — ggf. App
  selbst updaten.)
- **Speed-Diagnose:** warm 16 tok/s, 100 % GPU, passt in VRAM (5,3 GB) — flott.
  Die langen Wartezeiten (~3–8 Min) sind **Cold-Starts**: bei RAM-Druck (~1 GB
  frei) entlädt Ollama das Modell zwischen Nachrichten, der Reload dauert ~3 Min
  (verschärft, wenn Whisper gleichzeitig lädt).
- **`think:false` wirkungslos:** ornith ist ein Coding-Modell mit intrinsischem
  Reasoning (raw `{{ .Prompt }}`-Template); der Ollama-Think-Flag unterdrückt es
  nicht (Prompt-Instruktion senkt es nur ~40 %). Thinking ist ohnehin nicht der
  Engpass. Entscheidung: **so lassen** (Korrektheit top, erste Nachricht geduldig
  abwarten), kein Speed-Code.

**Offen / Notiz:** RAM ist die eigentliche Grenze für ornith:9b auf diesem Laptop;
bei Instabilität Fallback `qwen2.5:7b-instruct` (Dedup fängt dessen Über-Extraktion
ab). Reaktions-Confirm für Auswahl (nur 👍 = „alles") — Teilauswahl weiter per Text.

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
