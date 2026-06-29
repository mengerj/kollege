"""Agenten-Layer (Pydantic AI).

Pydantic-AI-Agent mit ``ExtractionResult`` als Output-Typ und vier Tools,
die direkt auf das Repository schreiben. Provider modell-agnostisch via
``build_model(settings)``. In Tests über ``TestModel``/``FunctionModel``
ohne echten LLM-Aufruf (``defer_model_check=True``).
"""

from __future__ import annotations

import contextlib
import datetime

from pydantic_ai import Agent, RunContext
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
""".strip()

# Kein Modell bei Konstruktion: defer_model_check=True erlaubt,
# das Modell erst beim run()-Aufruf zu übergeben (wichtig für Tests).
agent: Agent[Repository, ExtractionResult] = Agent(
    output_type=ExtractionResult,
    deps_type=Repository,
    system_prompt=_SYSTEM_PROMPT,
    defer_model_check=True,
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


def run_extraction(
    transcript: str,
    repo: Repository,
    settings: Settings,
) -> ExtractionResult:
    """Extraktion aus Transkript synchron ausführen (Produktions-Pfad).

    Für asynchronen Einsatz direkt ``agent.run()`` nutzen.
    """
    model = build_model(settings)
    result = agent.run_sync(transcript, model=model, deps=repo)
    return result.output
