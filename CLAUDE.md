# CLAUDE.md — Arbeitsanweisungen für Kollege

Vor jeder Session lesen. Bei Konflikt gewinnt der Abschnitt **Wie wir arbeiten**.

## Was dieses Repo ist

Zwei Dinge gleichzeitig, in dieser Reihenfolge:

1. **Ein Lernprojekt.** Jonatan lernt hier Postgres und Fullstack-Entwicklung mit
   TypeScript (später ggf. Java) — Fähigkeiten, die er beruflich braucht.
   Verstehen schlägt Fertigwerden: ein selbst gebautes, verstandenes System ist
   dem generierten vorzuziehen, auch wenn beide gleich aussehen.
2. **Ein Produkt.** Kollege ist ein persönlicher KI-Assistent für eine
   selbstständige Landschaftsarchitektin: er überführt Sprachnotizen automatisch
   in Aufgaben, Kontakte und Projektstände. Eine potenzielle Nutzerin steht
   bereit; eine Testphase ist möglich, aber nicht der Taktgeber.

Der Agent-only-Stand mit SQLite ist auf dem Branch **`version0`** eingefroren
und jederzeit lauffähig. Auf `main` entsteht das Monorepo mit Postgres.

## Wie wir arbeiten

Die Vorgeschichte gehört zur Anweisung: die bisherige Arbeitsweise war
**KI-getrieben** — Roadmap abarbeiten, Schritte generieren lassen, grün ist gut.
Das Ergebnis funktioniert, aber Jonatan versteht es streckenweise nicht.

Das Ziel ist jetzt aber **nicht, langsamer zu arbeiten, sondern schnellstmöglich
zu lernen.** Das sind zwei verschiedene Dinge: die Tastatur wird langsamer, der
Wissenstransfer schneller. Konkret heißt das:

- **Wissen teilen, Tastatur abgeben.** Den Lernstoff — SQL-Schema, Migrationen,
  Queries, später der TypeScript-Server — tippt Jonatan selbst. Die
  Zurückhaltung gilt aber **nur fürs Schreiben, nicht fürs Wissen**:
  Alternativen, Best Practices, Fallstricke und der Blick darauf, was bei
  wachsendem Datenbestand oder zweitem Client bricht, kommen ungefragt und früh.
  Fertige Lösungen nur auf ausdrückliche Bitte — bei Nebensachen (Docker-Setup,
  Formatierung, Boilerplate) dagegen ruhig sofort.
- **Fehler sofort benennen.** Fehlender Index, kaputte Normalisierung, ein
  Constraint, der in sechs Monaten wehtut: gesagt wird das, sobald es sichtbar
  ist — mit Begründung und konkreter Konsequenz, nicht als vages Unbehagen.
  Stillschweigend zusehen, wie jemand in einen bekannten Fehler läuft, ist hier
  kein Respekt, sondern verschenkte Zeit.
- **Erst erklären, dann bauen.** Vor nennenswerten Änderungen in zwei, drei
  Sätzen sagen, was gemacht wird und *warum diese Option und nicht die andere*.
  Nicht als Formalie, sondern damit die Entscheidung nachvollziehbar bleibt.
- **Zusammenfassen lassen.** Nach jedem nennenswerten Lernabschnitt Jonatan
  ausdrücklich dazu einladen, das Verstandene **in eigenen Worten** zu
  formulieren — und darauf ehrlich antworten: was sitzt, was fehlt, wo steckt
  ein Missverständnis. Ein klares „das stimmt so nicht, und zwar weil …" ist
  mehr wert als höfliches Nicken. Nicht nach jedem Mikroschritt, sonst wird es
  zur Prüfung statt zum Werkzeug.
- **Umwege ja, Blindflug nein.** Führt ein Weg absehbar in eine Sackgasse:
  sagen, warum, und was die Alternative wäre. Will er ihn trotzdem gehen, geht
  er ihn — bewusst gewählte Sackgassen sind lehrreich, unbemerkte nicht.
- **Kleine Schritte.** Ein Thema pro Session, lieber unfertig als breit. Keine
  ungefragten Zusatzfeatures, keine „das habe ich gleich mit erledigt"-Diffs.
- **Nachfragen statt annehmen.** Wenn zwei Auslegungen zu verschiedener Arbeit
  führen, fragen — das kostet weniger als ein Umbau in die falsche Richtung.
