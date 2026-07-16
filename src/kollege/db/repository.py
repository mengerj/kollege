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
from datetime import UTC, date, datetime
from typing import Any, Concatenate, cast

from kollege.models import (
    Contact,
    ExtractedContact,
    Ort,
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


_DDL_ORTE = """
CREATE TABLE IF NOT EXISTS orte (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,
    adresse     TEXT,
    flurnummer  TEXT,
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
)
"""

_DDL_CONTACTS = """
CREATE TABLE IF NOT EXISTS contacts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,
    type        TEXT,
    email       TEXT,
    phone       TEXT,
    channel     TEXT,
    notes       TEXT,
    ort_id      INTEGER REFERENCES orte(id),
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
    ort_id              INTEGER REFERENCES orte(id),
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
    """Alle DB-Operationen für Kontakte, Projekte, Tasks und Örtlichkeiten."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = threading.RLock()
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._create_schema()

    def _create_schema(self) -> None:
        cur = self._conn.cursor()
        cur.execute(_DDL_ORTE)
        cur.execute(_DDL_CONTACTS)
        cur.execute(_DDL_PROJECTS)
        cur.execute(_DDL_TASKS)
        self._migrate_ort_columns(cur)
        self._conn.commit()

    def _migrate_ort_columns(self, cur: sqlite3.Cursor) -> None:
        """Fügt ``ort_id`` zu bereits bestehenden ``contacts``/``projects``-Tabellen hinzu.

        ``CREATE TABLE IF NOT EXISTS`` legt die Spalte nur bei einer frischen DB an;
        eine schon existierende Datei aus der Zeit vor Schritt 8.26 hat sie noch
        nicht — SQLite kennt kein ``ADD COLUMN IF NOT EXISTS``, daher der Check.
        """
        for table in ("contacts", "projects"):
            columns = {row["name"] for row in cur.execute(f"PRAGMA table_info({table})")}
            if "ort_id" not in columns:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN ort_id INTEGER REFERENCES orte(id)")

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

    @_synchronized
    def link_contact_ort(self, contact_id: int, ort_id: int) -> Contact:
        """Kontakt mit einer Örtlichkeit verknüpfen (Schritt 8.26)."""
        self._conn.execute("UPDATE contacts SET ort_id = ? WHERE id = ?", (ort_id, contact_id))
        self._conn.commit()
        result = self.get_contact_by_id(contact_id)
        assert result is not None
        return result

    # ------------------------------------------------------------------ #
    # Örtlichkeiten (Schritt 8.26)                                         #
    # ------------------------------------------------------------------ #

    @_synchronized
    def get_or_create_ort(
        self, name: str, adresse: str | None = None, flurnummer: str | None = None
    ) -> Ort:
        """Örtlichkeit per Namensabgleich holen oder neu anlegen.

        Exact-name-Dedup wie bei Kontakten/Projekten. Ist die Örtlichkeit bereits
        vorhanden, werden ``adresse``/``flurnummer`` nur überschrieben, wenn ein
        neuer, nicht-``None``-Wert mitgegeben wird — ``None`` heißt „unverändert
        lassen" (analog ``upsert_contact``).
        """
        existing = self.get_ort_by_name(name)
        now = _now()

        if existing is not None:
            updates: dict[str, Any] = {}
            if adresse is not None:
                updates["adresse"] = adresse
            if flurnummer is not None:
                updates["flurnummer"] = flurnummer
            if updates:
                updates["updated_at"] = now
                set_clause = ", ".join(f"{k} = :{k}" for k in updates)
                updates["id"] = existing.id
                self._conn.execute(f"UPDATE orte SET {set_clause} WHERE id = :id", updates)
                self._conn.commit()
            assert existing.id is not None
            result = self.get_ort_by_id(existing.id)
            assert result is not None
            return result

        cur = self._conn.execute(
            """
            INSERT INTO orte (name, adresse, flurnummer, created_at, updated_at)
            VALUES (:name, :adresse, :flurnummer, :created_at, :updated_at)
            """,
            {
                "name": name,
                "adresse": adresse,
                "flurnummer": flurnummer,
                "created_at": now,
                "updated_at": now,
            },
        )
        self._conn.commit()
        assert cur.lastrowid is not None
        result = self.get_ort_by_id(cur.lastrowid)
        assert result is not None
        return result

    @_synchronized
    def get_ort_by_name(self, name: str) -> Ort | None:
        row = self._conn.execute("SELECT * FROM orte WHERE name = ?", (name,)).fetchone()
        return self._row_to_ort(row) if row is not None else None

    @_synchronized
    def get_ort_by_id(self, ort_id: int) -> Ort | None:
        row = self._conn.execute("SELECT * FROM orte WHERE id = ?", (ort_id,)).fetchone()
        return self._row_to_ort(row) if row is not None else None

    def _row_to_ort(self, row: Any) -> Ort:
        return Ort.model_validate(dict(row))

    @_synchronized
    def list_orte(self) -> list[Ort]:
        """Alle Örtlichkeiten, alphabetisch sortiert — für das Kommando ``/orte``."""
        rows = self._conn.execute("SELECT * FROM orte ORDER BY name COLLATE NOCASE").fetchall()
        return [self._row_to_ort(r) for r in rows]

    @_synchronized
    def get_all_orte(self) -> list[Ort]:
        """Alle Örtlichkeiten – für den Bekannte-Namen-Kontext (Schritt 8.7-Mechanik)."""
        rows = self._conn.execute("SELECT * FROM orte").fetchall()
        return [self._row_to_ort(r) for r in rows]

    # ------------------------------------------------------------------ #
    # Projects                                                             #
    # ------------------------------------------------------------------ #

    @_synchronized
    def get_project_by_title(self, title: str) -> Project | None:
        """Projekt per Titel (öffentlich, exakter Abgleich), ohne es anzulegen.

        Nicht-anlegende Variante von ``get_or_create_project`` — genutzt, um vor
        dem Anlegen zu prüfen, ob ein referenziertes Projekt bereits existiert
        (Neu-Markierung im Vorschlag/in der Bestätigung, Schritt 8.25).
        """
        row = self._conn.execute("SELECT * FROM projects WHERE title = ?", (title,)).fetchone()
        return self._row_to_project(row) if row is not None else None

    @_synchronized
    def get_or_create_project(self, title: str, contact_id: int | None = None) -> Project:
        """Hole vorhandenes Projekt per Titel oder lege neues an."""
        existing = self.get_project_by_title(title)
        if existing is not None:
            return existing

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

    @_synchronized
    def link_project_ort(self, project_id: int, ort_id: int) -> Project:
        """Projekt mit einer Örtlichkeit verknüpfen (Schritt 8.26)."""
        self._conn.execute("UPDATE projects SET ort_id = ? WHERE id = ?", (ort_id, project_id))
        self._conn.commit()
        result = self._get_project_by_id(project_id)
        assert result is not None
        return result

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
    def update_task(
        self,
        task_id: int,
        title: str | None = None,
        due: date | None = None,
        project_id: int | None = None,
    ) -> Task:
        """Felder einer bestehenden Aufgabe ändern (Schritt 8.19 — „Aufgabe bearbeiten").

        Nur nicht-``None``-Argumente werden geschrieben; ``None`` heißt „Feld
        unverändert lassen" (ein Feld wieder zu leeren ist bewusst nicht vorgesehen —
        Korrektur, kein Zurücksetzen). ``ValueError``, wenn die Aufgabe nicht
        existiert. ``updated_at`` gibt es auf ``tasks`` (noch) nicht — daher kein
        Zeitstempel-Update; bewusste Grenze.
        """
        existing = self._get_task_by_id(task_id)
        if existing is None:
            raise ValueError(f"Task {task_id} nicht gefunden")
        new_title = title if title is not None else existing.title
        new_due = due if due is not None else existing.due
        new_project_id = project_id if project_id is not None else existing.project_id
        self._conn.execute(
            "UPDATE tasks SET title = ?, due = ?, project_id = ? WHERE id = ?",
            (
                new_title,
                new_due.isoformat() if new_due is not None else None,
                new_project_id,
                task_id,
            ),
        )
        self._conn.commit()
        result = self._get_task_by_id(task_id)
        assert result is not None
        return result

    def get_project_by_id(self, project_id: int) -> Project | None:
        """Projekt per ID (öffentlich) — z. B. für Log-Konsistenz beim Aufgaben-Edit."""
        return self._get_project_by_id(project_id)

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

    def get_task_by_id(self, task_id: int) -> Task | None:
        """Aufgabe per ID (öffentlich, unabhängig vom Status) — für Lösch-Vorschauen."""
        return self._get_task_by_id(task_id)

    @_synchronized
    def get_tasks_by_project(self, project_id: int) -> list[Task]:
        """Alle Aufgaben eines Projekts — für die Cascade-Vorschau beim Projekt-Löschen."""
        rows = self._conn.execute(
            "SELECT * FROM tasks WHERE project_id = ?", (project_id,)
        ).fetchall()
        return [self._row_to_task(r) for r in rows]

    # ------------------------------------------------------------------ #
    # Löschverben (Schritt 8.22)                                           #
    # ------------------------------------------------------------------ #
    #
    # Löschen ist destruktiv und selten — bewusst nicht über die LLM-Extraktion,
    # sondern nur über deterministische Slash-Commands mit Zwei-Schritt-
    # Bestätigung erreichbar (siehe orchestrator.py). Referentielle Konsequenzen:
    # ein gelöschter Kontakt löst nur die Zuordnung (Projekte/Aufgaben bleiben —
    # Notizbuch-Prinzip: ergänzen, nicht ersetzen); ein gelöschtes Projekt reißt
    # seine Aufgaben mit (sie gehören inhaltlich dazu, ein verwaister Rest wäre
    # verwirrender als ihr Wegfall).

    @_synchronized
    def delete_contact(self, contact_id: int) -> None:
        """Kontakt löschen; Referenzen in Projekten/Aufgaben werden gelöst (nicht mitgelöscht).

        ``ValueError`` bei unbekannter ID.
        """
        if self.get_contact_by_id(contact_id) is None:
            raise ValueError(f"Kontakt {contact_id} nicht gefunden")
        self._conn.execute(
            "UPDATE projects SET contact_id = NULL WHERE contact_id = ?", (contact_id,)
        )
        self._conn.execute("UPDATE tasks SET contact_id = NULL WHERE contact_id = ?", (contact_id,))
        self._conn.execute("DELETE FROM contacts WHERE id = ?", (contact_id,))
        self._conn.commit()

    @_synchronized
    def delete_project(self, project_id: int) -> None:
        """Projekt löschen inkl. aller zugehörigen Aufgaben (Cascade).

        ``ValueError`` bei unbekannter ID.
        """
        if self._get_project_by_id(project_id) is None:
            raise ValueError(f"Projekt {project_id} nicht gefunden")
        self._conn.execute("DELETE FROM tasks WHERE project_id = ?", (project_id,))
        self._conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        self._conn.commit()

    @_synchronized
    def delete_task(self, task_id: int) -> None:
        """Einzelne Aufgabe löschen. ``ValueError`` bei unbekannter ID."""
        if self._get_task_by_id(task_id) is None:
            raise ValueError(f"Aufgabe {task_id} nicht gefunden")
        self._conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        self._conn.commit()

    @_synchronized
    def delete_ort(self, ort_id: int) -> None:
        """Örtlichkeit löschen; Referenzen in Kontakten/Projekten werden gelöst.

        ``ValueError`` bei unbekannter ID.
        """
        if self.get_ort_by_id(ort_id) is None:
            raise ValueError(f"Örtlichkeit {ort_id} nicht gefunden")
        self._conn.execute("UPDATE contacts SET ort_id = NULL WHERE ort_id = ?", (ort_id,))
        self._conn.execute("UPDATE projects SET ort_id = NULL WHERE ort_id = ?", (ort_id,))
        self._conn.execute("DELETE FROM orte WHERE id = ?", (ort_id,))
        self._conn.commit()

    @_synchronized
    def reset_all(self) -> None:
        """Alle Kontakte, Projekte, Aufgaben und Örtlichkeiten löschen (Testdaten-Reset).

        Reihenfolge wegen Fremdschlüsseln: Aufgaben zuerst (referenzieren Projekte/
        Kontakte), dann Projekte (referenzieren Kontakte/Örtlichkeiten), dann
        Kontakte (referenzieren Örtlichkeiten), dann Örtlichkeiten.
        """
        self._conn.execute("DELETE FROM tasks")
        self._conn.execute("DELETE FROM projects")
        self._conn.execute("DELETE FROM contacts")
        self._conn.execute("DELETE FROM orte")
        self._conn.commit()

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

    def query_open_tasks(self, sort_by_due: bool = True) -> list[Task]:
        """Offene Aufgaben — für die Slash-Commands ``/offen`` und ``/dringend``.

        ``sort_by_due=True`` (``/dringend``): aufsteigend nach Frist, d. h.
        überfällige (``due <= heute``) zuerst, dann die nächsten Fristen,
        Aufgaben ohne Datum ans Ende. ``sort_by_due=False`` (``/offen``):
        Einfügereihenfolge.
        """
        tasks = self.query_open_items()
        if not sort_by_due:
            return tasks
        return sorted(tasks, key=lambda t: (t.due is None, t.due))

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
    def get_all_tasks(self) -> list[Task]:
        """Alle Aufgaben unabhängig vom Status — für Lösch-Vorschauen (Schritt 8.22)."""
        rows = self._conn.execute("SELECT * FROM tasks").fetchall()
        return [self._row_to_task(r) for r in rows]

    @_synchronized
    def list_contacts(self) -> list[Contact]:
        """Alle Kontakte, alphabetisch sortiert — für das Kommando ``/kontakte``."""
        rows = self._conn.execute("SELECT * FROM contacts ORDER BY name COLLATE NOCASE").fetchall()
        return [self._row_to_contact(r) for r in rows]

    @_synchronized
    def list_projects(self) -> list[Project]:
        """Alle Projekte, alphabetisch sortiert — für das Kommando ``/projekte``."""
        rows = self._conn.execute("SELECT * FROM projects ORDER BY title COLLATE NOCASE").fetchall()
        return [self._row_to_project(r) for r in rows]

    def mark_task_done(self, task_id: int) -> Task:
        """Task als erledigt markieren — für das Kommando ``/erledigt <id>``.

        Nutzt ``update_task_status``; wirft ``ValueError`` bei unbekannter ID.
        """
        return self.update_task_status(task_id, TaskStatus.ERLEDIGT)

    @_synchronized
    def query_waiting_on(self, waiting_on: WaitingOn) -> list[Project]:
        """Projekte nach waiting_on filtern — Kernfrage „bei wem muss ich mich melden?"."""
        rows = self._conn.execute(
            "SELECT * FROM projects WHERE waiting_on = ?", (str(waiting_on),)
        ).fetchall()
        return [self._row_to_project(r) for r in rows]
