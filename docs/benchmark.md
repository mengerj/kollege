# Modell-Benchmark (Schritt 8.11)

Vergleicht mehrere LLMs (lokal *und* API) reproduzierbar auf **Extraktions-**
und **Korrektur-/Revisions-Qualität**. Ersetzt das Bauchgefühl bei der
Modellwahl (Ollama vs. API) durch eine messbare Grundlage.

## Warum — die vier Fehlerklassen

Auslöser war ein Live-Vorfall am 2026-07-01: eine triviale Rechtschreibkorrektur
(„Es heißt Aibling, nicht Eibling") auf einen offenen Vorschlag lief ins Leere
(„nichts erkannt"). Die Ursachenanalyse (siehe
[ROADMAP.md](../ROADMAP.md#schritt-811--modell-benchmark-system-extraktion--revision))
ergab: Das Modell *versteht* die Korrektur, scheitert aber **nicht-deterministisch**
am strukturierten Output — bei zwei verschiedenen lokalen Modellen reproduzierbar.

Das bestehende Eval-Set (Schritt 8.10, [`tests/test_eval.py`](../tests/test_eval.py))
konnte das nicht sichtbar machen:

| Fehlerklasse | Warum das alte Eval-Set (8.10) sie verpasst |
|---|---|
| **Flakiness** | Ein einzelner Lauf pro Fixture — ein Glückstreffer verdeckt eine flakige Ausgabe. |
| **Über-Extraktion** | Nur `min_*`-Schwellen — mehr Einträge sind nie ein Fehlschlag, auch wenn dupliziert wird. |
| **„nichts erkannt"** | Kein `must_not_be_empty`-Check — ein leeres `ExtractionResult` bestand die Schwelle trotzdem. |
| **Nicht angewandte Korrektur** | Kein Revisions-Pfad — nur Erstextraktion wurde getestet. |

Der Benchmark (8.11) adressiert alle vier: **N Wiederholungen** pro Fixture
(Flakiness), **`max_*`**-Schwellen (Über-Extraktion), **`must_not_be_empty`**
(„nichts erkannt"), und eine **zweite Fixture-Familie** für die Revisions-Schleife
(nicht angewandte Korrektur — der Aibling-Fall ist das erste Revisions-Fixture).

## Architektur

```
src/kollege/eval/          Single Source of Truth (kein LLM, voll testbar)
  fixtures.py                 Laden + Schema-Validierung (beide Fixture-Familien)
  scoring.py                  expected-Block → FixtureScore (hits/total + Flags)
  runner.py                   N Wiederholungen + Aggregation (pass_rate, mean_score, …)

tests/fixtures/eval/           Extraktions-Fixtures (Erstextraktion)
tests/fixtures/eval_revision/  Revisions-Fixtures (Korrektur-Schleife, Schritt 8.6)

tests/test_eval.py          pytest-Verdrahtung um kollege.eval (CI + --real-llm)
scripts/benchmark_models.py CLI: mehrere Modelle × beide Suiten × N Runs
```

`tests/test_eval.py` und `scripts/benchmark_models.py` importieren beide aus
`kollege.eval` — kein Logik-Duplikat. Der Benchmark ruft exakt den
Produktions-Pfad auf (`run_extraction` / `run_revision` aus
[`src/kollege/agent/__init__.py`](../src/kollege/agent/__init__.py)), misst also,
was live passiert, inklusive Primär-→Fallback-Verhalten.

## Fixtures ergänzen (Wachstumspfad)

Ein neues Szenario ist eine **neue JSON-Datei, kein Code-Diff**.

### Extraktion (`tests/fixtures/eval/<name>.json`)

```json
{
  "id": "eindeutige_id",
  "description": "Kurzbeschreibung, was getestet wird",
  "tags": ["optional", "zum Filtern"],
  "transcript": "Der Beispieltext, den das Modell verarbeiten soll.",
  "expected": {
    "min_contacts": 1, "max_contacts": 1,
    "contact_names": ["Wagner"],
    "min_tasks": 1, "max_tasks": 2,
    "task_keywords": ["Pflanzplan"],
    "min_project_updates": 0, "max_project_updates": null,
    "project_names": [],
    "forbidden_keywords": ["Eibling"],
    "must_not_be_empty": true
  }
}
```

Alle Keys außer `id`/`transcript`/`expected` sind optional; alle `expected`-Keys
haben Defaults (0 / leere Liste / `false`) — bestehende Fixtures ohne die neuen
8.11-Keys bleiben gültig.

### Revision (`tests/fixtures/eval_revision/<name>.json`)

Bildet die Quote-Reply-Korrektur (Schritt 8.6) nach: Ursprungstranskript +
bereits vorgeschlagenes `ExtractionResult` + Korrekturtext → erwartetes
revidiertes Ergebnis.

```json
{
  "id": "aibling_rechtschreibkorrektur",
  "original_transcript": "Ich muss noch den Kunden in Eibling wegen der Terrasse anrufen.",
  "current_result": {
    "contacts": [], "project_updates": [], "clarification": null,
    "tasks": [{"title": "Kunde in Eibling wegen Terrasse anrufen", "contact": null, "project": null, "due": null, "time_window": null}]
  },
  "correction": "Es heißt Aibling, nicht Eibling.",
  "known_names": [],
  "expected": {
    "min_tasks": 1, "max_tasks": 1,
    "task_keywords": ["Aibling"],
    "forbidden_keywords": ["Eibling"],
    "must_not_be_empty": true
  }
}
```

`current_result` ist ein vollständiges `ExtractionResult` (siehe
[`src/kollege/models.py`](../src/kollege/models.py)) — am einfachsten von einem
echten Lauf kopieren und anpassen. `known_names` simuliert den Kontext aus
Schritt 8.7 (leer lassen, wenn irrelevant für das Szenario).

### Neue Prüfung im Scorer

Ein neuer `expected`-Key = ein optionales Feld in `ExtractionExpectation`
([`fixtures.py`](../src/kollege/eval/fixtures.py)) + ein Zweig in `score_result()`
([`scoring.py`](../src/kollege/eval/scoring.py)). Kein Umbau von Fixtures oder
Aufrufern nötig.

## Modell registrieren

Kein Code-Diff — eine Zeile auf der Kommandozeile. Syntax:
`modell` (Standard-Provider `ollama`) oder `provider:modell`:

| Provider | Beispiel | Voraussetzung |
|---|---|---|
| `ollama` (Standard) | `qwen2.5:7b-instruct` | Lokaler Ollama-Server, Modell gepullt |
| `anthropic` | `anthropic:claude-sonnet-4-6` | `ANTHROPIC_API_KEY` |
| `openai` | `openai:gpt-4o-mini` | `OPENAI_API_KEY` |
| `openrouter` | `openrouter:mistralai/mistral-large` | `KOLLEGE_OPENROUTER_API_KEY` (`.env`) |

**OpenRouter** ist das bequeme Backend für die *Entdeckungsphase* — ein Key,
viele Modelle (Mistral, Qwen, DeepSeek, GLM, …). Die Fixtures sind synthetisch
(keine echten personenbezogenen Daten), daher hier datenschutzrechtlich
unkritisch. **Kein Produktions-Fundament** — OpenRouter ist ein US-Intermediär
ohne sauberen EU-AVV auf Router-Ebene. Die konforme Produktions-Anbindung ist
Schritt 8.12.

## Kosten: warum das viele Modell-Aufrufe sind

`N Wiederholungen × Fixtures × Suiten × Modelle` — das ist **Absicht** (siehe
oben, Flakiness braucht Wiederholungen), aber jeder „Lauf" ist selbst schon ein
mehrstufiges Agenten-Gespräch: Primär-Pfad (strukturierter Output, mit eigenem
pydantic-ai-Retry), bei Fehlschlag Fallback-Pfad (bis zu 3 weitere Versuche),
und innerhalb jedes Versuchs ein Tool-Call pro erkanntem Kontakt/Task/Projekt.
Ein Modell wie `ornith:9b`, das den Primär-Pfad fast nie besteht (genau das
Live-Symptom, das 8.11 auslöste), zahlt diese Kosten bei **jedem einzelnen**
Lauf — das ist kein Bug im Benchmark, sondern misst exakt das Problem.

Zwei Hebel, um das Ganze schlank zu halten:

- **Fixture-Set bewusst knapp gehalten.** `04_schneider_angebot` wurde entfernt
  (near-duplicate zu `01_wagner_pflanzplan`: „Kontakt + ein Task + Frist", ohne
  zusätzliches Signal). Aktuell 4 Extraktions- + 2 Revisions-Fixtures — die
  Revisions-Fixtures haben Priorität, weil sie den auslösenden Fehlerfall direkt
  testen. Beim Ergänzen (siehe oben) lieber ein neues *Verhalten* abdecken als
  eine Variation eines bestehenden Fixtures.
- **`--runs 3` für explorative Vergleiche, `--runs 5` für die eingecheckte
  Baseline.** Cloud-Modelle zusätzlich mit `--concurrency` parallelisieren
  (siehe unten) — lokales Ollama profitiert davon nicht (eine GPU, eine Anfrage
  gleichzeitig).

## Befehle

```bash
# Beide Suiten, Standard-Modelle des Live-Vorfalls, 5 Wiederholungen:
uv run python scripts/benchmark_models.py \
  --models ornith:9b,qwen2.5:7b-instruct \
  --runs 5

# Nur Revision, nur ein Modell, weniger Wiederholungen (schneller):
uv run python scripts/benchmark_models.py \
  --models qwen2.5:7b-instruct --suite revision --runs 3

# Lokal gegen ein API-Modell vergleichen:
uv run python scripts/benchmark_models.py \
  --models ornith:9b,anthropic:claude-sonnet-4-6 --runs 5

# OpenRouter-Modelle parallelisieren (netzwerkgebunden, kein GPU-Engpass):
uv run python scripts/benchmark_models.py \
  --models openrouter:mistralai/mistral-large,openrouter:qwen/qwen-2.5-7b-instruct \
  --runs 5 --concurrency 5

# Eval-Set (8.10) weiterhin einzeln nutzbar — ein Lauf, keine Aggregation:
uv run pytest -m eval --real-llm -s
```

Optionen: `--suite extraction,revision` (Standard: beide), `--out <dir>`
(Standard: `benchmarks/results/`), `--threshold` (Standard: 0.5, siehe unten),
`--concurrency N` (Standard: 1 = seriell; parallelisiert die Wiederholungen pro
Fixture — nur für Nicht-Ollama-Provider wirksam, siehe oben).

## Ergebnis-Interpretation

Der Benchmark druckt pro Modell eine Tabelle pro Suite und am Ende eine
Vergleichs-Matrix (Modell × Suite → `pass_rate`). Die Kennzahlen bedeuten
**verschiedene Dinge** — nicht nur `pass_rate` anschauen:

- **`pass_rate`** — Anteil Läufe, die die Trefferquoten-Schwelle (`--threshold`,
  Standard 50 %) erreichen **und** keine der drei Fehler-Flags treffen. Die
  Gesamtkennzahl für „ist dieses Modell brauchbar".
- **`mean_score`** — durchschnittliche Trefferquote (Mindestanzahlen +
  Schlüsselwörter), unabhängig von den Fehler-Flags. Hoch bei niedriger
  `pass_rate` → die Flags (nicht die Grundqualität) sind das Problem.
- **`empty_rate`** — Anteil Läufe, die trotz `must_not_be_empty: true` ein
  leeres Ergebnis lieferten. Direkter Indikator für die „nichts erkannt"-Klasse
  aus dem Live-Vorfall.
- **`over_extraction_rate`** — Anteil Läufe über einer `max_*`-Schwelle
  (Duplikate, zerlegte Sätze). Hoch bei sonst gutem `mean_score` → das Modell
  „versteht", neigt aber zum Zerlegen (bekanntes qwen2.5:7b-Verhalten, siehe
  [`docs/live-testing-guide.md`](live-testing-guide.md) §5.8).
- **`error_rate`** — Anteil Läufe, die eine Exception geworfen haben (Netz/Modell
  nicht erreichbar), **nicht** Teil der `pass_rate`-Berechnung im Nenner-Sinne,
  aber sichtbar in der Tabelle.
- **`median_latency_s`** — Median der Wall-Clock-Zeit pro Lauf. Bei Ollama stark
  von Cold-Start/RAM-Druck beeinflusst (siehe Live-Testing-Guide §5.10) — bei
  wiederholten Benchmark-Läufen ist das Modell meist schon warm.

**Schwellenwert (`--threshold`, Standard 0.5):** identisch zum bisherigen
Eval-Set (8.10) — bewusst niedrig, weil auch ein teilweise korrektes Ergebnis
(z. B. Kontakt erkannt, Datum leicht daneben) für Human-in-the-loop noch
brauchbar ist. Die Fehler-Flags (`empty`/`over_extraction`/`forbidden_hit`)
sind dagegen hart: ein Treffer disqualifiziert den Lauf unabhängig von der
Trefferquote.

## Ablage der Historie

Jeder Modell-Lauf schreibt eine kompakte Zusammenfassung nach
`benchmarks/results/<datum>_<modell>.md` (**eingecheckt** — Regressions-/
Fortschritts-Tracking über Modell-Versionen). Rohe Einzellauf-Daten werden
nicht persistiert; falls das später gebraucht wird (Backlog), gehört das nach
`benchmarks/results/*.json` — bereits in `.gitignore` vorgesehen.

## Bewusst nicht im Scope

- Automatische CI-Gates gegen echte Modelle (Benchmark läuft nur manuell).
- Kosten-/Token-Tracking pro API-Modell.
- Semantische Ähnlichkeit statt Keyword-Match.
- Whisper-Transkriptions-Benchmark (nur Text-Fixtures, Audio-Pfad separat).

Siehe auch: [Schritt 8.12](../ROADMAP.md#schritt-812--dsgvo-konforme-eu-llm-anbieter-evaluieren--anbinden)
nutzt diesen Benchmark als Auswahl-Werkzeug für einen DSGVO-konformen
Produktions-Anbieter.
