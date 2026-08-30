# apps/db — die Datenbank

Postgres als **Quelle der Wahrheit** für alle Clients: den bestehenden
Agenten ([`apps/agent_client`](../agent_client/README.md)) und die geplante
Weboberfläche ([`apps/frontend`](../frontend/README.md)).

Aktuell hält der Agent seine Daten noch in SQLite. Diese App ersetzt das
schrittweise — und ist zugleich das aktuelle Hauptlernziel: Postgres selbst
verstehen, statt es hinter einem ORM zu verstecken. **Migrationen werden hier
als rohes SQL geschrieben**, nummeriert und von Hand angewendet, solange das
trägt.

Stand: leer. Es gibt Docker-Setup und Konventionen, aber noch kein Schema.

## Datenbank starten

```bash
docker compose -f apps/db/docker-compose.yml up -d
```

```bash
docker compose -f apps/db/docker-compose.yml ps
```

Der `healthcheck` in der Compose-Datei meldet `healthy`, sobald Postgres
Verbindungen annimmt — der Container ist ein paar Sekunden vorher schon „up",
das ist nicht dasselbe.

Stoppen ohne Datenverlust: `stop`. `down -v` löscht das Volume **und damit alle
Daten** — der Unterschied steht kommentiert in der Compose-Datei.

## Verbinden

Ohne lokale Postgres-Installation, `psql` aus dem Container:

```bash
docker compose -f apps/db/docker-compose.yml exec postgres psql -U kollege -d kollege
```

Mit lokal installiertem Client (`brew install libpq` oder `postgresql@18`):

```bash
psql postgresql://kollege:kollege@localhost:5432/kollege
```

### Die Meta-Kommandos, die du am häufigsten brauchst

| Kommando | zeigt |
| --- | --- |
| `\l` | alle Datenbanken |
| `\dt` | Tabellen der aktuellen Datenbank |
| `\d tabellenname` | Spalten, Typen, Indizes, Constraints einer Tabelle |
| `\d+ tabellenname` | dasselbe plus Größe und Beschreibungen |
| `\di` | Indizes |
| `\du` | Rollen/Benutzer |
| `\x` | Ausgabe zeilenweise statt tabellarisch (bei breiten Tabellen) |
| `\timing` | Ausführungszeit jeder Query anzeigen |
| `\q` | beenden |

`EXPLAIN ANALYZE <query>` zeigt, wie Postgres eine Abfrage tatsächlich
ausführt — das ist der direkteste Weg zu verstehen, wann ein Index greift.

## Migrationen

Konvention: eine Datei pro Änderung in `migrations/`, aufsteigend nummeriert,
Name beschreibt die Absicht.

```
migrations/
  001_init.sql
  002_kontakte_ohne_unique_name.sql
```

Regeln, die sich bewährt haben:

- **Eine angewendete Migration wird nie wieder geändert.** Korrekturen kommen
  als neue Datei. Sonst driften deine Datenbank und die Dateien auseinander.
- Jede Datei ist für sich lauffähig und läuft in einer Transaktion
  (`BEGIN; ... COMMIT;`), damit ein Fehler nichts halb Angewendetes hinterlässt.
- Kommentiere im SQL, *warum* eine Entscheidung so fiel — der Code sagt schon,
  *was* passiert.

Anwenden:

```bash
docker compose -f apps/db/docker-compose.yml exec -T postgres psql -U kollege -d kollege < apps/db/migrations/001_init.sql
```

Solange es eine Handvoll Dateien sind, reicht das. Sobald du den Überblick
verlierst, welche Migration schon gelaufen ist, ist das der richtige Moment,
eine `schema_migrations`-Tabelle und ein kleines Runner-Skript zu bauen — und
dann verstehst du auch, warum Werkzeuge wie Flyway oder dbmate existieren.

## Das Schema entwerfen

**Erst eigener Entwurf, dann Vergleich.** Das SQLite-Schema des Agenten
existiert noch, ist aber bewusst *nicht* die Vorlage: es ist unter ganz anderen
Zwängen entstanden (eine Nutzerin, ein Client, ein LLM, das Duplikate
produzierte). Wer es zuerst liest, übernimmt seine Kompromisse, ohne sie als
Kompromisse zu erkennen. Also: erst auf Papier oder direkt in SQL skizzieren,
was die Domäne braucht — danach mit
[`repository.py`](../agent_client/src/kollege/db/repository.py) abgleichen und
die Unterschiede erklären. Genau die Unterschiede sind der Lerngewinn.

### Was abgebildet werden muss

Die Fachlichkeit, ohne Tabellenvorschlag:

- **Projekte** einer Landschaftsarchitektin — für Privatkunden und Gemeinden,
  mit einem Verlauf von der Anfrage bis zur Fertigstellung. Sie laufen über
  Monate und ruhen zwischendurch.
- **Kontakte** in mehreren Rollen: Auftraggeber, Gemeindeverwaltung,
  ausführende Gartenbaufirmen, Ämter. Dieselbe Person kann in verschiedenen
  Projekten verschiedene Rollen haben.
- **Örtlichkeiten** — Grundstücke mit Adresse und/oder Flurnummer. Nicht jedes
  Projekt hat eine, manche haben mehrere.
- **Aufgaben** mit Fristen, Zeitfenstern („im Frühjahr", „nach dem Frost"),
  Abhängigkeiten untereinander und dem Zustand *„warte auf Rückmeldung von X"*.
- **Herkunft und Nachvollziehbarkeit** — jeder Datensatz stammt entweder aus
  einer Sprachnotiz (vom LLM extrahiert, von der Nutzerin bestätigt) oder aus
  direkter Eingabe. Bei Fehlextraktionen muss man zurückverfolgen können,
  woher etwas kam.
- Später: **Nutzer und Zugriff**, sobald eine Weboberfläche existiert.

### Fragen, an denen sich der Entwurf entscheidet

- Welche Beziehungen sind 1:n, welche echt n:m? (Rollen von Kontakten in
  Projekten sind der interessante Fall.)
- Welche Datentypen für Zeit? Postgres unterscheidet `date`, `timestamptz` und
  `interval` — ein unscharfes „im Frühjahr" ist keines davon.
- Wie werden Zustände abgebildet: `CHECK`-Constraint, `ENUM`-Typ oder
  Nachschlagetabelle? Alle drei sind vertretbar und kosten Unterschiedliches,
  wenn sich die Liste ändert.
- Welche Constraints erzwingen Korrektheit, welche stehen dem Betrieb im Weg?
  Ein `UNIQUE` auf Kontaktnamen verhindert Duplikate — und den zweiten Herrn
  Müller.
- Löschen: echtes `DELETE` oder `deleted_at`? Für einen Assistenten, der
  Vorschläge macht, ist Nachvollziehbarkeit besonders wertvoll.
- Wo braucht es Indizes, und warum erst dann? (`EXPLAIN ANALYZE` beantwortet
  das besser als Intuition.)

Diese Liste ist Diskussionsstoff, keine Aufgabenliste.

## Grenze

Bis der Trockenlauf mit erfundenen Daten sauber läuft, kommen **keine echten
Kunden- oder Gemeindedaten** in diese Datenbank. Die lokale Instanz hat ein
Klartext-Passwort und keine Verschlüsselung im Ruhezustand.
