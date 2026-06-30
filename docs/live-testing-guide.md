# Leitfaden: Live-Test & Monitoring (Phase 1)

> **Zweck dieses Dokuments.** Es ist die Einweisung für eine KI-Session, deren
> Auftrag **nicht** das Abarbeiten eines neuen Roadmap-Schritts ist, sondern:
> den laufenden Signal-Bot **beobachten**, **DB-Einträge verifizieren**,
> **Edge-Cases live durchspielen** und den Code entsprechend **nachschärfen** —
> bis Phase 1 (Sprachnotiz-Kern) rund läuft. Erst danach geht es mit
> **Schritt 9 (IMAP)** weiter.
>
> Lies zuerst [CLAUDE.md](../CLAUDE.md) (Designprinzipien) und
> [docs/signal-setup.md](signal-setup.md) (Setup/Verknüpfung). Dieses Dokument
> ist die Brücke vom „läuft technisch" zum „läuft im Alltag".

---

## 1. Mentales Modell der Live-Kette

```
Signal (Notiz an mich)
   └─ signal-cli-rest-api (Docker, json-rpc, WebSocket /v1/receive)
        └─ SignalChannel.receive()           # persistente WS-Verbindung, drain pro Poll
             └─ Orchestrator.run_forever()    # Poll-Schleife (1s)
                  ├─ Transcriber (nur bei Audio: faster-whisper, lokal)
                  ├─ Agent.run_extraction()   # Ollama qwen2.5:7b → Tools → ExtractionResult
                  ├─ format_proposal() → Channel.send()   # Vorschlag zurück nach Signal
                  └─ nach „ja"/Auswahl: persist_result() → SQLite (data/kollege.db)
```

Drei Verantwortlichkeiten (siehe CLAUDE.md): **Ohr** (`channels/`), **Gehirn**
(`agent/`), **Gedächtnis** (`db/` + `data/projects/*.md`). Verdrahtung:
[`orchestrator.py`](../src/kollege/orchestrator.py), Live-Start:
[`scripts/run_signal.py`](../scripts/run_signal.py).

---

## 2. Hochfahren (Reihenfolge wichtig)

```bash
# 1. Docker-Container (Signal-Bridge)
docker compose up -d
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8080/v1/health   # erwartet: 204
curl -s http://localhost:8080/v1/accounts                                   # erwartet: ["+49…"]

# 2. Ollama mit tool-fähigem Modell
curl -s http://localhost:11434/api/tags | python3 -m json.tool | grep name  # qwen2.5:7b-instruct?

# 3. Bot starten — IMMER unbuffered, sonst sieht man nichts im Log
PYTHONUNBUFFERED=1 uv run python -u scripts/run_signal.py
```

`scripts/run_signal.py` prüft Health, Verknüpfung und Config vorab und bricht mit
klarer Meldung ab, wenn etwas fehlt. „✓ Bereit. Lausche …" = es läuft.

**Im Hintergrund laufen lassen + Log mitschneiden** (so kann die Session den Bot
beobachten, ohne die Konsole zu blockieren):

```bash
PYTHONUNBUFFERED=1 nohup uv run python -u scripts/run_signal.py > kollege.log 2>&1 &
tail -f kollege.log
```

---

## 3. Monitoring-Werkzeuge

### a) Läuft der Bot? Stürzt er ab?

```bash
pgrep -fl run_signal.py            # Prozess da?
tail -n 40 kollege.log             # Startbanner + evtl. Traceback
```

> ⚠ **Wichtig:** `run_forever()` hat **kein** Error-Handling. Eine unbehandelte
> Exception (z. B. Ollama-Timeout, Netzfehler) **beendet den Bot**. Dann steht im
> Log ein Traceback und `pgrep` liefert nichts. Das ist eine der ersten Sachen,
> die gehärtet werden sollten (siehe §6).

### b) Kommen Nachrichten überhaupt an? (rohe Envelopes)

Der Orchestrator loggt eingehende Nachrichten **nicht** — man ist sonst blind.
Zum Mitschneiden der rohen WebSocket-Pakete:

