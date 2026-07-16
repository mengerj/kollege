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
    assert {"contacts", "projects", "tasks", "orte"}.issubset(tables)


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


def test_get_project_by_title_returns_none_when_missing(repo: Repository) -> None:
    """Nicht-anlegende Variante (Schritt 8.25) — legt anders als get_or_create_project nichts an."""
    assert repo.get_project_by_title("Unbekanntes Projekt") is None


def test_get_project_by_title_returns_existing(repo: Repository) -> None:
    created = repo.get_or_create_project("Gartenpflege Weber")
    found = repo.get_project_by_title("Gartenpflege Weber")
    assert found is not None
    assert found.id == created.id


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


def test_query_open_tasks_sort_by_due_overdue_first_no_date_last(repo: Repository) -> None:
    ohne_datum = repo.create_task(Task(title="Ohne Datum"))
    spaeter = repo.create_task(Task(title="Später", due=date(2026, 12, 1)))
    ueberfaellig = repo.create_task(Task(title="Überfällig", due=date(2026, 1, 1)))
    bald = repo.create_task(Task(title="Bald", due=date(2026, 7, 5)))

    result = repo.query_open_tasks(sort_by_due=True)

    assert [t.id for t in result] == [ueberfaellig.id, bald.id, spaeter.id, ohne_datum.id]


def test_query_open_tasks_sort_by_due_false_returns_insertion_order(repo: Repository) -> None:
    first = repo.create_task(Task(title="Zuerst", due=date(2026, 12, 1)))
    second = repo.create_task(Task(title="Danach", due=date(2026, 1, 1)))

    result = repo.query_open_tasks(sort_by_due=False)

    assert [t.id for t in result] == [first.id, second.id]


def test_query_open_tasks_excludes_closed(repo: Repository) -> None:
    closed = repo.create_task(Task(title="Erledigt"))
    assert closed.id is not None
    repo.mark_task_done(closed.id)
    repo.create_task(Task(title="Offen"))

    assert len(repo.query_open_tasks()) == 1


def test_list_contacts_sorted_alphabetically(repo: Repository) -> None:
    repo.upsert_contact(ExtractedContact(name="Zimmermann"))
    repo.upsert_contact(ExtractedContact(name="Anders"))
    repo.upsert_contact(ExtractedContact(name="Müller"))

    names = [c.name for c in repo.list_contacts()]
    assert names == ["Anders", "Müller", "Zimmermann"]


def test_list_projects_sorted_alphabetically(repo: Repository) -> None:
    repo.get_or_create_project("Zaunbau")
    repo.get_or_create_project("Aibling")

    titles = [p.title for p in repo.list_projects()]
    assert titles == ["Aibling", "Zaunbau"]


def test_mark_task_done_sets_status(repo: Repository) -> None:
    task = repo.create_task(Task(title="Zaun streichen"))
    assert task.id is not None

    done = repo.mark_task_done(task.id)

    assert done.status is TaskStatus.ERLEDIGT
    assert repo.query_open_items() == []


def test_mark_task_done_unknown_id_raises(repo: Repository) -> None:
    with pytest.raises(ValueError, match="nicht gefunden"):
        repo.mark_task_done(999)


# --------------------------------------------------------------------------- #
# update_task — Aufgabe bearbeiten (Schritt 8.19)                              #
# --------------------------------------------------------------------------- #


def test_update_task_changes_title(repo: Repository) -> None:
    task = repo.create_task(Task(title="Bad Eibling begehen"))
    assert task.id is not None

    updated = repo.update_task(task.id, title="Bad Aibling begehen")

    assert updated.title == "Bad Aibling begehen"
    # Reload aus DB bestätigt Persistenz
    assert repo.query_open_items()[0].title == "Bad Aibling begehen"


def test_update_task_changes_due_and_project(repo: Repository) -> None:
    project = repo.get_or_create_project("Gemeinde-Sache")
    assert project.id is not None
    task = repo.create_task(Task(title="Unterlagen prüfen"))
    assert task.id is not None

    updated = repo.update_task(task.id, due=date(2026, 7, 10), project_id=project.id)

    assert updated.due == date(2026, 7, 10)
    assert updated.project_id == project.id


