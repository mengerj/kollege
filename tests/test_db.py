"""Tests für den SQLite-Persistenz-Layer (Repository).

Alle Tests laufen gegen In-Memory-SQLite (:memory:) — kein Dateisystem nötig.
"""

from __future__ import annotations

import sqlite3
from datetime import date

import pytest

from kollege.db import Repository, open_repository
from kollege.models import (
    ContactType,
    ExtractedContact,
    Project,
    ProjectStatus,
    Task,
    TaskSource,
    TaskStatus,
    WaitingOn,
)


@pytest.fixture
def repo() -> Repository:
    """Frisches In-Memory-Repository pro Test."""
    conn = sqlite3.connect(":memory:")
    return Repository(conn)


# --------------------------------------------------------------------------- #
# Schema                                                                        #
# --------------------------------------------------------------------------- #


def test_schema_creates_tables(repo: Repository) -> None:
    tables = {
        r[0]
        for r in repo._conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert {"contacts", "projects", "tasks"}.issubset(tables)


# --------------------------------------------------------------------------- #
# Contacts                                                                      #
# --------------------------------------------------------------------------- #


def test_upsert_contact_creates_new(repo: Repository) -> None:
    contact = repo.upsert_contact(ExtractedContact(name="Familie Müller", type=ContactType.PRIVAT))
    assert contact.id is not None
    assert contact.name == "Familie Müller"
    assert contact.type is ContactType.PRIVAT


def test_upsert_contact_dedup_same_name_updates_fields(repo: Repository) -> None:
    repo.upsert_contact(ExtractedContact(name="Gemeinde Muster"))
    updated = repo.upsert_contact(ExtractedContact(name="Gemeinde Muster", email="info@muster.de"))
    count = repo._conn.execute(
        "SELECT COUNT(*) FROM contacts WHERE name = 'Gemeinde Muster'"
    ).fetchone()[0]
    assert count == 1
    assert updated.email == "info@muster.de"


def test_upsert_contact_preserves_existing_field_when_not_provided(
    repo: Repository,
) -> None:
    repo.upsert_contact(ExtractedContact(name="Herr Meier", email="meier@example.com"))
    again = repo.upsert_contact(ExtractedContact(name="Herr Meier"))
    assert again.email == "meier@example.com"


def test_get_contact_by_name_not_found(repo: Repository) -> None:
    assert repo.get_contact_by_name("Niemand") is None


def test_round_trip_contact(repo: Repository) -> None:
    extracted = ExtractedContact(
        name="Dr. Schneider",
        type=ContactType.DIENSTLEISTER,
        email="dr@schneider.de",
        phone="+49 89 123456",
        notes="Statiker für Holzdecks",
    )
    contact = repo.upsert_contact(extracted)
    assert contact.id is not None
    fetched = repo.get_contact_by_id(contact.id)
    assert fetched is not None
    assert fetched.name == "Dr. Schneider"
    assert fetched.type is ContactType.DIENSTLEISTER
    assert fetched.email == "dr@schneider.de"
    assert fetched.notes == "Statiker für Holzdecks"


# --------------------------------------------------------------------------- #
# Projects                                                                      #
# --------------------------------------------------------------------------- #


def test_get_or_create_project_creates(repo: Repository) -> None:
    proj = repo.get_or_create_project("Garten Müller")
    assert proj.id is not None
    assert proj.title == "Garten Müller"
    assert proj.status is ProjectStatus.ANFRAGE


def test_get_or_create_project_dedup_by_title(repo: Repository) -> None:
    p1 = repo.get_or_create_project("Park Mitte")
    p2 = repo.get_or_create_project("Park Mitte")
    assert p1.id == p2.id


def test_get_or_create_project_with_contact(repo: Repository) -> None:
    contact = repo.upsert_contact(ExtractedContact(name="Frau Schmitt"))
    assert contact.id is not None
    proj = repo.get_or_create_project("Balkon Schmitt", contact_id=contact.id)
    assert proj.contact_id == contact.id


def test_update_project(repo: Repository) -> None:
    proj = repo.get_or_create_project("Grünanlage West")
    updated = repo.update_project(
        proj.model_copy(
            update={
                "status": ProjectStatus.PLANUNG,
                "waiting_on": WaitingOn.KUNDE,
                "next_action": "Pflanzplan einreichen",
            }
        )
    )
    assert updated.status is ProjectStatus.PLANUNG
    assert updated.waiting_on is WaitingOn.KUNDE
    assert updated.next_action == "Pflanzplan einreichen"


def test_update_project_without_id_raises(repo: Repository) -> None:
    proj = Project(title="Ohne ID")
    with pytest.raises(ValueError, match="id"):
        repo.update_project(proj)


# --------------------------------------------------------------------------- #
# Tasks                                                                         #
# --------------------------------------------------------------------------- #


def test_create_task(repo: Repository) -> None:
    task = Task(
        title="Pflanzplan zeichnen",
        due=date(2026, 8, 1),
        source=TaskSource.SPRACHNOTIZ,
    )
    saved = repo.create_task(task)
    assert saved.id is not None
    assert saved.title == "Pflanzplan zeichnen"
    assert saved.due == date(2026, 8, 1)
    assert saved.status is TaskStatus.OFFEN
    assert saved.source is TaskSource.SPRACHNOTIZ


def test_create_task_with_depends_on(repo: Repository) -> None:
    t1 = repo.create_task(Task(title="Bestandsaufnahme"))
    assert t1.id is not None
    t2 = repo.create_task(Task(title="Pflanzplan", depends_on=[t1.id]))
    assert t2.depends_on == [t1.id]


def test_create_task_preserves_time_window(repo: Repository) -> None:
    task = Task(
        title="Wiese mähen",
        time_window="Mai–Juni",
        window_start=date(2026, 5, 1),
        window_end=date(2026, 6, 30),
    )
    saved = repo.create_task(task)
    assert saved.time_window == "Mai–Juni"
    assert saved.window_start == date(2026, 5, 1)
    assert saved.window_end == date(2026, 6, 30)


# --------------------------------------------------------------------------- #
# Queries                                                                       #
# --------------------------------------------------------------------------- #


def test_query_open_items_returns_only_open(repo: Repository) -> None:
    repo.create_task(Task(title="Offen 1"))
    repo.create_task(Task(title="Offen 2"))
    closed = repo.create_task(Task(title="Erledigt"))
    assert closed.id is not None
    repo._conn.execute(
        "UPDATE tasks SET status = ? WHERE id = ?",
        (str(TaskStatus.ERLEDIGT), closed.id),
    )
    open_tasks = repo.query_open_items()
    assert len(open_tasks) == 2
    assert all(t.status is TaskStatus.OFFEN for t in open_tasks)


def test_query_waiting_on_returns_matching_projects(repo: Repository) -> None:
    p1 = repo.get_or_create_project("Warte auf Kunde")
    repo.update_project(p1.model_copy(update={"waiting_on": WaitingOn.KUNDE}))

    p2 = repo.get_or_create_project("Meine Aufgabe")
    repo.update_project(p2.model_copy(update={"waiting_on": WaitingOn.ICH}))

    # Noch ein Projekt ohne waiting_on
    repo.get_or_create_project("Kein Status")

    results = repo.query_waiting_on(WaitingOn.KUNDE)
    assert len(results) == 1
    assert results[0].title == "Warte auf Kunde"


def test_query_waiting_on_empty_when_no_match(repo: Repository) -> None:
    repo.get_or_create_project("Projekt ohne Warten")
    assert repo.query_waiting_on(WaitingOn.DIENSTLEISTER) == []


# --------------------------------------------------------------------------- #
# Factory                                                                       #
# --------------------------------------------------------------------------- #


def test_open_repository_creates_file(tmp_path: pytest.TempPathFactory) -> None:
    db_file = str(tmp_path / "test.db")  # type: ignore[operator]
    r = open_repository(db_file)
    # Schema vorhanden
    tables = {
        row[0]
        for row in r._conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert "contacts" in tables