```bash
# Bot vorher stoppen, sonst teilen sich zwei Empfänger die Nachrichten!
pkill -f run_signal.py
uv run python scripts/signal_debug_receive.py 30   # lauscht 30 s, gibt jedes Paket aus
```

Damit sieht man die **Envelope-Struktur** (entscheidend, siehe §5) und ob eine
Nachricht als `syncMessage.sentMessage` (Note-to-Self), `dataMessage` (fremd),
`reaction`, `receiptMessage` usw. ankommt.

### c) Wurde etwas gespeichert? (DB inspizieren)

```bash
uv run python -c "
import sqlite3
c=sqlite3.connect('data/kollege.db'); c.row_factory=sqlite3.Row
for t in ('contacts','projects','tasks'):
    rows=c.execute(f'SELECT * FROM {t}').fetchall()
    print(f'=== {t} ({len(rows)}) ===')
    for r in rows: print('  ', dict(r))
"
```

**Merke:** Die DB wird **erst nach Bestätigung** („ja"/👍-Text/„1 3") beschrieben.
Ein gesendeter Vorschlag steht nur im Arbeitsspeicher (`PendingProposal`), nicht
in der DB. Leere DB nach einem Vorschlag ist also normal, solange nicht bestätigt
wurde.

### d) Container-Sicht

```bash
docker compose logs -f signal-cli-rest-api
```

Ein gesundes Empfangsmuster ist **eine** lang offene `GET /v1/receive/…`-Zeile.
Viele kurze `GET …`-Zeilen im Sekundentakt = die alte Batch-Verbindung (Bug,
siehe §5) — sollte nicht mehr vorkommen.

---

## 4. Edge-Cases zum Live-Durchspielen

