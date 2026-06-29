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
curl http://localhost:8080/v1/health
# Erwartete Antwort: {"status":"ok"}
```

---

## 2. Als Linked Device verknüpfen

Signal erlaubt mehrere verknüpfte Geräte pro Konto (z. B. Signal Desktop).
Wir registrieren Kollege als eines dieser Geräte.

**Link-URI erzeugen:**

```bash
curl -X GET "http://localhost:8080/v1/qrcodelink?device_name=KollegeBot"
```

Die Antwort ist eine `sgnl://`-URI. Öffne sie in einem Browser oder wandle sie
in einen QR-Code um (z. B. mit `qrencode`):

```bash
# macOS (qrencode via Homebrew: brew install qrencode)
curl -s "http://localhost:8080/v1/qrcodelink?device_name=KollegeBot" \
  | qrencode -t ansiutf8
```

**Auf dem Smartphone scannen:**

1. Signal öffnen → Einstellungen → Verknüpfte Geräte → `+`
2. QR-Code scannen (oder URI direkt öffnen).
3. „KollegeBot" erscheint in der Geräteliste → Verknüpfung bestätigt.

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
