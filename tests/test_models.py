"""Tests für die Domänen- und Extraktionsmodelle."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from kollege.models import (
    Contact,
    ContactType,
    ExtractedTask,
    ExtractionResult,
    Project,
    ProjectStatus,
    Task,
    TaskSource,
    TaskStatus,
    WaitingOn,
)


def test_contact_minimal_requires_only_name() -> None:
    c = Contact(name="Familie Müller")
    assert c.id is None
    assert c.name == "Familie Müller"
    assert c.type is None
    assert c.created_at == c.updated_at or c.created_at <= c.updated_at


def test_contact_type_enum_validates() -> None:
    c = Contact(name="Gemeinde Musterhausen", type=ContactType.GEMEINDE)
    assert c.type is ContactType.GEMEINDE
    with pytest.raises(ValidationError):
        Contact(name="x", type="unsinn")


def test_project_defaults_to_anfrage() -> None:
    p = Project(title="Garten Müller")
    assert p.status is ProjectStatus.ANFRAGE
    assert p.waiting_on is None


def test_project_waiting_on_for_followup_question() -> None:
    p = Project(title="Park Gemeinde", waiting_on=WaitingOn.KUNDE)
    assert p.waiting_on is WaitingOn.KUNDE


def test_task_defaults() -> None:
    t = Task(title="Pflanzplan zeichnen")
    assert t.status is TaskStatus.OFFEN
    assert t.source is TaskSource.MANUELL
    assert t.depends_on == []


def test_task_depends_on_and_window() -> None:
    t = Task(
        title="Wiese mähen",
        depends_on=[1, 2],
        time_window="vor der ersten Mahd, ca. Mai–Juni",
        window_start=date(2026, 5, 1),
        window_end=date(2026, 6, 30),
    )
    assert t.depends_on == [1, 2]
    assert t.window_end == date(2026, 6, 30)


def test_extracted_task_parses_due_date() -> None:
    t = ExtractedTask(title="Angebot senden", due=date(2026, 7, 5), contact="Müller")
    assert t.due == date(2026, 7, 5)


def test_extraction_result_empty_helper() -> None:
    assert ExtractionResult().is_empty() is True
    assert ExtractionResult(tasks=[ExtractedTask(title="x")]).is_empty() is False


def test_extraction_result_can_request_clarification() -> None:
    r = ExtractionResult(clarification="Meinst du Familie Müller oder Gemeinde Müller?")
    assert r.is_empty() is True
    assert r.clarification is not None