def test_update_task_none_fields_leave_values_unchanged(repo: Repository) -> None:
    task = repo.create_task(Task(title="Ursprung", due=date(2026, 7, 1)))
    assert task.id is not None

    updated = repo.update_task(task.id, title="Neu")  # due bleibt unangetastet

    assert updated.title == "Neu"
    assert updated.due == date(2026, 7, 1)


def test_update_task_unknown_id_raises(repo: Repository) -> None:
    with pytest.raises(ValueError, match="nicht gefunden"):
        repo.update_task(999, title="egal")


def test_update_task_preserves_status(repo: Repository) -> None:
    """Ein Titel-Edit ändert den Status nicht (bleibt offen)."""
    task = repo.create_task(Task(title="Offen bleiben"))
    assert task.id is not None

    updated = repo.update_task(task.id, title="Immer noch offen")

    assert updated.status is TaskStatus.OFFEN


# --------------------------------------------------------------------------- #
# Löschverben (Schritt 8.22)                                                    #
# --------------------------------------------------------------------------- #


def test_delete_task_removes_it(repo: Repository) -> None:
    task = repo.create_task(Task(title="Weg damit"))
    assert task.id is not None

    repo.delete_task(task.id)

    assert repo.get_task_by_id(task.id) is None


def test_delete_task_unknown_id_raises(repo: Repository) -> None:
    with pytest.raises(ValueError, match="nicht gefunden"):
        repo.delete_task(999)


def test_delete_contact_removes_it(repo: Repository) -> None:
    contact = repo.upsert_contact(ExtractedContact(name="Familie Müller"))
    assert contact.id is not None

    repo.delete_contact(contact.id)

    assert repo.get_contact_by_id(contact.id) is None


def test_delete_contact_unknown_id_raises(repo: Repository) -> None:
    with pytest.raises(ValueError, match="nicht gefunden"):
        repo.delete_contact(999)


def test_delete_contact_unlinks_but_keeps_project_and_task(repo: Repository) -> None:
    """Referentielle Regel: Kontakt-Löschen löst die Zuordnung, löscht aber keine
    Projekte/Aufgaben mit (Notizbuch-Prinzip — ergänzen, nicht ersetzen)."""
    contact = repo.upsert_contact(ExtractedContact(name="Familie Müller"))
    assert contact.id is not None
    project = repo.get_or_create_project("Gartenzaun", contact_id=contact.id)
    task = repo.create_task(Task(title="Zaun streichen", contact_id=contact.id))
    assert task.id is not None

    repo.delete_contact(contact.id)

    reloaded_project = repo._get_project_by_id(project.id)  # type: ignore[arg-type]
    assert reloaded_project is not None
    assert reloaded_project.contact_id is None
    reloaded_task = repo.get_task_by_id(task.id)
    assert reloaded_task is not None
    assert reloaded_task.contact_id is None


def test_delete_project_removes_it(repo: Repository) -> None:
    project = repo.get_or_create_project("Kräutergarten")
    assert project.id is not None

    repo.delete_project(project.id)

    assert repo._get_project_by_id(project.id) is None


def test_delete_project_unknown_id_raises(repo: Repository) -> None:
    with pytest.raises(ValueError, match="nicht gefunden"):
        repo.delete_project(999)


def test_delete_project_cascades_to_its_tasks(repo: Repository) -> None:
    """Referentielle Regel: Projekt-Löschen löscht zugehörige Aufgaben mit —
    sie gehören inhaltlich zum Projekt, ein verwaister Rest wäre verwirrend."""
    project = repo.get_or_create_project("Kräutergarten")
    assert project.id is not None
    task = repo.create_task(Task(title="Beete anlegen", project_id=project.id))
    assert task.id is not None
    other_task = repo.create_task(Task(title="Ohne Projekt"))
    assert other_task.id is not None

    repo.delete_project(project.id)

    assert repo.get_task_by_id(task.id) is None
    assert repo.get_task_by_id(other_task.id) is not None  # unbeteiligte Aufgabe bleibt


