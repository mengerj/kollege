# Signal-Kanal einrichten (signal-cli-rest-api)

Kollege verbindet sich über
[signal-cli-rest-api](https://github.com/bbernhard/signal-cli-rest-api) mit Signal.
Der Container läuft lokal auf dem Mac und wird als **Linked Device** am eigenen
Signal-Konto angemeldet — kein neues Konto, kein Business-API nötig.

---

## Voraussetzungen

- Docker (Desktop oder Engine) läuft.
- `.env` enthält `KOLLEGE_SIGNAL_NUMBER=+49...` (deine Signal-Rufnummer).

---

## 1. Container starten

```bash
docker compose up -d
```

Überprüfe, ob der Container läuft:

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8080/v1/health
# Erwartete Antwort: 204
```

> **Hinweis:** `/v1/health` liefert bei Erfolg **HTTP 204 No Content** mit
> *leerem* Body zurück — `curl http://localhost:8080/v1/health` zeigt also
> bewusst nichts an. Das ist korrekt, kein Fehler. Mit dem `-w '%{http_code}'`
> oben siehst du den Statuscode.
>
> Direkt nach `docker compose up -d` braucht der Container ein paar Sekunden
> (`STATUS: health: starting`). Erst danach antwortet `/v1/health` mit 204.

Optional — Modus und Version prüfen (`mode` muss `json-rpc` sein):

```bash
curl -s http://localhost:8080/v1/about
# {"versions":[...],"mode":"json-rpc","version":"...", ...}
```

---

## 2. Als Linked Device verknüpfen

Signal erlaubt mehrere verknüpfte Geräte pro Konto (z. B. Signal Desktop).
Wir registrieren Kollege als eines dieser Geräte.

**QR-Code erzeugen:**

`/v1/qrcodelink` liefert den QR-Code **direkt als PNG-Bild** zurück — kein
`qrencode` nötig. Als Datei speichern und öffnen:

```bash
curl -s "http://localhost:8080/v1/qrcodelink?device_name=KollegeBot" -o signal-link-qr.png
open signal-link-qr.png   # macOS
```

> Der Link-Token läuft nach wenigen Minuten ab. Wenn das Scannen scheitert
> (Token abgelaufen), den Befehl einfach erneut ausführen — es entsteht ein
> frischer QR-Code.

Alternative (QR-Code direkt im Terminal, falls `qrencode` installiert ist —
`brew install qrencode`):

```bash
curl -s "http://localhost:8080/v1/qrcodelink?device_name=KollegeBot" | qrencode -t ansiutf8
```

**Auf dem Smartphone scannen:**

1. Signal öffnen → Einstellungen → Verknüpfte Geräte → `+`
2. QR-Code scannen.
3. „KollegeBot" erscheint in der Geräteliste → Verknüpfung bestätigt.

**Verknüpfung serverseitig prüfen:**

```bash
curl -s http://localhost:8080/v1/accounts
# Erwartete Antwort: ["+49..."]  (deine verknüpfte Nummer)
```

Eine leere Liste (`[]`) bedeutet: noch kein Gerät verknüpft.

---

## 3. Verbindung prüfen

Sende eine Test-Nachricht an dich selbst via API:

```bash
curl -X POST http://localhost:8080/v2/send \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Hallo von Kollege 👋",
    "number": "+49...",
    "recipients": ["+49..."]
  }'
```

Ersetze `+49...` durch deine Signal-Rufnummer.

---

## 4. Kollege konfigurieren

Stelle sicher, dass `.env` folgende Werte enthält:

```env
KOLLEGE_SIGNAL_API_URL=http://localhost:8080
KOLLEGE_SIGNAL_NUMBER=+49...          # deine Signal-Rufnummer
```

---

## 5. Bot starten

Voraussetzungen (einmal prüfen):

1. **Container läuft & verknüpft** — siehe oben (`/v1/health` → 204, `/v1/accounts`
   enthält deine Nummer).
2. **Ollama läuft** mit einem tool-fähigen Modell (Standard `qwen2.5:7b-instruct`):

   ```bash
   curl -s http://localhost:11434/api/tags   # listet installierte Modelle
   ```
3. **Signal-Abhängigkeiten installiert**: `uv sync --group signal`
   (für Sprachnotizen zusätzlich `uv sync --group transcription`).

Dann den Live-Listener starten:

```bash
uv run python scripts/run_signal.py
```

Das Skript prüft Health, Verknüpfung und Konfiguration vorab und meldet klar,
falls etwas fehlt. Bei Erfolg:

```
✓ Bereit. Lausche auf Signal-Nachrichten … (Strg-C zum Beenden)
```

Beenden mit **Strg-C**. Im Hintergrund (Logs in Datei):

```bash
nohup uv run python scripts/run_signal.py > kollege.log 2>&1 &
tail -f kollege.log
```

---

## 6. Mit Kollege reden (Note-to-Self)

Kollege ist als **verknüpftes Gerät an deinem eigenen Konto** angemeldet und
verarbeitet **ausschließlich deine „Notiz an mich"-Nachrichten** (Note-to-Self).
Eingehende Nachrichten *anderer* Personen werden bewusst **ignoriert** — der Bot
liest also nicht deinen sonstigen Signal-Verkehr.

So testest du:

1. In Signal den Chat **„Notiz an mich"** öffnen (dein eigener Kontakt, ganz oben
   in der Kontaktliste).
2. Eine Notiz schreiben oder als **Sprachnachricht** aufnehmen, z. B.:
   > *Ich muss morgen Frau Müller vom Gartenamt zurückrufen wegen des
   > Bebauungsplans Grüne Mitte, bis Freitag.*
3. Kollege antwortet mit einem Vorschlag („Ich habe folgendes erkannt: …").
   - **Erste Antwort dauert 20–60 s**, solange Ollama das Modell lädt.
   - Erste **Sprachnachricht** lädt zunächst das Whisper-Modell (~1,5 GB).
4. Bestätigen mit **👍** oder **„ja"** (oder Nummern wie „1 3" für eine Auswahl);
   ablehnen mit **„nein"**. Nach Bestätigung speichert Kollege in die DB und
   meldet **✅**.

> **Warum Note-to-Self statt einer zweiten Nummer?** Kein zweites Konto, keine
> Business-API. Auf dem verknüpften Gerät kommen deine Note-to-Self-Nachrichten
> als `syncMessage.sentMessage` an; Kollege filtert genau diese heraus.
> Eigene Bot-Antworten erzeugen keine Schleife (signal-cli stellt einem Gerät
> seine selbst gesendeten Nachrichten nicht erneut zu).

### Fehlersuche: rohe Envelopes ansehen

Wenn unklar ist, ob/wie Nachrichten ankommen, schneidet dieses Hilfsskript die
rohen WebSocket-Pakete mit (Bot vorher stoppen, damit sich nicht zwei Empfänger
die Nachrichten teilen):

```bash
uv run python scripts/signal_debug_receive.py 30   # lauscht 30 s
```

---

## Sicherheitshinweise

- `signal-cli-config/` enthält private Schlüsselmaterial — **nie ins Git committen**.
  (`.gitignore` enthält bereits diesen Eintrag.)
- Sichere das Verzeichnis genauso wie dein Signal-Konto.
- Bei Verlust: Verknüpfung in Signal entfernen und neu verknüpfen.

---

## Container verwalten

| Aktion | Befehl |
|---|---|
| Starten | `docker compose up -d` |
| Stoppen | `docker compose down` |
| Logs | `docker compose logs -f` |
| Neustart | `docker compose restart signal-cli-rest-api` |
| Logs (Container) | `docker compose logs signal-cli-rest-api` |
