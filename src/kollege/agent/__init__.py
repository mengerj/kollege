"""Agenten-Layer (Pydantic AI).

Pydantic-AI-Agent mit ``ExtractionResult`` als Output-Typ und vier Tools,
die direkt auf das Repository schreiben. Provider modell-agnostisch via
``build_model(settings)``. In Tests über ``TestModel``/``FunctionModel``
ohne echten LLM-Aufruf (``defer_model_check=True``).
"""

from __future__ import annotations

import contextlib
import datetime
import sqlite3

from pydantic_ai import Agent, RunContext
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.ollama import OllamaModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.ollama import OllamaProvider

from kollege.config import LLMProvider, Settings
from kollege.db.repository import Repository
from kollege.models import (
    ContactType,
    ExtractedContact,
    ExtractedProjectUpdate,
    ExtractedTask,
    ExtractionResult,
    ProjectStatus,
    Task,
    TaskSource,
    TaskStatus,
    WaitingOn,
)

__all__ = ["agent", "build_model", "run_extraction"]

_SYSTEM_PROMPT = """
Du bist Kollege, ein persönlicher Assistent für eine selbstständige Landschaftsarchitektin.
Deine Aufgabe: Aus Sprachnotizen oder Nachrichten strukturierte Daten extrahieren.

Extrahiere:
- Kontakte (Personen/Firmen, die erwähnt werden)
- Aufgaben (To-Dos, Fristen, Zeitfenster)
- Projektstatus-Hinweise (Statusänderungen, nächste Schritte, wer wartet auf wen)

Nutze die verfügbaren Tools direkt zum Speichern erkannter Daten.
Falls etwas unklar ist, setze das clarification-Feld statt zu raten.
Antworte immer auf Deutsch.

Erfasse so **wenige, klar getrennte** Einträge wie möglich:
- Lege pro echter Aufgabe **genau eine** Aufgabe an. Zerlege einen Satz nicht in
  mehrere überlappende Aufgaben und lege **keine Duplikate** an.
- Nur wenn wirklich mehrere unterschiedliche To-Dos genannt werden, trenne sie.
- Im Zweifel: lieber ein Eintrag zu wenig als ein doppelter.
""".strip()

# Kein Modell bei Konstruktion: defer_model_check=True erlaubt,
# das Modell erst beim run()-Aufruf zu übergeben (wichtig für Tests).
agent: Agent[Repository, ExtractionResult] = Agent(
    output_type=ExtractionResult,
    deps_type=Repository,
    system_prompt=_SYSTEM_PROMPT,
    defer_model_check=True,
)

_WEEKDAYS_DE = (
    "Montag",
    "Dienstag",
    "Mittwoch",
    "Donnerstag",
    "Freitag",
    "Samstag",
    "Sonntag",
)


@agent.system_prompt
def _today_prompt() -> str:
    """Aktuelles Datum injizieren, damit relative Fristen korrekt aufgelöst werden.

    Das LLM kennt das heutige Datum nicht und würde "morgen"/"nächsten Freitag"/
    "07.07" sonst relativ zu seinem Trainingsstand raten.
    """
    today = datetime.date.today()
    return (
        f"Heutiges Datum: {today.isoformat()} ({_WEEKDAYS_DE[today.weekday()]}). "
        'Löse relative Zeitangaben (z. B. "morgen", "übermorgen", "nächsten Freitag", '
        '"07.07") immer relativ zu diesem Datum auf. Tagesangaben ohne Jahr beziehen '
        "sich auf das nächste zukünftige Vorkommen. Gib Fristen stets als ISO-Datum "
        "(YYYY-MM-DD) an."
    )


@agent.tool
def upsert_contact(
    ctx: RunContext[Repository],
    name: str,
    contact_type: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    notes: str | None = None,
) -> str:
    """Kontakt speichern oder aktualisieren (Namens-Dedup).

    contact_type: privat | gemeinde | dienstleister (oder leer lassen).
    """
    ct: ContactType | None = None
    if contact_type:
        with contextlib.suppress(ValueError):
            ct = ContactType(contact_type)
    saved = ctx.deps.upsert_contact(
        ExtractedContact(name=name, type=ct, email=email, phone=phone, notes=notes)
    )
    return f"Kontakt gespeichert: {saved.name} (ID {saved.id})"


@agent.tool
def create_task(
    ctx: RunContext[Repository],
    title: str,
    contact_name: str | None = None,
    project_title: str | None = None,
    due: str | None = None,
    time_window: str | None = None,
) -> str:
    """Neue Aufgabe anlegen.

    Kontakt und Projekt werden per Name aufgelöst (müssen nicht vorher angelegt sein).
    due: ISO-8601-Datum (YYYY-MM-DD) oder leer lassen.
    """
    contact_id: int | None = None
    if contact_name:
        c = ctx.deps.get_contact_by_name(contact_name)
        if c is not None and c.id is not None:
            contact_id = c.id

    project_id: int | None = None
    if project_title:
        p = ctx.deps.get_or_create_project(project_title, contact_id=contact_id)
        if p.id is not None:
            project_id = p.id

    due_date: datetime.date | None = None
    if due:
        with contextlib.suppress(ValueError):
            due_date = datetime.date.fromisoformat(due)

    saved = ctx.deps.create_task(
        Task(
            title=title,
            contact_id=contact_id,
            project_id=project_id,
            due=due_date,
            time_window=time_window,
            status=TaskStatus.OFFEN,
            source=TaskSource.SPRACHNOTIZ,
        )
    )
    return f"Aufgabe angelegt: {saved.title!r} (ID {saved.id})"


