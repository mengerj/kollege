# Roadmap — Kollege

Arbeitsdokument zur kontinuierlichen Entwicklung. Jeder Schritt ist so
geschnitten, dass er in **einer Session** abgearbeitet werden kann, mit klarer
*Definition of Done* (DoD). Nach jedem Schritt: [PROJECT_LOG.md](PROJECT_LOG.md)
ergänzen und unten **NÄCHSTER SCHRITT** aktualisieren.

> Vorgehen pro Schritt: wo sinnvoll **test-driven** (erst Test, dann Code),
> alles muss `ruff`/`mypy`/`pytest` grün lassen. Details: [CLAUDE.md](CLAUDE.md).

---

## ▶ NÄCHSTER SCHRITT

**Schritt 8.22 — Löschen von Einträgen (Kontakte/Projekte/Aufgaben)** (siehe
Details/DoD weiter unten). Direkt aus dem Live-Test 2026-07-03: eine Lösch-Bitte
lief stumm ins Leere (keine Lösch-Funktion) — schnellster Vertrauensgewinn.
Danach naheliegend: **8.23** (Kontext-Deduplizierung/Token-Sparen, gleiche
Trace-Analyse) — **oder**, sobald wieder live getestet wird: **Schritt 8.5**
(restliche Live-Edge-Cases) mit der neuen Observability (8.21), inkl. Validierung
von 8.18/8.19 und dem 8.20-Szenario live. Danach: Stufe B für **Kontakte**
(Umbenennung + Merge).

> **DSGVO-konforme EU-LLM-Anbindung** ist nach **Schritt 9.1** verschoben (Phase 2)
> — aktuell nicht in naher Zukunft, `mistral-medium-3.1` trägt den Betrieb.

*Zuletzt erledigt: 8.21 (LLM-Traces + Verlaufs-Log). Was & warum steht im
[PROJECT_LOG.md](PROJECT_LOG.md); die Detail-DoD im
[ROADMAP_ARCHIV.md](ROADMAP_ARCHIV.md).*

> **Reihenfolge-Regel bestätigt (Nutzerin):** neue Nachricht = neue Notiz;
> Korrektur/Antwort **nur** über die Zitat-Antwort-Funktion. Slash-Commands auf
> Deutsch.
>
> **IMAP/E-Mail (Schritt 9 ff.) zurückgestellt**, bis Phase 1.5 rund läuft.
> Schritt 8.5 (restliche Live-Edge-Cases) läuft parallel weiter, sobald wieder
> live mit der Nutzerin getestet wird.

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
| 8.13 | Rückfrage-Antwort-Schleife + robuste 👍/👎-Erkennung | 1.5 | ✅ erledigt |
| 8.14 | Vollständige Historie pro Pending-Proposal | 1.5 | ✅ erledigt |
| 8.15 | Query-Funktionen + deutsche Slash-Commands | 1.5 | ✅ erledigt |
| 8.16 | Projekt-Markdown-Logs füllen (append_entry verdrahten) | 1.5 | ✅ erledigt |
| 8.17 | Erledigungen aus Freitext erkennen & abgleichen | 1.5 | ✅ erledigt |
| 8.18 | Zwei-Durchgang-Extraktion + deutsche Datumsanzeige | 1.5 | ✅ erledigt |
| 8.19 | Bestehende Aufgaben bearbeiten (Stufe B, nur Aufgaben) | 1.5 | ✅ erledigt |
| 8.20 | Korrektur-Lauf: Erledigungen bleiben erhalten (Bugfix) | 1.5 | ✅ erledigt |
| 8.21 | Live-Debugging-Observability (LLM-Traces + Verlaufs-Log) | 1.5 | ✅ erledigt |
| 8.22 | Löschen von Einträgen (Kontakte/Projekte/Aufgaben) | 1.5 | ▶ nächster Schritt |
| 8.23 | Kontext-Deduplizierung + Gap-Check-Gating (Token-Sparen) | 1.5 | ⬜ offen |
| 9 | IMAP read-only (t-online) | 2 | 🅿️ zurückgestellt bis Phase 1.5 (Branch liegt) |
| 9.1 | DSGVO-konforme EU-LLM-Anbieter evaluieren & anbinden | 2 | 🅿️ verschoben (war 8.12) |
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

