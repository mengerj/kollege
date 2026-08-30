# libs — geteilte Definitionen

Stand: **leer.** Hier landet, was mehr als eine App braucht.

Erwartbar zuerst: die Typen des Datenmodells (Projekt, Kontakt, Aufgabe,
Örtlichkeit) für Server und Frontend, samt Validierung — in TypeScript,
vermutlich mit Zod, sodass Laufzeitprüfung und statischer Typ aus einer Quelle
kommen.

## Die offene Frage

Der Agent ([`apps/agent_client`](../apps/agent_client/README.md)) ist Python und
beschreibt dasselbe Modell heute mit Pydantic. Zwei Sprachen, ein Datenmodell,
eine Datenbank — irgendetwas muss die Quelle sein, aus der der Rest folgt:

- das **SQL-Schema** als Wahrheit, Typen daraus generiert,
- eine **OpenAPI-Beschreibung** des Servers, Clients daraus generiert,
- oder von Hand gepflegte Definitionen auf beiden Seiten, die auseinanderdriften
  können (billig zu beginnen, teuer zu behalten).

Nicht vorab entscheiden — die Frage wird konkret, sobald Schema und erste
Endpunkte stehen.