@agent.tool
def update_project_status(
    ctx: RunContext[Repository],
    project_title: str,
    status: str | None = None,
    next_action: str | None = None,
    waiting_on: str | None = None,
    phase_note: str | None = None,
) -> str:
    """Projektstatus aktualisieren.

    status: anfrage | planung | umsetzung | pausiert | abgeschlossen
    waiting_on: ich | kunde | dienstleister
    """
    project = ctx.deps.get_or_create_project(project_title)
    if status:
        with contextlib.suppress(ValueError):
            project.status = ProjectStatus(status)
    if next_action is not None:
        project.next_action = next_action
    if waiting_on is not None:
        with contextlib.suppress(ValueError):
            project.waiting_on = WaitingOn(waiting_on)
    if phase_note is not None:
        project.phase_note = phase_note
    updated = ctx.deps.update_project(project)
    return f"Projekt aktualisiert: {updated.title!r} (Status: {updated.status})"


@agent.tool
def query_open_items(ctx: RunContext[Repository]) -> str:
    """Alle offenen Aufgaben zurückgeben."""
    tasks = ctx.deps.query_open_items()
    if not tasks:
        return "Keine offenen Aufgaben."
    lines = [f"- [{t.id}] {t.title}" for t in tasks]
    return "\n".join(lines)


def build_model(settings: Settings) -> Model:
    """Pydantic-AI-Model aus Config erzeugen (lokal-first: Ollama).

    Ollama: OpenAI-kompatible API auf lokalem Server.
    Anthropic: benötigt ANTHROPIC_API_KEY in der Umgebung.
    OpenAI: benötigt OPENAI_API_KEY in der Umgebung.
    """
    if settings.llm_provider == LLMProvider.OLLAMA:
        provider = OllamaProvider(base_url=settings.ollama_base_url)
        return OllamaModel(settings.llm_model, provider=provider)
    if settings.llm_provider == LLMProvider.ANTHROPIC:
        return AnthropicModel(settings.llm_model, provider=AnthropicProvider())
    # OpenAI-Fallback
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    return OpenAIChatModel(settings.llm_model, provider=OpenAIProvider())


def _rebuild_from_repo(repo: Repository, clarification: str | None = None) -> ExtractionResult:
    """Rekonstruiert ExtractionResult aus dem DB-Zustand eines frischen Temp-Repos.

    Verwendet für den Fallback-Pfad, wenn das Modell kein ``final_result``-Tool
    aufruft (z. B. kleinere Ollama-Modelle). Die Kontakte, Tasks und Projekte
    wurden bereits via Tools in ``repo`` gespeichert.
    """
    all_contacts = repo.get_all_contacts()
    all_projects = repo.get_all_projects()
    open_tasks = repo.query_open_items()

    project_by_id = {p.id: p for p in all_projects if p.id is not None}
    contact_by_id = {c.id: c for c in all_contacts if c.id is not None}

    extracted_contacts = [
        ExtractedContact(
            name=c.name,
            type=c.type,
            email=c.email,
            phone=c.phone,
            notes=c.notes,
        )
        for c in all_contacts
    ]

    extracted_tasks = [
        ExtractedTask(
            title=t.title,
            contact=contact_by_id[t.contact_id].name if t.contact_id in contact_by_id else None,
            project=project_by_id[t.project_id].title if t.project_id in project_by_id else None,
            due=t.due,
            time_window=t.time_window,
        )
        for t in open_tasks
    ]

    extracted_updates = [
        ExtractedProjectUpdate(
            project=p.title,
            status=p.status if p.status != ProjectStatus.ANFRAGE else None,
            phase_note=p.phase_note,
            next_action=p.next_action,
            waiting_on=p.waiting_on,
        )
        for p in all_projects
        if p.status != ProjectStatus.ANFRAGE or p.phase_note or p.next_action or p.waiting_on
    ]

    return ExtractionResult(
        contacts=extracted_contacts,
        tasks=extracted_tasks,
        project_updates=extracted_updates,
        clarification=clarification,
    )


def run_extraction(
    transcript: str,
    repo: Repository,
    settings: Settings,
) -> ExtractionResult:
    """Extraktion aus Transkript synchron ausführen (Produktions-Pfad).

    Primär-Pfad: Modell gibt ``ExtractionResult`` via ``final_result``-Tool zurück.
    Fallback: Modell speichert via Domain-Tools in ``repo``, ExtractionResult wird
    aus dem DB-Zustand rekonstruiert (für kleinere lokale Modelle wie qwen2.5:7b).
    """
    model = build_model(settings)

    # Primär-Pfad: Tool-Output-Modus (ExtractionResult als final_result-Tool).
    # Wird von TestModel/FunctionModel im CI genutzt und von starken Modellen.
    try:
        result = agent.run_sync(transcript, model=model, deps=repo, retries=1)
        return result.output
    except (UnexpectedModelBehavior, sqlite3.DatabaseError):
        pass

    # Fallback: Modell ruft Domain-Tools auf, aber kein final_result-Tool.
    # Frische Verbindung vermeidet Doppelschreibungen aus dem Primär-Lauf.
    fallback_conn = sqlite3.connect(":memory:", check_same_thread=False)
    fallback_repo = Repository(fallback_conn)
    text_result = agent.run_sync(
        transcript, model=model, deps=fallback_repo, output_type=str, retries=3
    )
    text_output: str = text_result.output
    # Wenn nichts gespeichert wurde, könnte es eine Rückfrage sein.
    clarification: str | None = None
    if not fallback_repo.get_all_contacts() and not fallback_repo.query_open_items():
        clarification = text_output.strip() if text_output else None
    return _rebuild_from_repo(fallback_repo, clarification=clarification)
