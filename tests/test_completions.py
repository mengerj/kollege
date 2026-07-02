"""Tests für Erledigungen aus Freitext erkennen & abgleichen (Schritt 8.17).

Strategie:
- ``build_open_tasks_context`` / ``get_open_tasks_context`` ohne LLM testbar.
- ``run_extraction`` mit Aufgaben-Kontext über ``FunctionModel`` (kein echter LLM),
  einmal als Prompt-Injektions-Check, einmal als vollständiger Abgleichs-Test
  (Schritt-8.17-DoD): Erledigungs-Notiz + passende offene Aufgabe → ``completed``.
- ``dedupe_result``/``persist_result`` gegen In-Memory-Repo.
- Orchestrator-Integration end-to-end (gemockte ``run_extraction``, wie in
  ``test_orchestrator.py``): Erledigungs-Notiz → "schließen"-Vorschlag →
  Bestätigung → Task-Status erledigt; unsichere Zuordnung → Rückfrage statt
  falsches Schließen.

Kein echter LLM-Aufruf, kein Netzwerk: CI-sicher.
"""

from __future__ import annotations

import datetime
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from kollege.agent import build_open_tasks_context, get_open_tasks_context, run_extraction
from kollege.channels import IncomingMessage, MemoryChannel
from kollege.config import Settings
from kollege.db import Repository
from kollege.models import (
    ExtractedCompletion,
    ExtractionResult,
    Task,
    TaskSource,
    TaskStatus,
)
from kollege.orchestrator import Orchestrator, dedupe_result, persist_result

SENDER = "+491234567890"


def _repo() -> Repository:
    return Repository(sqlite3.connect(":memory:", check_same_thread=False))


@pytest.fixture
def log_dir(tmp_path: Path) -> Path:
    return tmp_path / "logs"


def _orc(repo: Repository, channel: MemoryChannel, log_dir: Path) -> Orchestrator:
    return Orchestrator(
        channel=channel,
        repo=repo,
        transcriber=None,
        settings=Settings(),
        log_dir=log_dir,
    )


# ---------------------------------------------------------------------------
# build_open_tasks_context
# ---------------------------------------------------------------------------


def test_build_open_tasks_context_empty() -> None:
    assert build_open_tasks_context([]) == ""


def test_build_open_tasks_context_lists_id_and_title() -> None:
    task = Task(
        id=3, title="Zaun bei Müller streichen", status=TaskStatus.OFFEN, source=TaskSource.MANUELL
    )
    ctx = build_open_tasks_context([task])
    assert "#3" in ctx
    assert "Zaun bei Müller streichen" in ctx
    assert "OFFENE AUFGABEN" in ctx


def test_build_open_tasks_context_shows_due_date() -> None:
    task = Task(
        id=1,
        title="Angebot senden",
        due=datetime.date(2026, 7, 10),
        status=TaskStatus.OFFEN,
        source=TaskSource.MANUELL,
    )
    ctx = build_open_tasks_context([task])
    assert "2026-07-10" in ctx


def test_build_open_tasks_context_contains_matching_hint() -> None:
    task = Task(id=1, title="Rasen mähen", status=TaskStatus.OFFEN, source=TaskSource.MANUELL)
    ctx = build_open_tasks_context([task])
    assert "completed" in ctx
    assert "clarification" in ctx


# ---------------------------------------------------------------------------
# get_open_tasks_context
# ---------------------------------------------------------------------------


def test_get_open_tasks_context_empty_repo() -> None:
    repo = _repo()
    assert get_open_tasks_context(repo) == ""


def test_get_open_tasks_context_with_open_task() -> None:
    repo = _repo()
    repo.create_task(Task(title="Rasen mähen", status=TaskStatus.OFFEN, source=TaskSource.MANUELL))
    ctx = get_open_tasks_context(repo)
    assert "Rasen mähen" in ctx


def test_get_open_tasks_context_excludes_done_tasks() -> None:
    repo = _repo()
    t = repo.create_task(
        Task(title="Schon erledigt", status=TaskStatus.OFFEN, source=TaskSource.MANUELL)
    )
    assert t.id is not None
    repo.mark_task_done(t.id)
    assert get_open_tasks_context(repo) == ""