*Abgeschlossen. Detail-Begründungen & DoD: [ROADMAP_ARCHIV.md](ROADMAP_ARCHIV.md).*

## Phase 1 — Sprachnotiz-Kern (MVP)

*Abgeschlossen. Detail-Begründungen & DoD: [ROADMAP_ARCHIV.md](ROADMAP_ARCHIV.md).*

*Ziel der Phase: Sie spricht eine Notiz ein und bekommt strukturierte,
bestätigte Aufgaben/Kontakte zurück. Läuft komplett lokal auf dem Air.*

## Phase 1.5 — Verflüssigung des Sprachnotiz-Kerns *(vor Phase 2)*

> **Erledigte Schritte dieser Phase** (8.6, 8.7, 8.9–8.11, 8.13–8.21) stehen
> mit voller Begründung/DoD im [ROADMAP_ARCHIV.md](ROADMAP_ARCHIV.md); hier nur
> noch die **offenen** Schritte.

*Ziel der Phase: Der bestehende Kern (Sprachnotiz → Vorschlag → Bestätigung → DB)
soll sich im Alltag **flüssig, schnell genug und vertrauenswürdig** anfühlen.
Maßstab ist nicht „mehr Features", sondern **freiwillige Weiternutzung**
(Designprinzip 6). Erst danach kommt E-Mail (Phase 2).*

