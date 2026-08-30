# apps/server — die API

Stand: **leer.** Platzhalter für den Server zwischen Datenbank und Clients.

Geplant in TypeScript (Node), damit Frontend und Server dieselbe Sprache und
dieselben Typdefinitionen aus [`libs/`](../../libs/README.md) teilen. Fastify
oder NestJS — offen. Ein zweiter Server in Java gegen dasselbe Schema ist als
Vergleich denkbar, aber nicht geplant.

Reihenfolge: erst ein tragfähiges Schema in [`apps/db`](../db/README.md), dann
hier die ersten Endpunkte, dann Frontend und Agent als Clients daran.

Bis dahin greift der Agent direkt auf seine SQLite-Datei zu — das ist genau der
Zustand, den dieser Server ablösen soll.