# ---------------------------------------------------------------------------
# run_extraction mit open_tasks_context
# ---------------------------------------------------------------------------


def _capture_model(captured: list[str], result: ExtractionResult | None = None) -> FunctionModel:
    result_json = (result or ExtractionResult()).model_dump_json()

    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        for msg in messages:
            for part in msg.parts:
                if hasattr(part, "content"):
                    captured.append(str(part.content))
        return ModelResponse(parts=[ToolCallPart(tool_name="final_result", args=result_json)])

    return FunctionModel(fn)


def test_run_extraction_with_open_tasks_injects_context() -> None:
    captured: list[str] = []
    repo = _repo()
    settings = Settings()
    model = _capture_model(captured)
    open_tasks = build_open_tasks_context(
        [Task(id=5, title="Zaun streichen", status=TaskStatus.OFFEN, source=TaskSource.MANUELL)]
    )

    with patch("kollege.agent.build_model", return_value=model):
        run_extraction(
            "Den Zaun bei Müller hab ich heute fertig gestrichen.",
            repo,
            settings,
            open_tasks_context=open_tasks,
        )

    full = " ".join(captured)
    assert "#5" in full
    assert "Zaun streichen" in full
    assert "Zaun bei Müller" in full


def test_run_extraction_empty_open_tasks_context_no_injection() -> None:
    """Leerer Kontext → Transkript wird unverändert übergeben (kein Wrapper)."""
    captured: list[str] = []
    repo = _repo()
    settings = Settings()
    model = _capture_model(captured)

    with patch("kollege.agent.build_model", return_value=model):
        run_extraction("Reine Notiz", repo, settings, open_tasks_context="")

    full = " ".join(captured)
    assert "Reine Notiz" in full
    assert "OFFENE AUFGABEN" not in full


def test_run_extraction_function_model_detects_completion() -> None:
    """FunctionModel-Test (Schritt 8.17 DoD): Eine Erledigungs-Notiz mit passender
    offener Aufgabe im Kontext liefert ein ExtractionResult mit passendem
    completed-Eintrag — task_id wird aus dem Kontext übernommen, nicht geraten.
    """
    repo = _repo()
    settings = Settings()

    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        full = " ".join(
            str(part.content) for msg in messages for part in msg.parts if hasattr(part, "content")
        )
        completed = []
        if "#7" in full and "Zaun bei Müller streichen" in full and "gestrichen" in full:
            completed = [ExtractedCompletion(task_id=7, task_title="Zaun bei Müller streichen")]
        result = ExtractionResult(completed=completed)
        return ModelResponse(
            parts=[ToolCallPart(tool_name="final_result", args=result.model_dump_json())]
        )

    model = FunctionModel(fn)
    open_tasks = build_open_tasks_context(
        [
            Task(
                id=7,
                title="Zaun bei Müller streichen",
                status=TaskStatus.OFFEN,
                source=TaskSource.MANUELL,
            )
        ]
    )

    with patch("kollege.agent.build_model", return_value=model):
        result = run_extraction(
            "Den Zaun bei Müller hab ich heute gestrichen.",
            repo,
            settings,
            open_tasks_context=open_tasks,
        )

    assert len(result.completed) == 1
    assert result.completed[0].task_id == 7
    assert result.completed[0].task_title == "Zaun bei Müller streichen"


# ---------------------------------------------------------------------------
# dedupe_result / persist_result mit completed
# ---------------------------------------------------------------------------


def test_dedupe_result_dedups_completions() -> None:
    result = ExtractionResult(
        completed=[
            ExtractedCompletion(task_id=1, task_title="Zaun streichen"),
            ExtractedCompletion(task_id=1, task_title="Zaun streichen"),
        ]
    )
    deduped = dedupe_result(result)
    assert len(deduped.completed) == 1


