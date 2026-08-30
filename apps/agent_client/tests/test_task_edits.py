"""Tests für „Aufgabe bearbeiten" — Änderungen an bestehenden Aufgaben (Schritt 8.19).

Motiviert durch einen Live-Test: Aufgabe #6 hatte „Bad Eibling" statt „Bad Aibling".
Die Nutzerin wollte den Eintrag per Notiz korrigieren — bisher konnte das Modell das
nicht ausdrücken (kein Schema-Feld, keine Repo-Methode) und lieferte „nichts erkannt".

Strategie analog zu ``test_completions.py`` (Schritt 8.17):
- ``run_extraction`` mit Aufgaben-Kontext über ``FunctionModel`` (kein echter LLM).
- ``dedupe_result``/``persist_result``/``_result_items`` gegen In-Memory-Repo.
- Orchestrator-Integration end-to-end (gemockte ``run_extraction``): Edit-Notiz →
  „ändern"-Vorschlag → Bestätigung → Titel in der DB geändert.
- Kontext-Durchreichung in Rückfrage-/Korrektur-Läufen (der Live-Pfad).

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

from kollege.agent import build_open_tasks_context, run_extraction
from kollege.channels import IncomingMessage, MemoryChannel
from kollege.config import Settings
from kollege.db import Repository
from kollege.logs import open_project_log
from kollege.models import (
    ExtractedTaskEdit,
    ExtractionResult,
    Task,
    TaskSource,
    TaskStatus,
)
from kollege.orchestrator import (
    Orchestrator,
    dedupe_result,
    format_proposal,
    persist_result,
)

SENDER = "+491234567890"


def _repo() -> Repository:
    return Repository(sqlite3.connect(":memory:", check_same_thread=False))


@pytest.fixture(autouse=True)
def _passthrough_gap_check() -> object:
    """Zweiten Durchgang (Schritt 8.18) als Passthrough neutralisieren (wie 8.17-Tests)."""
    with patch(
        "kollege.orchestrator.run_gap_check",
        side_effect=lambda original_transcript, first_result, *a, **k: first_result,
    ):
        yield


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
# run_extraction — Edit-Erkennung via FunctionModel
# ---------------------------------------------------------------------------


def test_run_extraction_function_model_detects_edit() -> None:
    """DoD: Eine Korrektur-Notiz mit passender offener Aufgabe im Kontext liefert
    ein ExtractionResult mit einem edits-Eintrag — task_id aus dem Kontext, nicht
    geraten; nur das geänderte Feld (Titel) ist gesetzt.
    """
    repo = _repo()
    settings = Settings()

    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        full = " ".join(
            str(part.content) for msg in messages for part in msg.parts if hasattr(part, "content")
        )
        edits = []
        if "#6" in full and "Bad Eibling begehen" in full and "Bad Aibling" in full:
            edits = [
                ExtractedTaskEdit(
                    task_id=6,
                    task_title="Bad Eibling begehen",
                    new_title="Bad Aibling begehen",
                )
            ]
        result = ExtractionResult(edits=edits)
        return ModelResponse(
            parts=[ToolCallPart(tool_name="final_result", args=result.model_dump_json())]
        )

    model = FunctionModel(fn)
    open_tasks = build_open_tasks_context(
        [
            Task(
                id=6,
                title="Bad Eibling begehen",
                status=TaskStatus.OFFEN,
                source=TaskSource.MANUELL,
            )
        ]
    )

    with patch("kollege.agent.build_model", return_value=model):
        result = run_extraction(
            "Die Aufgabe Bad Eibling begehen heißt eigentlich Bad Aibling begehen.",
            repo,
            settings,
            open_tasks_context=open_tasks,
        )

    assert len(result.edits) == 1
    assert result.edits[0].task_id == 6
    assert result.edits[0].new_title == "Bad Aibling begehen"
    assert result.edits[0].new_due is None  # unverändert bleibt leer


# ---------------------------------------------------------------------------
# dedupe_result / _result_items / format_proposal mit edits
# ---------------------------------------------------------------------------


def test_dedupe_result_dedups_edits_by_task_id() -> None:
    result = ExtractionResult(
        edits=[
            ExtractedTaskEdit(task_id=6, task_title="Alt", new_title="Neu"),
            ExtractedTaskEdit(task_id=6, task_title="Alt", new_title="Neu"),
        ]
    )
    deduped = dedupe_result(result)
    assert len(deduped.edits) == 1


def test_proposal_shows_edit_with_changes() -> None:
    result = ExtractionResult(
        edits=[
            ExtractedTaskEdit(
                task_id=6,
                task_title="Bad Eibling begehen",
                new_title="Bad Aibling begehen",
                new_due=datetime.date(2026, 7, 10),
            )
        ]
    )
    text = format_proposal(result)
    assert "✏️" in text
    assert "#6" in text
    assert "Bad Aibling begehen" in text  # Zieltitel sichtbar VOR Bestätigung
    assert "Fr. 10. Juli 2026" in text  # geänderte Frist, deutsch


# ---------------------------------------------------------------------------
# persist_result mit edits
# ---------------------------------------------------------------------------


def test_persist_result_edit_changes_title(log_dir: Path) -> None:
    repo = _repo()
    task = repo.create_task(
        Task(title="Bad Eibling begehen", status=TaskStatus.OFFEN, source=TaskSource.MANUELL)
    )
    assert task.id is not None
    result = ExtractionResult(
        edits=[
            ExtractedTaskEdit(
                task_id=task.id, task_title=task.title, new_title="Bad Aibling begehen"
            )
        ]
    )

    summary = persist_result(result, None, repo, log_dir)

    assert summary.count == 1
    open_items = repo.query_open_items()
    assert len(open_items) == 1
    assert open_items[0].title == "Bad Aibling begehen"
    assert open_items[0].status is TaskStatus.OFFEN  # bleibt offen


def test_persist_result_edit_unknown_task_id_is_skipped(log_dir: Path) -> None:
    repo = _repo()
    result = ExtractionResult(
        edits=[ExtractedTaskEdit(task_id=999, task_title="Nicht da", new_title="egal")]
    )

    summary = persist_result(result, None, repo, log_dir)

    assert summary.count == 0


def test_persist_result_edit_appends_correction_to_project_log(log_dir: Path) -> None:
    """Hängt die Aufgabe an einem Projekt mit Log, wird die Korrektur append-only vermerkt."""
    repo = _repo()
    project = repo.get_or_create_project("Gemeinde-Sache")
    assert project.id is not None
    open_project_log(project, log_dir)  # legt markdown_log_path an
    repo.update_project(project)
    task = repo.create_task(
        Task(
            title="Bad Eibling begehen",
            project_id=project.id,
            status=TaskStatus.OFFEN,
            source=TaskSource.MANUELL,
        )
    )
    assert task.id is not None
    result = ExtractionResult(
        edits=[
            ExtractedTaskEdit(
                task_id=task.id, task_title=task.title, new_title="Bad Aibling begehen"
            )
        ]
    )

    persist_result(result, None, repo, log_dir)

    log_files = list(log_dir.glob("*.md"))
    assert len(log_files) == 1
    content = log_files[0].read_text(encoding="utf-8")
    assert "Aufgabe geändert" in content
    assert "Bad Aibling begehen" in content


# ---------------------------------------------------------------------------
# Orchestrator-Integration (Schritt 8.19 DoD)
# ---------------------------------------------------------------------------


def test_edit_note_creates_edit_proposal(log_dir: Path) -> None:
    repo = _repo()
    task = repo.create_task(
        Task(title="Bad Eibling begehen", status=TaskStatus.OFFEN, source=TaskSource.MANUELL)
    )
    assert task.id is not None
    channel = MemoryChannel()
    orc = _orc(repo, channel, log_dir)

    fake_result = ExtractionResult(
        edits=[
            ExtractedTaskEdit(
                task_id=task.id, task_title=task.title, new_title="Bad Aibling begehen"
            )
        ]
    )
    with patch("kollege.orchestrator.run_extraction", return_value=fake_result):
        orc.handle_message(
            IncomingMessage(sender=SENDER, text="Bad Eibling heißt eigentlich Bad Aibling.")
        )

    assert SENDER in orc._pending
    proposal_text = channel.sent[-1][1]
    assert "ändern" in proposal_text.lower()
    assert f"#{task.id}" in proposal_text
    # Noch nicht persistiert — Titel unverändert bis zur Bestätigung
    assert repo.query_open_items()[0].title == "Bad Eibling begehen"


def test_confirming_edit_changes_task_in_db(log_dir: Path) -> None:
    repo = _repo()
    task = repo.create_task(
        Task(title="Bad Eibling begehen", status=TaskStatus.OFFEN, source=TaskSource.MANUELL)
    )
    assert task.id is not None
    channel = MemoryChannel()
    orc = _orc(repo, channel, log_dir)

    fake_result = ExtractionResult(
        edits=[
            ExtractedTaskEdit(
                task_id=task.id, task_title=task.title, new_title="Bad Aibling begehen"
            )
        ]
    )
    with patch("kollege.orchestrator.run_extraction", return_value=fake_result):
        orc.handle_message(IncomingMessage(sender=SENDER, text="Tippfehler korrigieren"))
    channel.sent.clear()

    orc.handle_message(IncomingMessage(sender=SENDER, text="ja"))

    assert "✅" in channel.sent[0][1]
    assert repo.query_open_items()[0].title == "Bad Aibling begehen"
    assert SENDER not in orc._pending


# ---------------------------------------------------------------------------
# Kontext-Durchreichung in Rückfrage-/Korrektur-Läufen (der Live-Bug-Pfad)
# ---------------------------------------------------------------------------


def test_answer_clarification_passes_open_tasks_context(log_dir: Path) -> None:
    """Live-Bug: Der Rückfrage-Antwort-Lauf muss den Offene-Aufgaben-Kontext mitgeben,
    sonst kann das Modell die zu ändernde Aufgabe (#id) nach dem 👍 nicht referenzieren.
    """
    repo = _repo()
    repo.create_task(
        Task(title="Bad Eibling begehen", status=TaskStatus.OFFEN, source=TaskSource.MANUELL)
    )
    channel = MemoryChannel()
    orc = _orc(repo, channel, log_dir)

    # Erst eine Rückfrage erzeugen
    with patch(
        "kollege.orchestrator.run_extraction",
        return_value=ExtractionResult(clarification="Soll ich den Titel auf Bad Aibling ändern?"),
    ):
        orc.handle_message(IncomingMessage(sender=SENDER, text="Bad Eibling ist falsch"))
    assert SENDER in orc._pending_clarifications

    captured: dict[str, object] = {}

    def _capture(*args: object, **kwargs: object) -> ExtractionResult:
        captured.update(kwargs)
        return ExtractionResult()

    with patch("kollege.orchestrator.run_clarification_response", side_effect=_capture):
        orc.handle_message(IncomingMessage(sender=SENDER, text="Ja."))

    ctx = captured.get("open_tasks_context")
    assert isinstance(ctx, str)
    assert "Bad Eibling begehen" in ctx  # Kontext mit der offenen Aufgabe wurde gereicht
