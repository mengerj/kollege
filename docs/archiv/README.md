# Archiv der ersten Projektphase

Diese Dateien haben die Entwicklung bis August 2026 gesteuert, als Kollege ein
reines Agent-Projekt mit SQLite war. Sie werden **nicht mehr gepflegt** und
beschreiben teilweise Pfade, die es so nicht mehr gibt (alles lag damals im
Wurzelverzeichnis, nicht unter `apps/`).

| Datei | war |
| --- | --- |
| [ROADMAP.md](ROADMAP.md) | offene Schritte und der jeweils nächste |
| [ROADMAP_ARCHIV.md](ROADMAP_ARCHIV.md) | Detailbegründungen erledigter Schritte |
| [PROJECT_LOG.md](PROJECT_LOG.md) | chronologisches Log jeder Session |

Aufgehoben, weil hier die *Begründungen* stehen: warum der Agent zweistufig
extrahiert, warum Örtlichkeiten eine eigene Entität wurden, was in
Modellvergleichen tatsächlich herauskam. Beim Entwurf des Postgres-Schemas ist
das nützlicher Kontext.

Gezielt suchen statt lesen — `PROJECT_LOG.md` hat über 1600 Zeilen:

```bash
grep -n "Örtlichkeit" docs/archiv/PROJECT_LOG.md
```

Der Code-Stand, zu dem diese Dokumente gehören, liegt auf dem Branch
**`version0`**. Ab jetzt wird ohne Roadmap gearbeitet, siehe
[CLAUDE.md](../../CLAUDE.md).