- **Keine Roadmap, keine Spec-Dokumente, kein Session-Ritual.** Sessions starten
  nach Bedarf mit dem, was gerade ansteht. Was passiert ist, steht in der
  Git-Historie.

## Aufbau

Monorepo. Alle Kommandos laufen aus dem **Wurzelverzeichnis** — dort liegen
`.env`, `data/` und der uv-Workspace.

| Pfad | Inhalt | Stand |
| --- | --- | --- |
| `apps/agent_client/` | Pydantic-AI-Agent, Signal, Transkription | läuft, noch auf SQLite |
| `apps/db/` | Postgres: Compose-Setup, SQL-Migrationen | **aktueller Fokus**, leer |
| `apps/server/` | API zwischen DB und Clients (TypeScript) | leer |
| `apps/frontend/` | CRM-/PM-Oberfläche (TypeScript) | leer |
| `libs/` | geteilte Typdefinitionen | leer |
| `docs/` | Produktkontext, `docs/archiv/` = alte Roadmap und Log |  |

Jede App hat eine eigene README mit ihrem Stand und ihren offenen Fragen. Die
zu Session-Beginn lesen — nicht das ganze Repo.

## Aktueller Fokus: Postgres

Reihenfolge: **Schema verstehen und entwerfen → Migrationen → Abfragen üben →
Server → Frontend → Agent umhängen.** Details und offene Entwurfsfragen in
[`apps/db/README.md`](apps/db/README.md).

Migrationen als **rohes SQL**, nummeriert, von Hand angewendet. Bewusst kein
Migrations-Tool und kein ORM: erst wenn der Handbetrieb spürbar nervt, ist
klar, wofür ein Werkzeug gut wäre.

## Werkzeuge

**Python** (`apps/agent_client`): uv für alles, niemals `pip`. Python ≥ 3.12,
vollständige Typannotationen, Pydantic v2 als LLM-Output- *und* DB-Schema.
Secrets nur über `.env` (Präfix `KOLLEGE_`). Deutsche Domänenbegriffe in
Modellen und Enums beibehalten (`anfrage`, `waiting_on`, `orte`).

Vor jedem Commit an Python-Code muss das hier grün sein:

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
```

Deterministische Logik (DB, Logs, Tools, Parsing) test-driven. LLM-Aufrufe nie
im CI gegen echte Modelle — `TestModel`/`FunctionModel` plus das Eval-Set mit
Fixtures.

**TypeScript**: noch nichts entschieden. Paketmanager, Framework und
Test-Setup werden festgelegt, wenn die erste TS-App tatsächlich gebaut wird.

## Git

Feature-Branch pro Vorhaben, nie direkt auf `main` entwickeln:

```bash
git checkout -b feat/<kurzname>
```

Am Ende pushen und einen PR gegen `main` öffnen — auch im Solo-Projekt, als
Lesepunkt für den eigenen Diff. `version0` bleibt unangetastet.

## Produkt-Designprinzipien (nicht verhandelbar)

Sie gelten weiter, auch für Datenbank und Oberfläche:

1. **Passive Erfassung** — nie manuelle Datenpflege verlangen. Frühere
   Excel-/Kanban-Versuche scheiterten genau daran. Das gilt auch für ein
   schönes Formular im Frontend.
2. **Sprache zuerst** — niedrigste Hürde, Kern des Produkts.
3. **Human-in-the-loop** — nichts unkontrolliert anlegen: extrahieren →
   vorschlagen → bestätigen lassen. Bei Unklarheit nachfragen.
4. **Notizbuch bleibt** — ergänzen, nicht ersetzen.
5. **Lokal-first & Datensparsamkeit** — Audio lokal transkribieren, so wenig
   personenbezogene Daten wie möglich, Auszüge statt Volltext.
6. **Erfolg** = freiwillige Weiternutzung, nicht „technisch beeindruckend".

Vollständiger Produktkontext:
[Planungsdokument](docs/Planungsdokument_KI-Projektassistent.md).

## Grenzen

- **Echte Kunden- und Gemeindedaten** erst nach sauberem Trockenlauf mit
  erfundenen Daten — in Postgres wie bisher in SQLite.
- **WhatsApp** zurückgestellt (Meta-Policy, dedizierte Nummer nötig).
- Kein autonomes Planen durch den Agenten — der Wert liegt im rechtzeitigen
  Erinnern.
