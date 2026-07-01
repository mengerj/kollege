"""Eval-Set für Extraktions- **und** Revisions-Qualität (Schritt 8.10 / 8.11).

Fixtures in ``tests/fixtures/eval/*.json`` (Erstextraktion) und
``tests/fixtures/eval_revision/*.json`` (Korrektur-/Revisions-Schleife, 8.6).
Laden, Schema und Scoring leben in ``kollege.eval`` (Single Source of Truth,
gemeinsam mit ``scripts/benchmark_models.py`` genutzt) — hier nur die
pytest-Verdrahtung.

Modi:
- **CI (Standard):** ``FunctionModel``-Mock gibt erwartetes Ergebnis zurück.
  Validiert Schema-Konformität und Mindestanzahlen ohne echtes LLM.
- **Real-LLM:** ``pytest -m eval --real-llm`` — echter Ollama/Anthropic-Aufruf
  über den Produktions-Pfad (``run_extraction`` / ``run_revision``). Berechnet
  die Trefferquote pro Fixture (Schwellenwert siehe ``kollege.eval.DEFAULT_THRESHOLD``).
  Ein einzelner Lauf macht Flakiness nicht sichtbar — dafür ist
  ``scripts/benchmark_models.py --runs N`` gedacht.

Ausführen:
    pytest -m eval            # CI-Modus (FunctionModel, schnell)
    pytest -m eval --real-llm # Real-LLM-Modus (Trefferquote)
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from kollege.agent import agent, build_known_names_context, run_extraction, run_revision
from kollege.config import Settings
from kollege.db import Repository
from kollege.eval import (
    DEFAULT_THRESHOLD,
    ExtractionExpectation,
    ExtractionFixture,
    RevisionFixture,
    load_extraction_fixtures,
    load_revision_fixtures,
    score_result,
)
from kollege.models import (
    ExtractedContact,
    ExtractedProjectUpdate,
    ExtractedTask,
    ExtractionResult,
)

# --------------------------------------------------------------------------- #
# Fixtures laden                                                                #
# --------------------------------------------------------------------------- #

_EXTRACTION_DIR = Path(__file__).parent / "fixtures" / "eval"
_REVISION_DIR = Path(__file__).parent / "fixtures" / "eval_revision"

_EXTRACTION_FIXTURES = load_extraction_fixtures(_EXTRACTION_DIR)
_EXTRACTION_IDS = [f.id for f in _EXTRACTION_FIXTURES]

_REVISION_FIXTURES = load_revision_fixtures(_REVISION_DIR)
_REVISION_IDS = [f.id for f in _REVISION_FIXTURES]

# --------------------------------------------------------------------------- #
# Hilfsfunktionen                                                               #
# --------------------------------------------------------------------------- #


def _make_repo() -> Repository:
    return Repository(sqlite3.connect(":memory:", check_same_thread=False))


def _mock_result_from_expected(expected: ExtractionExpectation) -> ExtractionResult:
    """Erzeugt ein minimales ExtractionResult, das alle Mindestanforderungen erfüllt."""
    contact_names = list(expected.contact_names)
    while len(contact_names) < expected.min_contacts:
        contact_names.append(f"Kontakt {len(contact_names) + 1}")
    contacts = [ExtractedContact(name=n) for n in contact_names]

    task_titles = list(expected.task_keywords)[: expected.min_tasks]
    while len(task_titles) < expected.min_tasks:
        task_titles.append(f"Aufgabe {len(task_titles) + 1}")
    tasks = [ExtractedTask(title=t) for t in task_titles]

    project_names = list(expected.project_names)
    while len(project_names) < expected.min_project_updates:
        project_names.append(f"Projekt {len(project_names) + 1}")
    updates = [ExtractedProjectUpdate(project=p) for p in project_names]

    return ExtractionResult(contacts=contacts, tasks=tasks, project_updates=updates)


def _make_mock_model(result: ExtractionResult) -> FunctionModel:
    """FunctionModel, das ein vorgegebenes ExtractionResult zurückgibt."""
    result_json = result.model_dump_json()

    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[ToolCallPart(tool_name="final_result", args=result_json)])

    return FunctionModel(fn)


def _print_result(fixture_id: str, result: ExtractionResult, score_pct: float) -> None:
    print(f"\n[EVAL] {fixture_id}: {score_pct:.0%}")
    for c in result.contacts:
        print(f"  Kontakt : {c.name}")
    for t in result.tasks:
        due = f" (fällig: {t.due})" if t.due else ""
        print(f"  Aufgabe : {t.title}{due}")
    for pu in result.project_updates:
        status = f" → {pu.status}" if pu.status else ""
        print(f"  Projekt : {pu.project}{status}")
    if result.clarification:
        print(f"  Rückfrage: {result.clarification}")


# --------------------------------------------------------------------------- #
# Extraktions-Eval                                                             #
# --------------------------------------------------------------------------- #


@pytest.mark.eval
@pytest.mark.parametrize("fixture", _EXTRACTION_FIXTURES, ids=_EXTRACTION_IDS)
def test_eval_extraction(fixture: ExtractionFixture, real_llm: bool) -> None:
    """Extraktions-Eval: CI mit FunctionModel-Mock, manuell mit echtem LLM."""
    if real_llm:
        settings = Settings()
        repo = _make_repo()
        result = run_extraction(fixture.transcript, repo, settings)

        score = score_result(result, fixture.expected)
        _print_result(fixture.id, result, score.score)

        assert score.passed(DEFAULT_THRESHOLD), (
            f"Fixture '{fixture.id}': Trefferquote {score.score:.0%} "
            f"(hits={score.hits}/{score.total}), empty={score.empty}, "
            f"over_extraction={score.over_extraction}, forbidden_hit={score.forbidden_hit}"
        )

    else:
        # CI-Modus: FunctionModel-Mock — Schema + Mindest-Counts.
        mock_result = _mock_result_from_expected(fixture.expected)
        model = _make_mock_model(mock_result)
        repo = _make_repo()

        run_result = agent.run_sync(fixture.transcript, model=model, deps=repo)
        out = run_result.output

        assert isinstance(out, ExtractionResult)
        assert len(out.contacts) >= fixture.expected.min_contacts
        assert len(out.tasks) >= fixture.expected.min_tasks
        assert len(out.project_updates) >= fixture.expected.min_project_updates


# --------------------------------------------------------------------------- #
# Revisions-Eval (Schritt 8.11)                                                #
# --------------------------------------------------------------------------- #


@pytest.mark.eval
@pytest.mark.parametrize("fixture", _REVISION_FIXTURES, ids=_REVISION_IDS)
def test_eval_revision(fixture: RevisionFixture, real_llm: bool) -> None:
    """Revisions-Eval: CI mit FunctionModel-Mock, manuell mit echtem run_revision().

    Deckt die real beobachtete Fehlerklasse aus 8.11 ab: eine natürlichsprachige
    Korrektur (Schritt 8.6, Quote-Reply) muss zuverlässig ein nicht-leeres,
    korrigiertes Ergebnis liefern statt „nichts erkannt".
    """
    if real_llm:
        settings = Settings()
        known_context = (
            build_known_names_context(fixture.known_names, []) if fixture.known_names else None
        )
        result = run_revision(
            fixture.original_transcript,
            fixture.current_result,
            fixture.correction,
            settings,
            known_names_context=known_context,
        )

        score = score_result(result, fixture.expected)
        _print_result(fixture.id, result, score.score)

        assert score.passed(DEFAULT_THRESHOLD), (
            f"Fixture '{fixture.id}': Trefferquote {score.score:.0%} "
            f"(hits={score.hits}/{score.total}), empty={score.empty}, "
            f"over_extraction={score.over_extraction}, forbidden_hit={score.forbidden_hit}"
        )

    else:
        # CI-Modus: FunctionModel-Mock — Schema + Mindest-Counts, kein Fehlerklassen-Check
        # (der ist per Definition nur mit einem echten, potenziell flakigen Modell sichtbar).
        mock_result = _mock_result_from_expected(fixture.expected)
        model = _make_mock_model(mock_result)
        repo = _make_repo()

        run_result = agent.run_sync(
            f"[KORREKTUR-LAUF]\n{fixture.original_transcript}\n{fixture.correction}",
            model=model,
            deps=repo,
        )
        out = run_result.output

        assert isinstance(out, ExtractionResult)
        assert len(out.contacts) >= fixture.expected.min_contacts
        assert len(out.tasks) >= fixture.expected.min_tasks
        assert len(out.project_updates) >= fixture.expected.min_project_updates