def test_persist_result_completion_marks_task_done(log_dir: Path) -> None:
    repo = _repo()
    task = repo.create_task(
        Task(title="Zaun streichen", status=TaskStatus.OFFEN, source=TaskSource.MANUELL)
    )
    assert task.id is not None
    result = ExtractionResult(
        completed=[ExtractedCompletion(task_id=task.id, task_title=task.title)]
    )

    count = persist_result(result, None, repo, log_dir)

    assert count == 1
    assert repo.query_open_items() == []


def test_persist_result_completion_unknown_task_id_is_skipped(log_dir: Path) -> None:
    """Verschwundene/bereits erledigte Aufgabe: übersprungen statt Absturz."""
    repo = _repo()
    result = ExtractionResult(completed=[ExtractedCompletion(task_id=999, task_title="Nicht da")])

    count = persist_result(result, None, repo, log_dir)

    assert count == 0


# ---------------------------------------------------------------------------
# Orchestrator-Integration (Schritt 8.17 DoD)
# ---------------------------------------------------------------------------


def test_completion_note_creates_close_proposal(log_dir: Path) -> None:
    repo = _repo()
    task = repo.create_task(
        Task(title="Zaun bei Müller streichen", status=TaskStatus.OFFEN, source=TaskSource.MANUELL)
    )
    assert task.id is not None
    channel = MemoryChannel()
    orc = _orc(repo, channel, log_dir)

    fake_result = ExtractionResult(
        completed=[ExtractedCompletion(task_id=task.id, task_title=task.title)]
    )
    with patch("kollege.orchestrator.run_extraction", return_value=fake_result):
        orc.handle_message(
            IncomingMessage(sender=SENDER, text="Den Zaun bei Müller hab ich fertig gestrichen.")
        )

    assert SENDER in orc._pending
    proposal_text = channel.sent[-1][1]
    assert "schließen" in proposal_text.lower()
    assert f"#{task.id}" in proposal_text
    assert repo.query_open_items() != []  # noch nicht persistiert


def test_confirming_completion_marks_task_erledigt(log_dir: Path) -> None:
    repo = _repo()
    task = repo.create_task(
        Task(title="Angebot verschicken", status=TaskStatus.OFFEN, source=TaskSource.MANUELL)
    )
    assert task.id is not None
    channel = MemoryChannel()
    orc = _orc(repo, channel, log_dir)

    fake_result = ExtractionResult(
        completed=[ExtractedCompletion(task_id=task.id, task_title=task.title)]
    )
    with patch("kollege.orchestrator.run_extraction", return_value=fake_result):
        orc.handle_message(IncomingMessage(sender=SENDER, text="Angebot ist raus."))
    channel.sent.clear()

    orc.handle_message(IncomingMessage(sender=SENDER, text="ja"))

    assert "✅" in channel.sent[0][1]
    assert repo.query_open_items() == []
    assert SENDER not in orc._pending


def test_ambiguous_completion_asks_clarification_instead_of_closing(log_dir: Path) -> None:
    """Ohne guten Treffer stellt die Extraktion eine Rückfrage — nichts wird
    automatisch geschlossen (Vertrauensschutz, Designprinzip 3)."""
    repo = _repo()
    task = repo.create_task(
        Task(title="Angebot Müller", status=TaskStatus.OFFEN, source=TaskSource.MANUELL)
    )
    repo.create_task(
        Task(title="Angebot Meier", status=TaskStatus.OFFEN, source=TaskSource.MANUELL)
    )
    assert task.id is not None
    channel = MemoryChannel()
    orc = _orc(repo, channel, log_dir)

    fake_result = ExtractionResult(clarification="Meinst du das Angebot für Müller oder für Meier?")
    with patch("kollege.orchestrator.run_extraction", return_value=fake_result):
        orc.handle_message(IncomingMessage(sender=SENDER, text="Das Angebot ist raus."))

    assert SENDER not in orc._pending
    assert SENDER in orc._pending_clarifications
    assert "Rückfrage" in channel.sent[-1][1]
    assert len(repo.query_open_items()) == 2  # nichts geschlossen