def test_get_tasks_by_project_returns_only_matching(repo: Repository) -> None:
    project = repo.get_or_create_project("Kräutergarten")
    assert project.id is not None
    task = repo.create_task(Task(title="Beete anlegen", project_id=project.id))
    repo.create_task(Task(title="Ohne Projekt"))

    tasks = repo.get_tasks_by_project(project.id)

    assert [t.id for t in tasks] == [task.id]


def test_reset_all_clears_everything(repo: Repository) -> None:
    contact = repo.upsert_contact(ExtractedContact(name="Familie Müller"))
    repo.get_or_create_project("Kräutergarten", contact_id=contact.id)
    repo.create_task(Task(title="Beete anlegen"))
    repo.get_or_create_ort("Flurstück 12")

    repo.reset_all()

    assert repo.get_all_contacts() == []
    assert repo.get_all_projects() == []
    assert repo.get_all_tasks() == []
    assert repo.get_all_orte() == []


def test_reset_all_on_empty_repo_does_not_raise(repo: Repository) -> None:
    repo.reset_all()
    assert repo.get_all_tasks() == []


# --------------------------------------------------------------------------- #
# Örtlichkeiten (Schritt 8.26)                                                  #
# --------------------------------------------------------------------------- #


def test_get_or_create_ort_creates_new(repo: Repository) -> None:
    ort = repo.get_or_create_ort("Flurstück 12", adresse="Musterweg 3", flurnummer="12/3")
    assert ort.id is not None
    assert ort.name == "Flurstück 12"
    assert ort.adresse == "Musterweg 3"
    assert ort.flurnummer == "12/3"


def test_get_or_create_ort_dedup_same_name_returns_existing(repo: Repository) -> None:
    first = repo.get_or_create_ort("Flurstück 12")
    second = repo.get_or_create_ort("Flurstück 12")
    assert first.id == second.id


def test_get_or_create_ort_updates_adresse_when_provided(repo: Repository) -> None:
    repo.get_or_create_ort("Flurstück 12")
    updated = repo.get_or_create_ort("Flurstück 12", adresse="Neue Adresse 1")
    assert updated.adresse == "Neue Adresse 1"


def test_get_or_create_ort_preserves_existing_field_when_not_provided(repo: Repository) -> None:
    repo.get_or_create_ort("Flurstück 12", adresse="Musterweg 3")
    again = repo.get_or_create_ort("Flurstück 12")
    assert again.adresse == "Musterweg 3"


def test_get_ort_by_name_not_found(repo: Repository) -> None:
    assert repo.get_ort_by_name("Niemandsland") is None


def test_link_contact_ort_sets_ort_id(repo: Repository) -> None:
    contact = repo.upsert_contact(ExtractedContact(name="Familie Müller"))
    ort = repo.get_or_create_ort("Flurstück 12")
    assert contact.id is not None
    assert ort.id is not None

    updated = repo.link_contact_ort(contact.id, ort.id)

    assert updated.ort_id == ort.id
    assert repo.get_contact_by_id(contact.id).ort_id == ort.id  # type: ignore[union-attr]


def test_link_project_ort_sets_ort_id(repo: Repository) -> None:
    project = repo.get_or_create_project("Stadtpark")
    ort = repo.get_or_create_ort("Flurstück 12")
    assert project.id is not None
    assert ort.id is not None

    updated = repo.link_project_ort(project.id, ort.id)

    assert updated.ort_id == ort.id
    assert repo.get_project_by_id(project.id).ort_id == ort.id  # type: ignore[union-attr]


def test_list_orte_sorted_alphabetically(repo: Repository) -> None:
    repo.get_or_create_ort("Zufahrt Nord")
    repo.get_or_create_ort("Am Bach")
    repo.get_or_create_ort("Mühlenweg")

    names = [o.name for o in repo.list_orte()]

    assert names == ["Am Bach", "Mühlenweg", "Zufahrt Nord"]


def test_get_all_orte_returns_all(repo: Repository) -> None:
    repo.get_or_create_ort("Flurstück 12")
    repo.get_or_create_ort("Flurstück 13")
    assert len(repo.get_all_orte()) == 2


