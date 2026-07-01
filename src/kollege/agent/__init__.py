"""Agenten-Layer (Pydantic AI).

Pydantic-AI-Agent mit ``ExtractionResult`` als Output-Typ und vier Tools,
die direkt auf das Repository schreiben. Provider modell-agnostisch via
``build_model(settings)``. In Tests über ``TestModel``/``FunctionModel``
ohne echten LLM-Aufruf (``defer_model_check=True``).
"""

from __future__ import annotations

import contextlib
import datetime
import logging
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
    Contact,
    ContactType,
    ExtractedContact,
    ExtractedProjectUpdate,
    ExtractedTask,
    ExtractionResult,
    Project,
    ProjectStatus,
    Task,
    TaskSource,
    TaskStatus,
    WaitingOn,
)

__all__ = [
    "agent",
    "build_known_names_context",
    "build_model",
    "filter_known_names",
    "get_known_names_context",
    "pre_warm_model",
    "run_clarification_response",
    "run_extraction",
    "run_revision",
]

_logger = logging.getLogger("kollege.agent")

_MAX_KNOWN_NAMES = 80


def filter_known_names(
    contacts: list[Contact],
    projects: list[Project],
    max_names: int = _MAX_KNOWN_NAMES,
) -> tuple[list[str], list[str]]:
    """Bekannte Kontakt- und Projektnamen vorfiltern.

    Sortiert nach ``updated_at`` absteigend (kürzlich aktiv → zuerst) und
    begrenzt auf ``max_names // 2`` je Kategorie, damit der Kontext nicht
    unbegrenzt wächst. Verhindert Kontext-Überschwemmung bei großer DB.
    """
    half = max(1, max_names // 2)
    sorted_contacts = sorted(contacts, key=lambda c: c.updated_at, reverse=True)
    sorted_projects = sorted(projects, key=lambda p: p.updated_at, reverse=True)
    return [c.name for c in sorted_contacts[:half]], [p.title for p in sorted_projects[:half]]


def build_known_names_context(
    contact_names: list[str],
    project_names: list[str],
) -> str:
    """Formatiert bekannte Namen als Kontext-Block für den Agenten.

    Gibt einen leeren String zurück, wenn beide Listen leer sind.
    Der Block wird dem Transkript vorangestellt und weist den Agenten an,
    Namen aus dem Transkript gegen die Liste abzugleichen (Whisper-Verhörer
    wie „Herr Schnitt" → „Schmidt" können so ohne Revisions-Schleife
    korrigiert werden).
    """
    if not contact_names and not project_names:
        return ""
    lines: list[str] = [
        "[BEKANNTE NAMEN — nur zur Normalisierung, nicht als neue Einträge extrahieren]",
    ]
    if contact_names:
        lines.append("Kontakte: " + ", ".join(contact_names))
    if project_names:
        lines.append("Projekte: " + ", ".join(project_names))
    lines.append(
        "Gleiche Namen im Transkript mit dieser Liste ab: "
        "Falls ein Name einem bekannten Namen stark ähnelt (z. B. »Herr Schnitt« → »Schmidt«), "
        "verwende den bekannten Namen. "
        "Bei echter Mehrdeutigkeit: clarification-Feld setzen statt zu raten. "
        "Unbekannte Namen einfach so übernehmen."
    )
    return "\n".join(lines)


def get_known_names_context(
    repo: Repository,
    max_names: int = _MAX_KNOWN_NAMES,
) -> str:
    """Bekannte Namen aus dem Repository laden und als Kontext-String formatieren.

    Gibt einen leeren String zurück, wenn das Repository leer ist.
    """
    contacts = repo.get_all_contacts()
    projects = repo.get_all_projects()
    c_names, p_names = filter_known_names(contacts, projects, max_names)
    return build_known_names_context(c_names, p_names)


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


def pre_warm_model(settings: Settings) -> None:
    """Ollama-Modell vorladen, bevor die erste Nachricht eintrifft.

    Cold-Start (Modell aus VRAM/RAM verdrängt) dauert je nach Modell und
    RAM-Auslastung mehrere Minuten. Beim Start des Dienstes verhindert Pre-Warm,
    dass die allererste Sprachnotiz diese Latenz erlebt.

    Scheitert das Vorladen (Ollama noch nicht bereit), wird nur gewarnt — der
    Dienst startet trotzdem und lädt das Modell beim ersten echten Aufruf.

    Nur für Ollama sinnvoll; Cloud-Provider brauchen kein Pre-Warm.
    """
    if settings.llm_provider != LLMProvider.OLLAMA:
        return

    _logger.info("Pre-Warm: Lade Modell %s …", settings.llm_model)
    try:
        import httpx

        # Ollama native API: POST /api/generate mit leerem Prompt lädt das Modell
        # ohne eine vollständige Inferenz durchzuführen.
        # ollama_base_url endet auf /v1 (OpenAI-kompatibel); für die native API
        # brauchen wir nur den Basis-Anteil.
        base = settings.ollama_base_url.rstrip("/").removesuffix("/v1")
        resp = httpx.post(
            f"{base}/api/generate",
            json={"model": settings.llm_model, "prompt": "", "stream": False},
            timeout=120.0,
        )
        resp.raise_for_status()
        _logger.info("Pre-Warm: Modell %s geladen und bereit.", settings.llm_model)
    except ImportError:
        _logger.warning(
            "Pre-Warm: httpx nicht installiert (uv sync --group signal) — übersprungen."
        )
    except Exception as exc:
        _logger.warning(
            "Pre-Warm: Fehlgeschlagen (%s) — Modell wird beim ersten Aufruf geladen.", exc
        )


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
    if settings.llm_provider == LLMProvider.OPENROUTER:
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider

        return OpenAIChatModel(
            settings.llm_model,
            provider=OpenAIProvider(
                base_url=settings.openrouter_base_url,
                api_key=settings.openrouter_api_key,
            ),
        )
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


def _format_result_for_revision(result: ExtractionResult) -> str:
    """Aktuelles ExtractionResult als lesbaren Text für den Revisions-Prompt."""
    lines: list[str] = []
    for c in result.contacts:
        lines.append(f"  - Kontakt: {c.name}")
    for t in result.tasks:
        due = f" (fällig: {t.due})" if t.due else ""
        proj = f" [{t.project}]" if t.project else ""
        lines.append(f"  - Aufgabe: {t.title}{proj}{due}")
    for pu in result.project_updates:
        status = f" → {pu.status}" if pu.status else ""
        lines.append(f"  - Projekt: {pu.project}{status}")
    return "\n".join(lines) if lines else "  (leer)"


def run_revision(
    original_transcript: str,
    current_result: ExtractionResult,
    correction: str,
    settings: Settings,
    known_names_context: str | None = None,
) -> ExtractionResult:
    """Revidiert ein ExtractionResult anhand eines Korrekturhinweises.

    Das LLM bekommt das Ursprungstranskript, den aktuellen Vorschlag und den
    Korrekturtext. Es liefert ein überarbeitetes ExtractionResult, das erneut
    als Vorschlag angezeigt wird (nichts wird bis zur Bestätigung persistiert).

    Intern wird ``run_extraction`` auf einem zusammengesetzten Prompt aufgerufen —
    so wird der gesamte Primär-/Fallback-Pfad wiederverwendet, inklusive
    Namensabgleich via ``known_names_context``.
    """
    revision_prompt = (
        "[KORREKTUR-LAUF]\n"
        f"Ursprüngliches Transkript:\n{original_transcript}\n\n"
        f"Bisheriger Vorschlag:\n{_format_result_for_revision(current_result)}\n\n"
        f"Korrektur:\n{correction}\n\n"
        "Überarbeite den Vorschlag entsprechend der Korrektur. "
        "Extrahiere das korrigierte Ergebnis vollständig."
    )
    tmp_repo = Repository(sqlite3.connect(":memory:", check_same_thread=False))
    return run_extraction(
        revision_prompt, tmp_repo, settings, known_names_context=known_names_context
    )


def run_clarification_response(
    original_transcript: str,
    clarification_question: str,
    answer: str,
    settings: Settings,
    known_names_context: str | None = None,
) -> ExtractionResult:
    """Beantwortet eine zuvor gestellte Rückfrage und extrahiert erneut.

    Wenn ``run_extraction`` unsicher war, hat es eine Rückfrage (``clarification``)
    gestellt statt zu raten. Diese Funktion führt den Dialog fort: Das LLM bekommt
    das Ursprungstranskript, die von ihm gestellte Rückfrage und die Antwort der
    Nutzerin (Freitext, transkribierte Sprache oder ein simples "Ja." aus einem
    👍-Tapback) und liefert das nun aufgelöste ``ExtractionResult``.

    Bei Zustimmung legt es die in der Rückfrage angebotenen Einträge an; bei
    Ablehnung bleibt das Ergebnis leer; liefert die Antwort neue Angaben, fließen
    sie ein. Nur bei weiterhin echter Unklarheit wird erneut eine Rückfrage gestellt.

    Intern wird — wie bei ``run_revision`` — ``run_extraction`` auf einem
    zusammengesetzten Prompt aufgerufen, sodass Primär-/Fallback-Pfad und
    Namensabgleich unverändert wiederverwendet werden.
    """
    response_prompt = (
        "[RÜCKFRAGE-ANTWORT]\n"
        f"Ursprüngliches Transkript:\n{original_transcript}\n\n"
        f"Deine Rückfrage an die Nutzerin:\n{clarification_question}\n\n"
        f"Antwort der Nutzerin:\n{answer}\n\n"
        "Setze die Extraktion jetzt vollständig um. Bei Zustimmung (z. B. »ja«, »👍«, "
        "»passt«) lege die in der Rückfrage angebotenen Einträge an. Bei Ablehnung "
        "(»nein«) extrahiere nichts. Liefert die Antwort zusätzliche Angaben, "
        "berücksichtige sie. Stelle nur dann erneut eine Rückfrage, wenn weiterhin "
        "etwas Wesentliches unklar bleibt."
    )
    tmp_repo = Repository(sqlite3.connect(":memory:", check_same_thread=False))
    return run_extraction(
        response_prompt, tmp_repo, settings, known_names_context=known_names_context
    )


def run_extraction(
    transcript: str,
    repo: Repository,
    settings: Settings,
    known_names_context: str | None = None,
) -> ExtractionResult:
    """Extraktion aus Transkript synchron ausführen (Produktions-Pfad).

    Primär-Pfad: Modell gibt ``ExtractionResult`` via ``final_result``-Tool zurück.
    Fallback: Modell speichert via Domain-Tools in ``repo``, ExtractionResult wird
    aus dem DB-Zustand rekonstruiert (für kleinere lokale Modelle wie qwen2.5:7b).

    ``known_names_context``: Bekannte Kontakt-/Projektnamen aus dem Repository,
    formatiert via ``build_known_names_context()``. Wird dem Transkript vorangestellt,
    damit das LLM Whisper-Verhörer erkennen und normalisieren kann.
    """
    model = build_model(settings)

    # Bekannte Namen dem Transkript voranstellen (nur wenn nicht leer).
    augmented = transcript
    if known_names_context:
        augmented = f"{known_names_context}\n\n[NOTIZ]\n{transcript}"

    # Primär-Pfad: Tool-Output-Modus (ExtractionResult als final_result-Tool).
    # Wird von TestModel/FunctionModel im CI genutzt und von starken Modellen.
    try:
        result = agent.run_sync(augmented, model=model, deps=repo, retries=1)
        return result.output
    except (UnexpectedModelBehavior, sqlite3.DatabaseError):
        pass

    # Fallback: Modell ruft Domain-Tools auf, aber kein final_result-Tool.
    # Frische Verbindung vermeidet Doppelschreibungen aus dem Primär-Lauf.
    fallback_conn = sqlite3.connect(":memory:", check_same_thread=False)
    fallback_repo = Repository(fallback_conn)
    text_result = agent.run_sync(
        augmented, model=model, deps=fallback_repo, output_type=str, retries=3
    )
    text_output: str = text_result.output
    # Wenn nichts gespeichert wurde, könnte es eine Rückfrage sein.
    clarification: str | None = None
    if not fallback_repo.get_all_contacts() and not fallback_repo.query_open_items():
        clarification = text_output.strip() if text_output else None
    return _rebuild_from_repo(fallback_repo, clarification=clarification)
