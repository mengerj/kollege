"""Tests für die Domänen- und Extraktionsmodelle."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from kollege.models import (
    Contact,
    ContactType,
    ExtractedCompletion,
    ExtractedContact,
    ExtractedOrt,
    ExtractedProjectUpdate,
    ExtractedTask,
    ExtractedTaskEdit,
    ExtractionResult,
    Ort,
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


def test_ort_minimal_requires_only_name() -> None:
    o = Ort(name="Flurstück 12")
    assert o.id is None
    assert o.adresse is None
    assert o.flurnummer is None


def test_ort_with_adresse_and_flurnummer() -> None:
    o = Ort(name="Garten Hinterberger", adresse="Seestraße 7", flurnummer="118")
    assert o.adresse == "Seestraße 7"
    assert o.flurnummer == "118"


def test_extracted_ort_optional_links() -> None:
    loc = ExtractedOrt(name="Streuobstwiese Berger", contact="Familie Berger")
    assert loc.contact == "Familie Berger"
    assert loc.project is None


def test_contact_and_project_default_ort_id_none() -> None:
    assert Contact(name="Familie Müller").ort_id is None
    assert Project(title="Garten Müller").ort_id is None


def test_extraction_result_locations_counts_toward_is_empty() -> None:
    assert ExtractionResult(locations=[ExtractedOrt(name="Flurstück 12")]).is_empty() is False


# ---------------------------------------------------------------------------
# has_gap_check_candidates (Schritt 8.23 — Gap-Check-Gating)
# ---------------------------------------------------------------------------


def test_has_gap_check_candidates_false_when_completely_empty() -> None:
    assert ExtractionResult().has_gap_check_candidates() is False


def test_has_gap_check_candidates_false_for_pure_completion_note() -> None:
    """Eine reine Erledigungs-Notiz (nur completed) hat für den Gap-Check nichts zu
    prüfen (Live-Trace 2026-07-03, siehe ROADMAP.md Schritt 8.23)."""
    result = ExtractionResult(
        completed=[
            ExtractedCompletion(task_id=1, task_title="Zaun streichen"),
            ExtractedCompletion(task_id=2, task_title="Angebot senden"),
        ]
    )
    assert result.has_gap_check_candidates() is False


def test_has_gap_check_candidates_false_for_pure_edit_note() -> None:
    result = ExtractionResult(
        edits=[ExtractedTaskEdit(task_id=1, task_title="Zaun streichen", new_due=date(2026, 7, 20))]
    )
    assert result.has_gap_check_candidates() is False


@pytest.mark.parametrize(
    "result",
    [
        ExtractionResult(contacts=[ExtractedContact(name="Müller")]),
        ExtractionResult(tasks=[ExtractedTask(title="Angebot schicken")]),
        ExtractionResult(project_updates=[ExtractedProjectUpdate(project="Stadtpark")]),
        ExtractionResult(locations=[ExtractedOrt(name="Flurstück 12")]),
    ],
)
def test_has_gap_check_candidates_true_for_core_categories(result: ExtractionResult) -> None:
    assert result.has_gap_check_candidates() is True