def test_delete_ort_removes_it(repo: Repository) -> None:
    ort = repo.get_or_create_ort("Flurstück 12")
    assert ort.id is not None

    repo.delete_ort(ort.id)

    assert repo.get_ort_by_id(ort.id) is None


def test_delete_ort_unknown_id_raises(repo: Repository) -> None:
    with pytest.raises(ValueError, match="nicht gefunden"):
        repo.delete_ort(999)


def test_delete_ort_unlinks_but_keeps_contact_and_project(repo: Repository) -> None:
    """Referentielle Regel wie bei Kontakten: Löschen löst die Zuordnung, ohne
    den Kontakt/das Projekt selbst mitzulöschen."""
    contact = repo.upsert_contact(ExtractedContact(name="Familie Müller"))
    project = repo.get_or_create_project("Stadtpark")
    ort = repo.get_or_create_ort("Flurstück 12")
    assert contact.id is not None
    assert project.id is not None
    assert ort.id is not None
    repo.link_contact_ort(contact.id, ort.id)
    repo.link_project_ort(project.id, ort.id)

    repo.delete_ort(ort.id)

    reloaded_contact = repo.get_contact_by_id(contact.id)
    reloaded_project = repo._get_project_by_id(project.id)
    assert reloaded_contact is not None
    assert reloaded_contact.ort_id is None
    assert reloaded_project is not None
    assert reloaded_project.ort_id is None


def test_migration_adds_ort_id_to_existing_contacts_and_projects_tables() -> None:
    """Bestehende DB ohne ``ort_id`` (Zeit vor Schritt 8.26) läuft nach dem Öffnen weiter."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute(
        """
        CREATE TABLE contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            type TEXT, email TEXT, phone TEXT, channel TEXT, notes TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL UNIQUE,
            contact_id INTEGER REFERENCES contacts(id),
            status TEXT NOT NULL DEFAULT 'anfrage',
            phase_note TEXT, markdown_log_path TEXT, next_action TEXT, waiting_on TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )
        """
    )
    now = "2026-01-01T00:00:00+00:00"
    conn.execute(
        "INSERT INTO contacts (name, created_at, updated_at) VALUES ('Alt', ?, ?)", (now, now)
    )
    conn.execute(
        "INSERT INTO projects (title, created_at, updated_at) VALUES ('Altprojekt', ?, ?)",
        (now, now),
    )
    conn.commit()

    repo = Repository(conn)

    contact = repo.get_contact_by_name("Alt")
    project = repo.get_project_by_title("Altprojekt")
    assert contact is not None
    assert contact.ort_id is None
    assert project is not None
    assert project.ort_id is None
    # Migration ist idempotent — erneutes Öffnen darf nicht scheitern.
    Repository(conn)


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


# --------------------------------------------------------------------------- #
# Nebenläufigkeit                                                               #
# --------------------------------------------------------------------------- #


def test_repository_is_thread_safe() -> None:
    """Gleichzeitige Schreibzugriffe aus mehreren Threads dürfen nicht kollidieren.

    Regression: Pydantic-AI führt Agent-Tools nebenläufig in Worker-Threads aus,
    die sich eine ``sqlite3.Connection`` teilen. Ohne Serialisierung schlug das
    mit ``InterfaceError: bad parameter or other API misuse`` (o.ä.) fehl.
    """
    import threading

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    repo = Repository(conn)

    n_threads = 8
    per_thread = 25
    barrier = threading.Barrier(n_threads)
    errors: list[Exception] = []

    def worker(tid: int) -> None:
        barrier.wait()  # maximalen gleichzeitigen Start erzwingen
        try:
            for i in range(per_thread):
                repo.upsert_contact(ExtractedContact(name=f"Kontakt {tid}-{i}"))
                repo.get_or_create_project(f"Projekt {tid}-{i}")
                repo.create_task(
                    Task(
                        title=f"Aufgabe {tid}-{i}",
                        status=TaskStatus.OFFEN,
                        source=TaskSource.SPRACHNOTIZ,
                    )
                )
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Nebenläufige Zugriffe schlugen fehl: {errors[:3]}"
    assert len(repo.query_open_items()) == n_threads * per_thread
