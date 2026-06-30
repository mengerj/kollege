"""SQLite-Repository: Schema-Erzeugung und CRUD-Operationen.

Nutzt stdlib ``sqlite3``; Pydantic-Modelle als Serialisierungsschicht.
Schema ist idempotent (``CREATE TABLE IF NOT EXISTS``).
"""

from __future__ import annotations

import functools
import json
import sqlite3
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Concatenate, cast

from kollege.models import (
    Contact,
    ExtractedContact,
    Project,
    ProjectStatus,
    Task,
    TaskStatus,
    WaitingOn,
)


def _synchronized[**P, R](
    method: Callable[Concatenate[Repository, P], R],
) -> Callable[Concatenate[Repository, P], R]:
    """Serialisiert den Methodenaufruf über den Repository-eigenen Lock.

    Pydantic-AI führt die Domain-Tools eines Agent-Laufs nebenläufig in
    Worker-Threads aus. Diese teilen sich dieselbe ``sqlite3.Connection``, die
    nicht für gleichzeitige Nutzung ausgelegt ist (sonst „bad parameter or other
    API misuse"). Ein reentranter Lock pro Repository sequenzialisiert daher
    jede komplette Operation (execute + fetch + commit).
    """

    @functools.wraps(method)
    def wrapper(self: Repository, *args: P.args, **kwargs: P.kwargs) -> R:
        with self._lock:
            return method(self, *args, **kwargs)

    return cast("Callable[Concatenate[Repository, P], R]", wrapper)


_DDL_CONTACTS = """
CREATE TABLE IF NOT EXISTS contacts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,
    type        TEXT,
    email       TEXT,
    phone       TEXT,
    channel     TEXT,
    notes       TEXT,
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
)
"""

_DDL_PROJECTS = """
CREATE TABLE IF NOT EXISTS projects (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    title               TEXT    NOT NULL UNIQUE,
    contact_id          INTEGER REFERENCES contacts(id),
    status              TEXT    NOT NULL DEFAULT 'anfrage',
    phase_note          TEXT,
    markdown_log_path   TEXT,
    next_action         TEXT,
    waiting_on          TEXT,
    created_at          TEXT    NOT NULL,
    updated_at          TEXT    NOT NULL
)
"""

_DDL_TASKS = """
CREATE TABLE IF NOT EXISTS tasks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT    NOT NULL,
    project_id   INTEGER REFERENCES projects(id),
    contact_id   INTEGER REFERENCES contacts(id),
    due          TEXT,
    status       TEXT    NOT NULL DEFAULT 'offen',
    source       TEXT    NOT NULL DEFAULT 'manuell',
    source_ref   TEXT,
    depends_on   TEXT    NOT NULL DEFAULT '[]',
    time_window  TEXT,
    window_start TEXT,
    window_end   TEXT,
    created_at   TEXT    NOT NULL
)
"""


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()