### Schritt 8.5 — Signal-Live-Betrieb + Härtung ⏳
Echter Bot verknüpft, §6-Backlog umgesetzt und live verifiziert (👍-Reaktion,
Absturz-Resistenz, Logging, Audio-E2E, Dedup, „(kein Datum)"). Verbleibend: restliche
Edge-Cases (Guide §4) live gegenprüfen.
**DoD:** Edge-Case-Tabelle (Guide §4) reproduzierbar grün im Alltag.

### Schritt 8.8 — Sofort-Quittung / gefühlte Reaktionszeit ⬜
Cold-Start + Whisper + LLM erzeugen spürbare Latenz; ohne Rückmeldung wirkt das wie
„nichts passiert" (live so erlebt). Eine **knappe Sofort-Bestätigung** beim Eingang
(z. B. „🎤 hab ich, ich verarbeite das kurz …") nimmt die Unsicherheit, bevor der
eigentliche Vorschlag kommt. Optional: Hinweis bei ungewöhnlich langem Lauf.
**DoD:** Jede eingehende Notiz wird binnen ~1 s quittiert; der Vorschlag folgt wie
gehabt. Kein Doppel-Senden mehr aus Ungeduld.

### Schritt 8.22 — Löschen von Einträgen (Kontakte/Projekte/Aufgaben) ⬜

**Motiv (aus Live-Test 2026-07-03, Trace `data/traces/2026-07-03.jsonl`).** Die
Nutzerin bat *„Lösche alle gespeicherten Kontakte und Projekte"*. Das Modell
stellte korrekt eine Rückfrage (destruktive Aktion), auf *„Alles. Das waren bis
jetzt nur Tests"* lief der `clarification_response`-Lauf aber ins **Leere**: ein
komplett leeres `ExtractionResult`, **keine Aktion, keine Rückmeldung**. Ursache:
Es existiert **keine Lösch-Funktion** — weder ein Repository-Verb noch ein
Command noch ein Tool. Das `ExtractionResult`-Schema kann „Löschen" gar nicht
ausdrücken, also verschwindet die Absicht kommentarlos. Das ist ein
Vertrauensbruch (Prinzip 3/6): die Nutzerin denkt, etwas sei passiert.

**Designentscheidung — deterministisch per Slash-Command, nicht über die
LLM-Extraktion.** Löschen ist destruktiv und selten; es gehört **nicht** in den
probabilistischen Extraktionspfad (Über-/Fehl-Löschung wäre fatal). Konsistent zu
[Schritt 8.15](#schritt-815--query-funktionen--deutsche-slash-commands-) (Queries
= deterministische Commands ohne LLM-Entscheidungsdruck):

- **Repository (rein, TDD-fähig):** `delete_contact(id)`, `delete_project(id)`,
  `delete_task(id)` und — für die Testdaten-Situation — `reset_all()` (löscht
  Kontakte + Projekte + Aufgaben). Referentielle Konsequenzen bewusst festlegen
  (Aufgaben eines gelöschten Projekts: mitlöschen vs. Projektbezug lösen).
- **Deutsche Commands:** `/loeschen kontakt <id>`, `/loeschen projekt <id>`,
  `/loeschen aufgabe <id>` und `/zuruecksetzen` (alles) — im bestehenden
  Dispatcher am Anfang von `handle_message`.
- **Zwei-Schritt-Bestätigung (Prinzip 3):** destruktive Commands zeigen erst, was
  gelöscht wird (Anzahl + Titel/Namen) und verlangen ein **explizites 👍/„ja"**,
  bevor gelöscht wird — nutzt die vorhandene Pending-Mechanik. Nie ohne
  Bestätigung löschen.
- **Der Extraktionspfad bleibt löschfrei, wird aber gesprächsfähig:** Erkennt das
  Modell eine Lösch-/„weg damit"-Absicht, soll es **nicht** leer zurückkommen,
  sondern per `clarification` auf den passenden Command hinweisen (z. B. „Zum
  Löschen nutze bitte `/loeschen …` oder `/zuruecksetzen`"). Damit endet keine
  Lösch-Absicht mehr stumm.

**DoD.** Repository-Löschverben test-driven (In-Memory-SQLite, referentielle
Regeln geprüft); Commands im Dispatcher mit Zwei-Schritt-Bestätigung getestet;
eine Lösch-formulierte Notiz endet nicht mehr leer, sondern verweist auf den
Command; `/hilfe` listet die neuen Commands; CI-Kette grün.

### Schritt 8.23 — Kontext-Deduplizierung + Gap-Check-Gating (Token-Sparen) ⬜

**Motiv (Trace-Analyse 2026-07-03).** Die neuen LLM-Traces machen sichtbar, wo
Kontext doppelt gesendet wird und Tokens unnötig verbraucht werden. Beobachtungen
aus `data/traces/2026-07-03.jsonl`:

1. **Gap-Check verdoppelt den Prompt-Kontext.** Der zweite Durchgang
   (`run_gap_check`) sendet den **kompletten** `[BEKANNTE NAMEN]`- **und**
   `[OFFENE AUFGABEN]`-Block erneut (via `known_names_context`/`open_tasks_context`)
   **und** listet im „Erster Extraktions-Vorschlag"-Teil dieselben Aufgaben mit
   vollem Titel + Frist noch einmal auf. Im Trace: Extraktion 3107 → Gap-Check
   **3662** Input-Tokens, und das Ergebnis war **identisch** (`output ==`). Für
   *jede* Notiz läuft damit ein zweiter, teurer LLM-Call.
2. **Doppelte Instruktionen.** Die `completed`/`edits`-Anweisung steht **einmal
   ausführlich im System-Prompt** und **erneut kondensiert** im
   `[OFFENE AUFGABEN]`-User-Block; die `clarification`-Anweisung steht im
   System-Prompt, im `[BEKANNTE NAMEN]`-Block und im `[OFFENE AUFGABEN]`-Block.
3. **Aufgaben-Titel als Volltext doppelt** im Gap-Check (Kontextblock + Vorschlag).
4. **Gap-Check läuft bedingungslos bei *jeder* Notiz** (in
   [`_extract`](src/kollege/orchestrator.py) direkt nach dem ersten Durchgang, nur
   bei `first.clarification` übersprungen). Der zweite LLM-Call ist damit ein
   **fester Verdopplungsfaktor** auf Latenz *und* Tokens der Erstextraktion —
   unabhängig davon, ob es überhaupt Lücken zu füllen gibt. Im Trace war das
   Ergebnis byte-identisch (`output ==`), d. h. der komplette zweite Call war reine
   Verschwendung.
5. **Trace-Format speichert den Prompt doppelt** (kein LLM-Token, aber Disk /
   schnelleres Wachstum der Trace-Dateien): der Prompt-Text steht sowohl in
   `llm_run_start.payload.prompt` als auch nochmal in
   `llm_run_result.payload.messages` (dort als `user-prompt`-Part). Eines von
   beiden reicht — z. B. in `llm_run_result` nur noch die *neuen* Nachrichten seit
   `llm_run_start` ablegen oder den redundanten `prompt` in `llm_run_start` weglassen.

**Ansatz (Umfang im Schritt festzurren, messen mit Traces vorher/nachher).**
- **Gap-Check gaten statt immer laufen lassen:** zweiten Durchgang nur auslösen,
  wenn das Erstergebnis **plausible Lücken** hat (z. B. Aufgabe ohne Datum/Projekt,
  oder nicht-leeres Ergebnis) — bei einer reinen Erledigungs-Notiz wie im Trace
  bringt er nichts. Alternativ/Minimal: Gap-Check nur, wenn `first`-Ergebnis nicht
  leer ist (spart den ganzen zweiten Call bei „nichts erkannt"/reinen Erledigungen).
- **Kontext im Gap-Check abspecken:** im „Erster Vorschlag" nur **IDs/Kurzform**
  statt Volltitel wiederholen (die Titel stehen bereits im `[OFFENE AUFGABEN]`-
  Block), oder den `[OFFENE AUFGABEN]`-Block im zweiten Durchgang weglassen, wenn
  er im ersten schon war.
- **Instruktionen entdoppeln:** eine Quelle der Wahrheit — Detailregeln im
  System-Prompt, die Kontextblöcke nur noch **Daten** (Namen/Aufgabenliste) ohne
  wiederholte Handlungsanweisung.
- **Trace-Redundanz beheben** (Punkt 5) — kleiner, isolierter Cleanup in
  [`trace.py`](src/kollege/trace.py)/[`agent/__init__.py`](src/kollege/agent/__init__.py);
  Viewer [`scripts/show_trace.py`](scripts/show_trace.py) entsprechend anpassen.

**Bewusst kein Blindflug.** Token-Sparen darf die in 8.11/8.18 gemessene Qualität
nicht verschlechtern → **Benchmark (8.11) vor/nach** fahren (`pass_rate`,
`empty_rate`, `over_extraction_rate`), damit klar ist, dass nur Redundanz
wegfällt, keine Wirkung. Das Gap-Check-Gating ist der Punkt mit dem höchsten
Risiko für die Qualität (8.18 war genau dafür da) → hier besonders sorgfältig messen.

**DoD.** Gap-Check läuft nur noch bei tatsächlichem Bedarf (Gating getestet);
Kontext-Redundanz im Gap-Check-/System-Prompt messbar reduziert (Trace-Vergleich
Input-Tokens vorher/nachher dokumentiert); Trace speichert den Prompt nicht mehr
doppelt (Viewer weiterhin funktionsfähig); Benchmark zeigt **keine** Qualitäts-
Regression; CI-Kette grün.

---

## Phase 2 — E-Mail & Übersicht *(zurückgestellt bis Phase 1.5 rund läuft)*

*Ziel: Der Assistent beantwortet „bei wem muss ich mich melden?".*

> **Bewusst zurückgestellt.** Erst wenn sich der Sprachnotiz-Kern im Alltag flüssig
> anfühlt (Phase 1.5), wird E-Mail angegangen. Der Schritt-9-Branch ist begonnen,
> liegt aber; die Reihenfolge wird danach neu bewertet.

### Schritt 9.1 — DSGVO-konforme EU-LLM-Anbieter evaluieren & anbinden ⬜

*(War Schritt 8.12; am 2026-07-03 nach Phase 2 verschoben — aktuell nicht in
naher Zukunft, `mistral-medium-3.1` trägt den Betrieb ausreichend. Reihenfolge
innerhalb Phase 2 später bewerten.)*

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
      → Anbieter-Evaluierung in **Schritt 9.1** (war 8.12; Mistral/Aleph Alpha/Bedrock-EU;
      OpenRouter als US-Intermediär bewusst **kein** DSGVO-Fundament).
- [ ] KI-Transparenz: Assistent gibt sich als KI zu erkennen (sobald Dritte interagieren).
- [ ] Gemeinde-Daten (öffentliche Stellen) besonders sensibel.
- [ ] Transportverschlüsselung überall (IMAP SSL, HTTPS).

## Bewusst zurückgestellt

- **WhatsApp** — Meta verbietet seit 15.01.2026 universelle KI-Chatbots; Business-API
  bräuchte dedizierte Nummer. Signal ersetzt WhatsApp als Assistenz-Kanal.