Schicke jeweils eine **Notiz an mich** und prüfe Vorschlag + (nach „ja") DB:

| Kategorie | Beispiel-Notiz | Worauf achten |
|---|---|---|
| Einfacher Task | „Morgen Tom anrufen." | due = morgen (ISO), 1 Task, kein Doppel |
| Relatives Datum | „Nächsten Freitag Angebot rausschicken." | korrektes ISO-Datum, Jahr stimmt |
| Explizites Datum | „Am 07.07 Sabine anrufen." | nächstes zukünftiges Vorkommen, Jahr stimmt |
| Kontakt + Projekt | „Herr Schneider, Projekt Naturpark, wartet auf Genehmigung." | Kontakt, Projekt-Status, waiting_on |
| Mehrere Tasks | „Pflanzliste fertig, dann Müller anrufen." | werden sie sinnvoll getrennt? Duplikate? |
| Unklar | „Das Ding wegen der Sache." | `clarification` statt geraten? |
| Auswahl | Vorschlag mit mehreren Punkten → Antwort „1 3" | nur 1 und 3 gespeichert |
| Ablehnen | Vorschlag → „nein" | nichts gespeichert, „Verworfen" |
| Sprachnachricht | kurze Audio-Notiz | Whisper-Transkript plausibel (1. Mal lädt ~1,5 GB) |
| Reaktion 👍 | Tapback statt Text | **funktioniert NICHT** (siehe §5/§6) |

Nach jedem „ja" mit der DB-Abfrage (§3c) gegenprüfen, **dass genau das Erwartete**
gespeichert wurde — Titel, `due`, `contact_id`, `project_id`, `status`.

---

## 5. Was diese Session über die Live-Kette gelernt hat (Stolpersteine)

Diese Punkte haben in der ersten Live-Inbetriebnahme jeweils Zeit gekostet — sie
sind bereits **gefixt**, aber gut zu kennen, weil ähnliche Klassen von Fehlern
wieder auftauchen werden:

1. **Health-Check liefert `204 No Content` mit leerem Body** — nicht
   `{"status":"ok"}`. `curl …/v1/health` „zeigt nichts" = gesund. Mit
   `-w '%{http_code}'` prüfen.

2. **Note-to-Self ≠ `dataMessage`.** Kollege ist ein *verknüpftes Gerät* am
   eigenen Konto. Eigene Notizen kommen als **`syncMessage.sentMessage`** mit
   `destination == eigene Nummer` an. Nachrichten *anderer* Personen
   (`dataMessage`) werden **bewusst ignoriert** (Datensparsamkeit, Nutzerwunsch).
   → [`signal_channel.py`](../src/kollege/channels/signal_channel.py)
   `_parse_envelope`.

3. **Persistente WebSocket-Verbindung ist Pflicht.** Im `json-rpc`-Modus streamt
   signal-cli Nachrichten in Echtzeit und **spielt sie nicht erneut ab**. Die
   ursprüngliche „pro Aufruf verbinden/trennen"-Logik verlor jede Nachricht, die
   in einer Verbindungslücke eintraf (Symptom: Bot läuft, reagiert aber nie). Fix:
   Verbindung wird einmal geöffnet und zwischen Polls offen gehalten.

4. **SQLite-Thread-Safety.** Pydantic-AI führt Agent-Tools **nebenläufig in
   Worker-Threads** aus, die sich *eine* `sqlite3.Connection` teilen. Ohne
   Serialisierung: `InterfaceError: bad parameter or other API misuse`,
   `OperationalError: cannot commit`, oder `AssertionError` — **nicht-deterministisch**
   (mal geht's, mal nicht; im Trockenlauf mit MemoryChannel fiel es nicht auf).
   Fix: reentranter Lock pro Repository (`@_synchronized`).
   ⚠ Verwandter Fallstrick: `run_extraction` fing `sqlite3.DatabaseError`, aber
   `InterfaceError` ist ein **Geschwister**, kein Subtyp → wurde nicht gefangen.

5. **Das LLM kennt das heutige Datum nicht.** „morgen"/„07.07" wurden relativ zum
   Trainingsstand (~Okt 2023) aufgelöst. Fix: dynamischer System-Prompt
   (`@agent.system_prompt`) injiziert das aktuelle Datum + Wochentag.

6. **Tapback-Reaktion ≠ Textnachricht.** Ein 👍 als Signal-*Reaktion* kommt als
   eigenes `reaction`-Envelope (kein `message`-Text) — der Bestätigungs-Regex
   (`_YES`) greift nur auf **Text** „ja"/„👍". Reaktionen werden derzeit
   **ignoriert**. (Noch offen, siehe §6.)

7. **Beobachtbarkeit ist dünn.** Der Orchestrator loggt weder Empfang noch
   Verarbeitung. Beim Debuggen ist `scripts/signal_debug_receive.py` (rohe
   Envelopes) + DB-Abfrage der schnellste Weg zur Wahrheit. Mehr Logging im
   Orchestrator wäre eine sinnvolle erste Härtung.

8. **Modellqualität (qwen2.5:7b).** Neigt zu **Über-Extraktion**: zerlegt einen
   Satz in mehrere überlappende Tasks, dupliziert, lässt `due` mal weg. Kein
   Code-Bug — Human-in-the-loop fängt es ab (Auswahl „1 3"). Jetzt zusätzlich von
   `dedupe_result` abgefedert (§6.5).

9. **Signal-Audio kommt als AAC/MP4, nicht (mehr) OGG.** Neuere Clients senden
   `audio/aac`; `_download_attachment` leitet die Endung aus dem contentType ab.
   Funktional unkritisch (faster-whisper erkennt das Format am Inhalt), aber fürs
   Debuggen relevant.

10. **Modell `ornith:9b` (Erfahrung 2026-06-30).** Tool-fähig, Extraktion korrekt
    (Datum, Verknüpfung, keine Über-Extraktion). Aber:
    - **Braucht Ollama > 0.30.8** (sonst 412 beim Pull). Server war die
      Ollama.app (0.30.8) → via Homebrew auf 0.30.11.
    - **Cold-Start ist der Engpass, nicht „Thinking".** Warm: 16 tok/s, 100 % GPU,
      passt in VRAM. Bei RAM-Druck (~1 GB frei) entlädt Ollama das Modell zwischen
      Nachrichten → Reload ~3 Min (verschärft, wenn Whisper gleichzeitig lädt).
    - **`think:false` wirkungslos** — ornith hat intrinsisches Reasoning
      (Coding-Modell, raw `{{ .Prompt }}`-Template); der Ollama-Flag unterdrückt es
      nicht. Bei RAM-Engpass ist `qwen2.5:7b-instruct` der leichtere Fallback.

---

## 6. Bekannte Lücken / Härtungs-Kandidaten (Backlog für diese Test-Phase)

> **Stand 2026-06-30: alle sechs Punkte umgesetzt** (Branch `feat/phase1-haertung`,
> 131 Tests grün, live verifiziert). Hier als Doku belassen.

1. ✅ **Reaktions-Bestätigung (👍 als Tapback).** `_parse_envelope` liest jetzt
   das `reaction`-Feld in `syncMessage.sentMessage` (`emoji`, `isRemove`);
   `IncomingMessage.is_reaction`. Der Orchestrator wertet 👍 auf einen offenen
   Vorschlag als „ja", andere/leere Reaktionen werden ignoriert. **Live
   bestätigt.** (Teilauswahl „1 3" bleibt vorerst Text-only.)

2. ✅ **`run_forever()`/`run_once()` gehärtet.** try/except pro Nachricht: Fehler
   wird geloggt, der Absender bekommt eine knappe Meldung, der Bot läuft weiter.
   Die Poll-Schleife selbst fängt ebenfalls Fehler ab.

3. ✅ **Logging im Orchestrator.** Eingang (Absender, Typ Text/Audio/Reaktion),
   Extraktion (Anzahl / clarification), Persistenz, Fehler — datensparsam (keine
   Inhalte). `run_signal.py` setzt `logging.basicConfig`.

4. ✅ **Vorschlag zeigt `due` immer an** — auch „(kein Datum)".

5. ✅ **Über-Extraktion eindämmen.** `dedupe_result` entdoppelt vor dem Vorschlag
   (Kontakte per Name, Tasks per Titel+Datum, Updates per Projekt); System-Prompt
   zusätzlich geschärft.

6. ✅ **Sprachnachrichten end-to-end verifiziert** (echte Audio-Notiz → Whisper →
   Vorschlag). Hinweis: erstes Audio lädt `faster-whisper-medium` (~4 Min einmalig).

---

## 7. Code-Änderungen während der Test-Phase

- Auf einem **Feature-Branch** arbeiten (nie direkt `main`), kleine Commits.
- Vor jedem Commit die volle Kette grün halten:

  ```bash
  uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
  ```

- Für deterministische Logik (Parsing, DB, Envelope-Typen) **erst Test, dann
  Code**. LLM-Aufrufe nicht im CI — `TestModel`/`FunctionModel` nutzen.
- Den Bot nach Code-Änderungen **neu starten** (er lädt Module beim Start; ein
  laufender Prozess sieht Änderungen nicht).
- Relevante Erkenntnisse hier (§5/§6) und im [PROJECT_LOG.md](../PROJECT_LOG.md)
  ergänzen.

---

## 8. Definition of Done für „Phase 1 läuft rund"

- [ ] Text-Notiz → Vorschlag → „ja"/Auswahl → korrekter DB-Eintrag (Titel, Datum,
      Verknüpfungen) — reproduzierbar über die Edge-Case-Tabelle (§4).
- [ ] 👍-Reaktion bestätigt zuverlässig.
- [ ] Bot überlebt einen Verarbeitungsfehler, ohne abzustürzen.
- [ ] Sprachnachricht wird korrekt transkribiert und verarbeitet.
- [ ] Datumsauflösung stimmt über mehrere Formulierungen.

Erst wenn das steht: weiter mit **Schritt 9 (IMAP)** laut [ROADMAP.md](../ROADMAP.md).
