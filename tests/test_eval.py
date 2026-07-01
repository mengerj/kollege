"""Eval-Set für Extraktionsqualität.

Fixtures in ``tests/fixtures/eval/*.json`` enthalten Beispiel-Transkripte
und erwartete Felder. Jedes Fixture hat eine ``expected``-Sektion mit
Mindestanzahlen und Schlüsselwörtern.

Modi:
- **CI (Standard):** ``FunctionModel``-Mock gibt erwartetes Ergebnis zurück.
  Validiert Schema-Konformität und Pipeline-Verhalten ohne echtes LLM.
- **Real-LLM:** ``pytest -m eval --real-llm`` — echter Ollama/Anthropic-Aufruf.
  Berechnet Trefferquote pro Fixture (Schwellenwert: 50 %).

Ausführen:
    pytest -m eval            # CI-Modus (FunctionModel, schnell)
    pytest -m eval --real-llm # Real-LLM-Modus (Trefferquote)
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from kollege.agent import agent, run_extraction
from kollege.config import Settings
from kollege.db import Repository
from kollege.models import (
    ExtractedContact,
    ExtractedProjectUpdate,
    ExtractedTask,
    ExtractionResult,
)

# --------------------------------------------------------------------------- #
# Fixtures laden                                                                #
# --------------------------------------------------------------------------- #

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "eval"

_EVAL_FIXTURES: list[dict[str, Any]] = sorted(
    [json.loads(p.read_text()) for p in _FIXTURE_DIR.glob("*.json")],
    key=lambda x: str(x["id"]),
)

_FIXTURE_IDS: list[str] = [str(f["id"]) for f in _EVAL_FIXTURES]

# --------------------------------------------------------------------------- #
# Schwellenwert                                                                 #
# --------------------------------------------------------------------------- #

_QUALITY_THRESHOLD = 0.5

# --------------------------------------------------------------------------- #
# Hilfsfunktionen                                                               #
# --------------------------------------------------------------------------- #


def _make_repo() -> Repository:
    return Repository(sqlite3.connect(":memory:", check_same_thread=False))


def _mock_result_from_expected(expected: dict[str, Any]) -> ExtractionResult:
    """Erzeugt ein minimales ExtractionResult, das alle Mindestanforderungen erfüllt."""
    contact_names: list[str] = list(expected.get("contact_names", []))
    min_contacts: int = int(expected.get("min_contacts", 0))
    while len(contact_names) < min_contacts:
        contact_names.append(f"Kontakt {len(contact_names) + 1}")
    contacts = [ExtractedContact(name=n) for n in contact_names]

    task_keywords: list[str] = list(expected.get("task_keywords", []))
    min_tasks: int = int(expected.get("min_tasks", 0))
    task_titles: list[str] = task_keywords[:min_tasks]
    while len(task_titles) < min_tasks:
        task_titles.append(f"Aufgabe {len(task_titles) + 1}")
    tasks = [ExtractedTask(title=t) for t in task_titles]

    project_names: list[str] = list(expected.get("project_names", []))
    min_updates: int = int(expected.get("min_project_updates", 0))
    while len(project_names) < min_updates:
        project_names.append(f"Projekt {len(project_names) + 1}")
    updates = [ExtractedProjectUpdate(project=p) for p in project_names]

    return ExtractionResult(contacts=contacts, tasks=tasks, project_updates=updates)


def _make_mock_model(result: ExtractionResult) -> FunctionModel:
    """FunctionModel, das ein vorgegebenes ExtractionResult zurückgibt."""
    result_json = result.model_dump_json()

    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[ToolCallPart(tool_name="final_result", args=result_json)])

    return FunctionModel(fn)


def _score_result(result: ExtractionResult, expected: dict[str, Any]) -> tuple[int, int]:
    """Berechnet Trefferquote als (Treffer, Gesamt).

    Prüft Mindestanzahlen und Schlüsselwort-Teilstrings (case-insensitive).
    Schwellenwert-Tests statt striktem Equality-Assert (LLM-Nichtdeterminismus).
    """
    hits = 0
    total = 0

    # Mindestanzahl Kontakte
    total += 1
    if len(result.contacts) >= int(expected.get("min_contacts", 0)):
        hits += 1

    # Kontaktnamen (Teilstring, case-insensitive)
    for name_kw in expected.get("contact_names", []):
        total += 1
        if any(str(name_kw).lower() in c.name.lower() for c in result.contacts):
            hits += 1

    # Mindestanzahl Tasks
    total += 1
    if len(result.tasks) >= int(expected.get("min_tasks", 0)):
        hits += 1

    # Task-Schlüsselwörter in Titeln
    for kw in expected.get("task_keywords", []):
        total += 1
        if any(str(kw).lower() in t.title.lower() for t in result.tasks):
            hits += 1

    # Mindestanzahl Projektupdates
    total += 1
    if len(result.project_updates) >= int(expected.get("min_project_updates", 0)):
        hits += 1

    # Projektnamen
    for proj_kw in expected.get("project_names", []):
        total += 1
        if any(str(proj_kw).lower() in pu.project.lower() for pu in result.project_updates):
            hits += 1

    return hits, total


# --------------------------------------------------------------------------- #
# Eval-Tests                                                                   #
# --------------------------------------------------------------------------- #


@pytest.mark.eval
@pytest.mark.parametrize("fixture", _EVAL_FIXTURES, ids=_FIXTURE_IDS)
def test_eval_extraction(fixture: dict[str, Any], real_llm: bool) -> None:
    """Extraktions-Eval: CI mit FunctionModel-Mock, manuell mit echtem LLM.

    CI-Modus (Standard):
    - FunctionModel gibt erwartetes ExtractionResult zurück.
    - Prüft Schema-Konformität und Mindest-Counts.

    Real-LLM-Modus (--real-llm):
    - Echter run_extraction()-Aufruf (Ollama/Anthropic aus Settings).
    - Berechnet Trefferquote, Schwellenwert: 50 %.
    """
    expected = fixture["expected"]
    transcript = str(fixture["transcript"])
    fixture_id = str(fixture["id"])

    if real_llm:
        # Echter LLM: Trefferquote berechnen
        settings = Settings()
        repo = _make_repo()
        result = run_extraction(transcript, repo, settings)

        hits, total = _score_result(result, expected)
        score = hits / total if total > 0 else 1.0

        print(f"\n[EVAL] {fixture_id}: {hits}/{total} = {score:.0%}")
        for c in result.contacts:
            print(f"  Kontakt : {c.name}")
        for t in result.tasks:
            due = f" (fällig: {t.due})" if t.due else ""
            print(f"  Aufgabe : {t.title}{due}")
        for pu in result.project_updates:
            status = f" → {pu.status}" if pu.status else ""
            print(f"  Projekt : {pu.project}{status}")

        assert score >= _QUALITY_THRESHOLD, (
            f"Fixture '{fixture_id}': Trefferquote {score:.0%} unter Schwellenwert "
            f"{_QUALITY_THRESHOLD:.0%} ({hits}/{total})"
        )

    else:
        # CI-Modus: FunctionModel-Mock
        mock_result = _mock_result_from_expected(expected)
        model = _make_mock_model(mock_result)
        repo = _make_repo()

        run_result = agent.run_sync(transcript, model=model, deps=repo)
        out = run_result.output

        assert isinstance(out, ExtractionResult)
        assert len(out.contacts) >= int(expected.get("min_contacts", 0)), (
            f"Fixture '{fixture_id}': zu wenige Kontakte "
            f"({len(out.contacts)} < {expected.get('min_contacts', 0)})"
        )
        assert len(out.tasks) >= int(expected.get("min_tasks", 0)), (
            f"Fixture '{fixture_id}': zu wenige Tasks "
            f"({len(out.tasks)} < {expected.get('min_tasks', 0)})"
        )
        assert len(out.project_updates) >= int(expected.get("min_project_updates", 0)), (
            f"Fixture '{fixture_id}': zu wenige Projektupdates "
            f"({len(out.project_updates)} < {expected.get('min_project_updates', 0)})"
        )
