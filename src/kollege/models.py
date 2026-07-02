"""Domänen- und Extraktionsmodelle.

Pydantic-Modelle dienen doppelt: als LLM-Output-Schema (Extraktion) und als
Grundlage des SQLite-Schemas (Persistenz). Diese Datei enthält **keine**
Persistenzlogik — nur die Typen. Bewusst minimal gehalten (Designprinzip:
"minimal anfangen, bei Bedarf verfeinern").

Zwei Familien:
- ``Extracted*``  — was der Agent aus Text/Sprache vorschlägt (ohne IDs).
- Domänen-Entitäten (``Contact``, ``Project``, ``Task``) — persistierte Objekte
  mit IDs und Zeitstempeln.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(tz=UTC)


# --------------------------------------------------------------------------- #
# Enums                                                                        #
# --------------------------------------------------------------------------- #
class ContactType(StrEnum):
    PRIVAT = "privat"
    GEMEINDE = "gemeinde"
    DIENSTLEISTER = "dienstleister"


class Channel(StrEnum):
    SIGNAL = "signal"
    EMAIL = "email"
    PHONE = "phone"


class ProjectStatus(StrEnum):
    ANFRAGE = "anfrage"
    PLANUNG = "planung"
    UMSETZUNG = "umsetzung"
    PAUSIERT = "pausiert"
    ABGESCHLOSSEN = "abgeschlossen"


class WaitingOn(StrEnum):
    """Für die Kernfrage 'bei wem muss ich mich melden?'."""

    ICH = "ich"
    KUNDE = "kunde"
    DIENSTLEISTER = "dienstleister"


class TaskStatus(StrEnum):
    OFFEN = "offen"
    ERLEDIGT = "erledigt"
    VERWORFEN = "verworfen"


class TaskSource(StrEnum):
    SPRACHNOTIZ = "sprachnotiz"
    EMAIL = "email"
    CHAT = "chat"
    MANUELL = "manuell"


# --------------------------------------------------------------------------- #
# Extraktionsmodelle (LLM-Output, ohne IDs)                                    #
# --------------------------------------------------------------------------- #
class ExtractedContact(BaseModel):
    """Ein vom Agenten aus Text erkannter Kontakt-Vorschlag."""

    name: str
    type: ContactType | None = None
    email: str | None = None
    phone: str | None = None
    notes: str | None = None


class ExtractedTask(BaseModel):
    """Eine vom Agenten aus Text erkannte Aufgabe (Vorschlag)."""

    title: str
    contact: str | None = None
    project: str | None = None
    due: date | None = None
    time_window: str | None = None


class ExtractedProjectUpdate(BaseModel):
    """Ein erkannter Statushinweis zu einem Projekt."""

    project: str
    status: ProjectStatus | None = None
    phase_note: str | None = None
    next_action: str | None = None
    waiting_on: WaitingOn | None = None


class ExtractedCompletion(BaseModel):
    """Eine erkannte Erledigungs-Aussage zu einer bestehenden offenen Aufgabe.

    ``task_id``/``task_title`` werden unverändert aus der dem Agenten mitgegebenen
    Liste offener Aufgaben übernommen (Schritt 8.17) — kein Raten, keine neue
    Aufgabe anlegen.
    """

    task_id: int
    task_title: str


class ExtractionResult(BaseModel):
    """Gebündeltes Ergebnis einer Extraktion aus einer Nachricht/Sprachnotiz.

    Dies ist das ``output_type`` des Pydantic-AI-Agenten. Der Agent fragt bei
    Unklarheiten nach (``clarification``), statt zu raten.
    """

    contacts: list[ExtractedContact] = Field(default_factory=list)
    tasks: list[ExtractedTask] = Field(default_factory=list)
    project_updates: list[ExtractedProjectUpdate] = Field(default_factory=list)
    completed: list[ExtractedCompletion] = Field(default_factory=list)
    clarification: str | None = None

    def is_empty(self) -> bool:
        return not (self.contacts or self.tasks or self.project_updates or self.completed)


# --------------------------------------------------------------------------- #
# Domänen-Entitäten (persistiert)                                             #
# --------------------------------------------------------------------------- #
class Contact(BaseModel):
    id: int | None = None
    name: str
    type: ContactType | None = None
    email: str | None = None
    phone: str | None = None
    channel: Channel | None = None
    notes: str | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class Project(BaseModel):
    id: int | None = None
    title: str
    contact_id: int | None = None
    status: ProjectStatus = ProjectStatus.ANFRAGE
    phase_note: str | None = None
    markdown_log_path: str | None = None
    next_action: str | None = None
    waiting_on: WaitingOn | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class Task(BaseModel):
    id: int | None = None
    title: str
    project_id: int | None = None
    contact_id: int | None = None
    due: date | None = None
    status: TaskStatus = TaskStatus.OFFEN
    source: TaskSource = TaskSource.MANUELL
    source_ref: str | None = None
    depends_on: list[int] = Field(default_factory=list)
    time_window: str | None = None
    window_start: date | None = None
    window_end: date | None = None
    created_at: datetime = Field(default_factory=_now)