class Repository:
    """Alle DB-Operationen für Kontakte, Projekte und Tasks."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = threading.RLock()
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._create_schema()

    def _create_schema(self) -> None:
        cur = self._conn.cursor()
        cur.execute(_DDL_CONTACTS)
        cur.execute(_DDL_PROJECTS)
        cur.execute(_DDL_TASKS)
        self._conn.commit()

    # ------------------------------------------------------------------ #
    # Contacts                                                             #
    # ------------------------------------------------------------------ #

    @_synchronized
    def upsert_contact(self, extracted: ExtractedContact) -> Contact:
        """Exact-name-Dedup: vorhandenen Kontakt aktualisieren oder neu anlegen.

        Dedup-Strategie: exakter Namensabgleich (Fuzzy folgt später, Schritt 13).
        Doppelte Kontakte wären ein Vertrauenskiller — lieber zu wenig mergen.
        """
        existing = self.get_contact_by_name(extracted.name)
        now = _now()

        if existing is not None:
            updates: dict[str, Any] = {"updated_at": now}
            if extracted.type is not None:
                updates["type"] = str(extracted.type)
            if extracted.email is not None:
                updates["email"] = extracted.email
            if extracted.phone is not None:
                updates["phone"] = extracted.phone
            if extracted.notes is not None:
                updates["notes"] = extracted.notes
            set_clause = ", ".join(f"{k} = :{k}" for k in updates)
            updates["id"] = existing.id
            self._conn.execute(
                f"UPDATE contacts SET {set_clause} WHERE id = :id",
                updates,
            )
            self._conn.commit()
            assert existing.id is not None
            result = self.get_contact_by_id(existing.id)
            assert result is not None
            return result

        cur = self._conn.execute(
            """
            INSERT INTO contacts (name, type, email, phone, notes, created_at, updated_at)
            VALUES (:name, :type, :email, :phone, :notes, :created_at, :updated_at)
            """,
            {
                "name": extracted.name,
                "type": str(extracted.type) if extracted.type is not None else None,
                "email": extracted.email,
                "phone": extracted.phone,
                "notes": extracted.notes,
                "created_at": now,
                "updated_at": now,
            },
        )
        self._conn.commit()
        assert cur.lastrowid is not None
        result = self.get_contact_by_id(cur.lastrowid)
        assert result is not None
        return result

    @_synchronized
    def get_contact_by_name(self, name: str) -> Contact | None:
        row = self._conn.execute("SELECT * FROM contacts WHERE name = ?", (name,)).fetchone()
        return self._row_to_contact(row) if row is not None else None

    @_synchronized
    def get_contact_by_id(self, contact_id: int) -> Contact | None:
        row = self._conn.execute("SELECT * FROM contacts WHERE id = ?", (contact_id,)).fetchone()
        return self._row_to_contact(row) if row is not None else None

    def _row_to_contact(self, row: Any) -> Contact:
        return Contact.model_validate(dict(row))

    # ------------------------------------------------------------------ #
    # Projects                                                             #
    # ------------------------------------------------------------------ #

    @_synchronized
    def get_or_create_project(self, title: str, contact_id: int | None = None) -> Project:
        """Hole vorhandenes Projekt per Titel oder lege neues an."""
        row = self._conn.execute("SELECT * FROM projects WHERE title = ?", (title,)).fetchone()
        if row is not None:
            return self._row_to_project(row)

        now = _now()
        cur = self._conn.execute(
            """
            INSERT INTO projects (title, contact_id, status, created_at, updated_at)
            VALUES (:title, :contact_id, :status, :now, :now)
            """,
            {
                "title": title,
                "contact_id": contact_id,
                "status": str(ProjectStatus.ANFRAGE),
                "now": now,
            },
        )
        self._conn.commit()
        assert cur.lastrowid is not None
        result = self._get_project_by_id(cur.lastrowid)
        assert result is not None
        return result

    @_synchronized
    def update_project(self, project: Project) -> Project:
        """Vorhandenes Projekt per ID aktualisieren."""
        if project.id is None:
            raise ValueError("project.id darf beim Update nicht None sein")
        now = _now()
        self._conn.execute(
            """
            UPDATE projects SET
                title               = :title,
                contact_id          = :contact_id,
                status              = :status,
                phase_note          = :phase_note,
                markdown_log_path   = :markdown_log_path,
                next_action         = :next_action,
                waiting_on          = :waiting_on,
                updated_at          = :updated_at
            WHERE id = :id
            """,
            {
                "title": project.title,
                "contact_id": project.contact_id,
                "status": str(project.status),
                "phase_note": project.phase_note,
                "markdown_log_path": project.markdown_log_path,
                "next_action": project.next_action,
                "waiting_on": str(project.waiting_on) if project.waiting_on is not None else None,
                "updated_at": now,
                "id": project.id,
            },
        )
        self._conn.commit()
        result = self._get_project_by_id(project.id)
        assert result is not None
        return result

    def _get_project_by_id(self, project_id: int) -> Project | None:
        row = self._conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return self._row_to_project(row) if row is not None else None

    def _row_to_project(self, row: Any) -> Project:
        return Project.model_validate(dict(row))

    # ------------------------------------------------------------------ #
    # Tasks                                                                #
    # ------------------------------------------------------------------ #

    @_synchronized
    def create_task(self, task: Task) -> Task:
        """Neuen Task anlegen; gibt Task mit gesetzter ID zurück."""
        cur = self._conn.execute(
            """
            INSERT INTO tasks
                (title, project_id, contact_id, due, status, source, source_ref,
                 depends_on, time_window, window_start, window_end, created_at)
            VALUES
                (:title, :project_id, :contact_id, :due, :status, :source, :source_ref,
                 :depends_on, :time_window, :window_start, :window_end, :created_at)
            """,
            {
                "title": task.title,
                "project_id": task.project_id,
                "contact_id": task.contact_id,
                "due": task.due.isoformat() if task.due is not None else None,
                "status": str(task.status),
                "source": str(task.source),
                "source_ref": task.source_ref,
                "depends_on": json.dumps(task.depends_on),
                "time_window": task.time_window,
                "window_start": task.window_start.isoformat()
                if task.window_start is not None
                else None,
                "window_end": task.window_end.isoformat() if task.window_end is not None else None,
                "created_at": task.created_at.isoformat(),
            },
        )
        self._conn.commit()
        assert cur.lastrowid is not None
        result = self._get_task_by_id(cur.lastrowid)
        assert result is not None
        return result

    def _get_task_by_id(self, task_id: int) -> Task | None:
        row = self._conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return self._row_to_task(row) if row is not None else None

    def _row_to_task(self, row: Any) -> Task:
        d = dict(row)
        d["depends_on"] = json.loads(d.get("depends_on") or "[]")
        return Task.model_validate(d)

    @_synchronized
    def update_task_status(self, task_id: int, status: TaskStatus) -> Task:
        """Task-Status aktualisieren (offen → erledigt / verworfen)."""
        self._conn.execute(
            "UPDATE tasks SET status = ? WHERE id = ?",
            (str(status), task_id),
        )
        self._conn.commit()
        result = self._get_task_by_id(task_id)
        if result is None:
            raise ValueError(f"Task {task_id} nicht gefunden")
        return result

    # ------------------------------------------------------------------ #
    # Queries                                                              #
    # ------------------------------------------------------------------ #

    @_synchronized
    def query_open_items(self) -> list[Task]:
        """Alle Tasks mit Status OFFEN — Kernfrage „was liegt noch an?"."""
        rows = self._conn.execute(
            "SELECT * FROM tasks WHERE status = ?", (str(TaskStatus.OFFEN),)
        ).fetchall()
        return [self._row_to_task(r) for r in rows]

    @_synchronized
    def get_all_contacts(self) -> list[Contact]:
        """Alle Kontakte – für die Rekonstruktion nach Tool-Only-Läufen."""
        rows = self._conn.execute("SELECT * FROM contacts").fetchall()
        return [self._row_to_contact(r) for r in rows]

    @_synchronized
    def get_all_projects(self) -> list[Project]:
        """Alle Projekte – für die Rekonstruktion nach Tool-Only-Läufen."""
        rows = self._conn.execute("SELECT * FROM projects").fetchall()
        return [self._row_to_project(r) for r in rows]

    @_synchronized
    def query_waiting_on(self, waiting_on: WaitingOn) -> list[Project]:
        """Projekte nach waiting_on filtern — Kernfrage „bei wem muss ich mich melden?"."""
        rows = self._conn.execute(
            "SELECT * FROM projects WHERE waiting_on = ?", (str(waiting_on),)
        ).fetchall()
        return [self._row_to_project(r) for r in rows]
