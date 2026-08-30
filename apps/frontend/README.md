# apps/frontend — die Weboberfläche

Stand: **leer.** Platzhalter für die spätere Oberfläche.

Ziel ist ein CRM- und Projektmanagement-Werkzeug für Landschaftsarchitektur:
Projekte, Kontakte, Örtlichkeiten und Aufgaben sehen und bearbeiten — als
sichtbares Gegenstück zum Agenten, der dieselben Daten per Sprache befüllt.

Geplant in TypeScript. Framework (Vite + React, Next.js, SvelteKit …) ist
bewusst noch nicht entschieden — das ergibt sich, sobald das Datenmodell steht
und klar ist, was die Oberfläche tatsächlich anzeigen muss.

Erst kommt das Schema ([`apps/db`](../db/README.md)), dann eine API
([`apps/server`](../server/README.md)), dann diese App.

## Designprinzip, das hier besonders wehtut

Das Projekt existiert, weil manuelle Datenpflege gescheitert ist — Excel und
Kanban-Boards wurden nicht weitergeführt. Eine Oberfläche mit vielen leeren
Formularfeldern würde genau diesen Fehler wiederholen. Sie soll zeigen und
korrigieren, was der Agent gesammelt hat, nicht zur Eingabemaske werden.
