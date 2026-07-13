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
import time
from typing import Any

from pydantic_ai import Agent, RunContext, capture_run_messages
from pydantic_ai.agent import AgentRunResult
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter
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
    ExtractedTaskEdit,
    ExtractionResult,
    Project,
    ProjectStatus,
    Task,
    TaskSource,
    TaskStatus,
    WaitingOn,
)
from kollege.trace import NoopTraceWriter, TraceWriter, new_run_id

__all__ = [
    "agent",
    "build_known_names_context",
    "build_model",
    "build_open_tasks_context",
    "filter_known_names",
    "get_known_names_context",
    "get_open_tasks_context",
    "pre_warm_model",
    "run_clarification_response",
    "run_extraction",
    "run_gap_check",
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


def build_open_tasks_context(tasks: list[Task]) -> str:
    """Formatiert offene Aufgaben (mit IDs) als Kontext-Block für den Agenten.

    Gibt einen leeren String zurück, wenn keine Aufgaben offen sind. Der Block
    wird dem Transkript vorangestellt, damit der Agent Erledigungs-Aussagen im
    Text ("Zaun bei Müller ist gestrichen") gegen eine bestehende offene Aufgabe
    abgleichen kann, statt eine neue Aufgabe anzulegen (Schritt 8.17).
    """
    if not tasks:
        return ""
    lines: list[str] = [
        "[OFFENE AUFGABEN — zum Abgleich mit Erledigungs-Aussagen im Text]",
    ]
    for t in tasks:
        due = f" (fällig: {t.due})" if t.due else ""
        lines.append(f"#{t.id} {t.title}{due}")
    lines.append(
        "Beschreibt der Text, dass eine dieser Aufgaben erledigt wurde, trage sie im "
        "completed-Feld ein (task_id und task_title unverändert aus dieser Liste "
        "übernehmen) statt eine neue Aufgabe anzulegen. Schließe nur bei eindeutiger "
        "Übereinstimmung. Beschreibt der Text eine Korrektur/Änderung an einer dieser "
        "Aufgaben (Titel, Frist oder Projektzuordnung), trage sie im edits-Feld ein "
        "(task_id/task_title aus dieser Liste, nur geänderte Felder setzen) statt eine "
        "neue Aufgabe anzulegen. Bei Unsicherheit oder Mehrdeutigkeit: clarification-"
        "Feld setzen statt zu raten."
    )
    return "\n".join(lines)


def get_open_tasks_context(repo: Repository) -> str:
    """Offene Aufgaben aus dem Repository laden und als Kontext-String formatieren.

    Gibt einen leeren String zurück, wenn keine Aufgaben offen sind.
    """
    return build_open_tasks_context(repo.query_open_items())


_SYSTEM_PROMPT = """
Du bist Kollege, ein persönlicher Assistent für das Projektmanagement.
Deine Aufgabe: Aus Sprachnotizen oder Nachrichten strukturierte Daten extrahieren
und mit dem bestehenden Datenbestand abgleichen.

Extrahiere:
- Kontakte (Personen/Firmen, die erwähnt werden)
- Aufgaben (To-Dos, Fristen, Zeitfenster)
- Projektstatus-Hinweise (Statusänderungen, nächste Schritte, wer wartet auf wen)
- Erledigungen bestehender Aufgaben (siehe unten)
- Änderungen an bestehenden Aufgaben (siehe unten)

Nutze die verfügbaren Tools direkt zum Speichern erkannter Daten.
Falls etwas unklar ist, setze das clarification-Feld statt zu raten.
Antworte immer auf Deutsch.

Beschreibt der Text, dass eine bestehende **offene Aufgabe** (siehe ggf. mitgelieferte
Liste offener Aufgaben im Kontext) bereits erledigt wurde, trage sie im completed-Feld
ein (task_id und task_title unverändert aus der Liste übernehmen) statt eine neue
Aufgabe anzulegen. Schließe nur bei eindeutiger Übereinstimmung; bei Unsicherheit oder
Mehrdeutigkeit setze stattdessen das clarification-Feld. Ohne Liste offener Aufgaben im
Kontext oder ohne passenden Treffer bleibt completed leer.

Beschreibt der Text eine **Korrektur/Änderung an einer bestehenden offenen Aufgabe**
(z. B. „Der Ort Bad Eibling heißt eigentlich Bad Aibling", „bei der Zaun-Aufgabe
ist die Frist doch der Freitag", „ordne das der Gemeinde-Sache zu"), lege **keine neue
Aufgabe** an und schließe sie nicht — trage stattdessen einen Eintrag im edits-Feld ein:
task_id und task_title unverändert aus der Liste offener Aufgaben übernehmen und nur die
tatsächlich geänderten Felder setzen (new_title, new_due als ISO-Datum, new_project);
unveränderte Felder bleiben leer. Nur bei eindeutiger Zuordnung zu genau einer Aufgabe;
bei Unsicherheit/Mehrdeutigkeit stattdessen clarification setzen. Ohne Liste offener
Aufgaben im Kontext bleibt edits leer.

Beschreibt der Text eine **Lösch-Absicht** (z. B. „Lösche den Kontakt Müller",
„die Aufgabe ist Quatsch, weg damit", „setz alles zurück"), lege dafür **nichts**
an, rufe kein Tool auf und rate nicht, was gemeint ist — Löschen läuft
ausschließlich über die deterministischen Commands /loeschen kontakt <id>,
/loeschen projekt <id>, /loeschen aufgabe <id> und /zuruecksetzen (alles),
niemals über diese Extraktion. Setze stattdessen das clarification-Feld mit
einem Hinweis auf den passenden Command, damit die Lösch-Absicht nicht
stillschweigend ins Leere läuft (z. B. „Zum Löschen nutze bitte /loeschen
kontakt, projekt oder aufgabe <id>, oder /zuruecksetzen für alles.").

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


def _format_edit_changes(ed: ExtractedTaskEdit) -> str:
    """Geänderte Felder einer Aufgaben-Änderung menschenlesbar zusammenfassen.

    Zeigt für jedes gesetzte ``new_*``-Feld die Zieländerung, damit die Änderung
    auch im Revisions-/Lücken-Prüfungs-Prompt vollständig sichtbar ist (Schritt 8.20).
    """
    parts: list[str] = []
    if ed.new_title is not None:
        parts.append(f"Titel → «{ed.new_title}»")
    if ed.new_due is not None:
        parts.append(f"Frist → {ed.new_due}")
    if ed.new_project is not None:
        parts.append(f"Projekt → {ed.new_project}")
    return ", ".join(parts) if parts else "(keine Änderung)"


def _format_result_for_prompt(result: ExtractionResult, *, mark_gaps: bool = False) -> str:
    """Aktuelles ExtractionResult als lesbaren Text für Prompt-Läufe (Schritt 8.20).

    Eine gemeinsame Quelle der Wahrheit für den Revisions-Prompt (``run_revision``,
    Schritt 8.6) **und** den Lücken-Prüfungs-Prompt (``run_gap_check``, Schritt 8.18).
    Beide Varianten listen **alle** Kategorien inkl. **Erledigungen** und
    **Änderungen** — genau deren Fehlen im Revisions-Prompt ließ Korrektur-Läufe zuvor
    bereits erkannte Erledigungen verlieren (Schritt 8.20), weil das Modell den
    Vorschlag als frischen One-Shot neu erzeugt und nicht gezeigte Einträge de facto
    gelöscht werden.

    ``mark_gaps=True`` (Lücken-Prüfung): markiert fehlende Fälligkeit/Projekt-/
    Kontaktzuordnung **explizit** (»OHNE Fälligkeitsdatum«), damit der zweite
    Durchgang Lücken direkt sieht. ``mark_gaps=False`` (Korrektur-Lauf): kompakte Form.
    """
    lines: list[str] = []
    for c in result.contacts:
        lines.append(f"  - Kontakt: {c.name}")
    for t in result.tasks:
        if mark_gaps:
            due = f"fällig {t.due}" if t.due else "OHNE Fälligkeitsdatum"
            proj = f"Projekt {t.project}" if t.project else "OHNE Projektzuordnung"
            contact = f"Kontakt {t.contact}" if t.contact else "ohne Kontakt"
            lines.append(f"  - Aufgabe: {t.title} ({due}; {proj}; {contact})")
        else:
            due = f" (fällig: {t.due})" if t.due else ""
            proj = f" [{t.project}]" if t.project else ""
            lines.append(f"  - Aufgabe: {t.title}{proj}{due}")
    for pu in result.project_updates:
        status = f" → {pu.status}" if pu.status else ""
        label = "Projekt-Update" if mark_gaps else "Projekt"
        lines.append(f"  - {label}: {pu.project}{status}")
    for comp in result.completed:
        lines.append(f"  - Erledigung: #{comp.task_id} {comp.task_title}")
    for ed in result.edits:
        changes = _format_edit_changes(ed)
        lines.append(f"  - Aufgabe ändern: #{ed.task_id} {ed.task_title} — {changes}")
    if lines:
        return "\n".join(lines)
    return "  (nichts erkannt)" if mark_gaps else "  (leer)"


def _format_history(history: list[tuple[str, str]] | None) -> str:
    """Formatiert frühere Turns derselben Interaktion als Prompt-Block (Schritt 8.14).

    ``history`` enthält Turns *vor* dem aktuellen (z. B. frühere Korrekturen oder
    eine Rückfrage+Antwort), damit Referenzen wie »wie in der letzten Nachricht«
    über mehrere Korrektur-Runden hinweg aufgelöst werden können — nicht nur
    gegen das Ursprungstranskript und den zuletzt strukturierten Vorschlag.
    Gibt einen leeren String zurück, wenn keine Historie vorliegt.
    """
    if not history:
        return ""
    lines = [f"  [{label}] {text}" for label, text in history]
    return "Bisherige Turns dieser Interaktion:\n" + "\n".join(lines) + "\n\n"


def run_revision(
    original_transcript: str,
    current_result: ExtractionResult,
    correction: str,
    settings: Settings,
    known_names_context: str | None = None,
    open_tasks_context: str | None = None,
    history: list[tuple[str, str]] | None = None,
    trace: TraceWriter | None = None,
    run_id: str | None = None,
) -> ExtractionResult:
    """Revidiert ein ExtractionResult anhand eines Korrekturhinweises.

    Das LLM bekommt das Ursprungstranskript, den aktuellen Vorschlag und den
    Korrekturtext. Es liefert ein überarbeitetes ExtractionResult, das erneut
    als Vorschlag angezeigt wird (nichts wird bis zur Bestätigung persistiert).

    ``history``: frühere Turns *derselben Interaktion* (z. B. vorangegangene
    Korrekturen oder eine Rückfrage+Antwort), geordnet, ohne das Ursprungs-
    transkript und ohne die aktuelle Korrektur (die stehen bereits in eigenen
    Parametern). Löst Referenzen wie »wie in der letzten Nachricht« über
    mehrere Korrektur-Runden hinweg auf (Schritt 8.14).

    Intern wird ``run_extraction`` auf einem zusammengesetzten Prompt aufgerufen —
    so wird der gesamte Primär-/Fallback-Pfad wiederverwendet, inklusive
    Namensabgleich via ``known_names_context`` und Aufgaben-Abgleich (Erledigungen/
    Änderungen an bestehenden Aufgaben) via ``open_tasks_context`` (Schritt 8.19).
    """
    revision_prompt = (
        "[KORREKTUR-LAUF]\n"
        f"{_format_history(history)}"
        f"Ursprüngliches Transkript:\n{original_transcript}\n\n"
        f"Bisheriger Vorschlag:\n{_format_result_for_prompt(current_result)}\n\n"
        f"Korrektur:\n{correction}\n\n"
        "Überarbeite den Vorschlag entsprechend der Korrektur. Falls die Korrektur "
        "auf einen früheren Turn dieser Interaktion verweist (z. B. »wie in der "
        "letzten Nachricht«), nutze die oben stehende Historie. "
        "Übernimm alle Einträge des bisherigen Vorschlags unverändert, die von der "
        "Korrektur nicht betroffen sind — auch bereits erkannte Erledigungen und "
        "Änderungen an bestehenden Aufgaben. Entferne einen Eintrag nur, wenn die "
        "Korrektur das ausdrücklich verlangt. "
        "Extrahiere das korrigierte Ergebnis vollständig."
    )
    tmp_repo = Repository(sqlite3.connect(":memory:", check_same_thread=False))
    return run_extraction(
        revision_prompt,
        tmp_repo,
        settings,
        known_names_context=known_names_context,
        open_tasks_context=open_tasks_context,
        kind="revision",
        trace=trace,
        run_id=run_id,
    )


def run_gap_check(
    original_transcript: str,
    first_result: ExtractionResult,
    settings: Settings,
    known_names_context: str | None = None,
    open_tasks_context: str | None = None,
    trace: TraceWriter | None = None,
    run_id: str | None = None,
) -> ExtractionResult:
    """Zweiter Durchgang: Lücken füllen und Übersehenes nachtragen (Schritt 8.18).

    Der erste Extraktionsdurchgang ist ein One-Shot und lässt gelegentlich Dinge
    liegen: eine Aufgabe ohne Fälligkeitsdatum, obwohl der Text ein Timing nahelegt;
    eine Aufgabe ohne Projektzuordnung, obwohl andere Einträge derselben Nachricht
    (oder ein bekanntes Projekt) klar dazugehören; oder — der wichtigste Fall — eine
    im Transkript genannte Aufgabe, die komplett übersehen wurde.

    Dieser Lauf bekommt Transkript **und** das Erstergebnis und liefert ein
    **vollständiges, ergänztes** ExtractionResult. Weil ohnehin jeder Vorschlag vor
    der Persistenz bestätigt wird (Prinzip 3), soll das Modell Lücken bevorzugt mit
    einer gut begründeten Vermutung füllen statt bei jeder Kleinigkeit zurückzufragen
    — nur bei echter, wesentlicher Unklarheit wird eine ``clarification`` gestellt.

    Intern wird — wie bei ``run_revision`` — ``run_extraction`` auf einem
    zusammengesetzten Prompt aufgerufen, sodass Primär-/Fallback-Pfad und
    Namensabgleich unverändert wiederverwendet werden.
    """
    first_formatted = _format_result_for_prompt(first_result, mark_gaps=True)
    gap_prompt = (
        "[LÜCKEN-PRÜFUNG — ZWEITER DURCHGANG]\n"
        f"Ursprüngliches Transkript:\n{original_transcript}\n\n"
        f"Erster Extraktions-Vorschlag:\n{first_formatted}\n\n"
        "Prüfe den Vorschlag sorgfältig gegen das Transkript und ergänze ihn:\n"
        "1. Übersehen: Wurde eine Aufgabe, ein Kontakt, ein Projekt-Update oder eine "
        "Erledigung im Transkript genannt, fehlt aber im Vorschlag? Trage sie nach.\n"
        "2. Fälligkeit: Legt der Text ein Timing nahe (»vor dem Termin«, »diese Woche«, "
        "»bald«, ein Wochentag, ein konkretes Datum), fehlt aber bei einer Aufgabe das "
        "Datum? Leite ein konkretes ISO-Datum (YYYY-MM-DD) ab.\n"
        "3. Projektzuordnung: Gehört eine Aufgabe zu einem bekannten Projekt oder zu "
        "einem Projekt, das andere Einträge derselben Nachricht nennen? Ordne sie zu.\n"
        "4. Kontaktzuordnung: analog zur Projektzuordnung.\n"
        "Fülle Lücken mit einer gut begründeten Vermutung aus dem Kontext — die Nutzerin "
        "bestätigt jeden Vorschlag, bevor etwas gespeichert wird. Stelle nur bei echter, "
        "wesentlicher Unklarheit eine Rückfrage (clarification). Erfinde nichts, was das "
        "Transkript nicht hergibt, und lege keine Duplikate an.\n"
        "Gib das VOLLSTÄNDIGE, ergänzte Ergebnis zurück (alle bereits erkannten Einträge "
        "plus deine Ergänzungen), nicht nur die Änderungen."
    )
    tmp_repo = Repository(sqlite3.connect(":memory:", check_same_thread=False))
    return run_extraction(
        gap_prompt,
        tmp_repo,
        settings,
        known_names_context=known_names_context,
        open_tasks_context=open_tasks_context,
        kind="gap_check",
        trace=trace,
        run_id=run_id,
    )


def run_clarification_response(
    original_transcript: str,
    clarification_question: str,
    answer: str,
    settings: Settings,
    known_names_context: str | None = None,
    open_tasks_context: str | None = None,
    history: list[tuple[str, str]] | None = None,
    trace: TraceWriter | None = None,
    run_id: str | None = None,
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

    ``history``: frühere Turns *derselben Interaktion* vor dieser Rückfrage
    (z. B. eine vorangegangene Rückfrage+Antwort-Runde), siehe ``run_revision``
    (Schritt 8.14).

    Intern wird — wie bei ``run_revision`` — ``run_extraction`` auf einem
    zusammengesetzten Prompt aufgerufen, sodass Primär-/Fallback-Pfad,
    Namensabgleich (``known_names_context``) und Aufgaben-Abgleich
    (``open_tasks_context``, Schritt 8.19) unverändert wiederverwendet werden.
    """
    response_prompt = (
        "[RÜCKFRAGE-ANTWORT]\n"
        f"{_format_history(history)}"
        f"Ursprüngliches Transkript:\n{original_transcript}\n\n"
        f"Deine Rückfrage an die Nutzerin:\n{clarification_question}\n\n"
        f"Antwort der Nutzerin:\n{answer}\n\n"
        "Setze die Extraktion jetzt vollständig um. Bei Zustimmung (z. B. »ja«, »👍«, "
        "»passt«) lege die in der Rückfrage angebotenen Einträge an. Bei Ablehnung "
        "(»nein«) extrahiere nichts. Liefert die Antwort zusätzliche Angaben, "
        "berücksichtige sie. Falls sich die Antwort auf einen früheren Turn dieser "
        "Interaktion bezieht, nutze die oben stehende Historie. Stelle nur dann "
        "erneut eine Rückfrage, wenn weiterhin etwas Wesentliches unklar bleibt."
    )
    tmp_repo = Repository(sqlite3.connect(":memory:", check_same_thread=False))
    return run_extraction(
        response_prompt,
        tmp_repo,
        settings,
        known_names_context=known_names_context,
        open_tasks_context=open_tasks_context,
        kind="clarification_response",
        trace=trace,
        run_id=run_id,
    )


def _serialize_messages(messages: list[ModelMessage]) -> list[dict[str, Any]]:
    """Alle Messages eines Laufs (System-Prompts, Tool-Calls, Retries, Antwort)
    JSON-serialisierbar machen, für das Trace-Ereignis eines LLM-Laufs."""
    dumped: list[dict[str, Any]] = ModelMessagesTypeAdapter.dump_python(messages, mode="json")
    return dumped


def _trace_llm_result(
    writer: TraceWriter,
    run_id: str,
    *,
    kind: str,
    path: str,
    model_name: str,
    result: AgentRunResult[Any],
    messages: list[ModelMessage],
    started_at: float,
) -> None:
    """Erfolgreichen LLM-Lauf (Primär- oder Fallback-Pfad) ins Trace schreiben."""
    usage = result.usage
    output = result.output
    writer.write(
        "llm_run_result",
        run_id,
        {
            "kind": kind,
            "path": path,
            "model": model_name,
            "latency_s": round(time.monotonic() - started_at, 3),
            "usage": {
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "requests": usage.requests,
            },
            "messages": _serialize_messages(messages),
            "output": (
                output.model_dump(mode="json") if isinstance(output, ExtractionResult) else output
            ),
        },
    )


def _trace_llm_error(
    writer: TraceWriter,
    run_id: str,
    *,
    kind: str,
    path: str,
    model_name: str,
    exc: Exception,
    messages: list[ModelMessage],
    started_at: float,
) -> None:
    """Gescheiterten LLM-Lauf ins Trace schreiben — gerade Fehlerfälle sind die
    interessanten (Schritt 8.11-Analyse: Primär-Pfad scheitert bei manchen Modellen
    fast immer). ``messages`` stammt aus ``capture_run_messages()``, damit auch
    abgebrochene Läufe ihre Tool-Calls/Retries zeigen."""
    writer.write(
        "llm_run_error",
        run_id,
        {
            "kind": kind,
            "path": path,
            "model": model_name,
            "latency_s": round(time.monotonic() - started_at, 3),
            "exception_type": type(exc).__name__,
            "exception_text": str(exc),
            "messages": _serialize_messages(messages),
        },
    )


def run_extraction(
    transcript: str,
    repo: Repository,
    settings: Settings,
    known_names_context: str | None = None,
    open_tasks_context: str | None = None,
    kind: str = "extraktion",
    trace: TraceWriter | None = None,
    run_id: str | None = None,
) -> ExtractionResult:
    """Extraktion aus Transkript synchron ausführen (Produktions-Pfad).

    Primär-Pfad: Modell gibt ``ExtractionResult`` via ``final_result``-Tool zurück.
    Fallback: Modell speichert via Domain-Tools in ``repo``, ExtractionResult wird
    aus dem DB-Zustand rekonstruiert (für kleinere lokale Modelle wie qwen2.5:7b).

    ``known_names_context``: Bekannte Kontakt-/Projektnamen aus dem Repository,
    formatiert via ``build_known_names_context()``. Wird dem Transkript vorangestellt,
    damit das LLM Whisper-Verhörer erkennen und normalisieren kann.

    ``open_tasks_context``: Offene Aufgaben aus dem Repository, formatiert via
    ``build_open_tasks_context()``. Wird ebenfalls vorangestellt, damit das LLM
    Erledigungs-Aussagen im Text gegen eine bestehende Aufgabe abgleichen kann
    (Schritt 8.17).

    ``kind``: Laufart für die Trace-Aufzeichnung — ``extraktion`` (Default),
    ``gap_check``, ``revision`` oder ``clarification_response`` (gesetzt von den
    jeweiligen Wrapper-Funktionen). ``trace``/``run_id`` (Schritt 8.21): opt-in
    Aufzeichnung des kompletten Laufs (Kontext, Tool-Calls, Rückgaben, Fehler) für
    Live-Debugging; ohne Writer (Default) entsteht kein zusätzlicher Overhead.
    """
    writer = trace if trace is not None else NoopTraceWriter()
    rid = run_id if run_id is not None else new_run_id()
    model = build_model(settings)

    # Bekannte Namen und offene Aufgaben dem Transkript voranstellen (nur wenn nicht leer).
    context_blocks = [block for block in (known_names_context, open_tasks_context) if block]
    augmented = transcript
    if context_blocks:
        augmented = "\n\n".join([*context_blocks, f"[NOTIZ]\n{transcript}"])

    writer.write(
        "llm_run_start",
        rid,
        {
            "kind": kind,
            "provider": str(settings.llm_provider),
            "model": settings.llm_model,
            "prompt": augmented,
        },
    )

    # Primär-Pfad: Tool-Output-Modus (ExtractionResult als final_result-Tool).
    # Wird von TestModel/FunctionModel im CI genutzt und von starken Modellen.
    started_at = time.monotonic()
    with capture_run_messages() as primary_messages:
        try:
            result = agent.run_sync(augmented, model=model, deps=repo, retries=1)
            _trace_llm_result(
                writer,
                rid,
                kind=kind,
                path="primär",
                model_name=settings.llm_model,
                result=result,
                messages=primary_messages,
                started_at=started_at,
            )
            return result.output
        except (UnexpectedModelBehavior, sqlite3.DatabaseError) as exc:
            _trace_llm_error(
                writer,
                rid,
                kind=kind,
                path="primär",
                model_name=settings.llm_model,
                exc=exc,
                messages=primary_messages,
                started_at=started_at,
            )

    # Fallback: Modell ruft Domain-Tools auf, aber kein final_result-Tool.
    # Frische Verbindung vermeidet Doppelschreibungen aus dem Primär-Lauf.
    fallback_conn = sqlite3.connect(":memory:", check_same_thread=False)
    fallback_repo = Repository(fallback_conn)
    fallback_started_at = time.monotonic()
    with capture_run_messages() as fallback_messages:
        try:
            text_result = agent.run_sync(
                augmented, model=model, deps=fallback_repo, output_type=str, retries=3
            )
        except Exception as exc:
            _trace_llm_error(
                writer,
                rid,
                kind=kind,
                path="fallback",
                model_name=settings.llm_model,
                exc=exc,
                messages=fallback_messages,
                started_at=fallback_started_at,
            )
            raise
        _trace_llm_result(
            writer,
            rid,
            kind=kind,
            path="fallback",
            model_name=settings.llm_model,
            result=text_result,
            messages=fallback_messages,
            started_at=fallback_started_at,
        )
    text_output: str = text_result.output
    # Wenn nichts gespeichert wurde, könnte es eine Rückfrage sein.
    clarification: str | None = None
    if not fallback_repo.get_all_contacts() and not fallback_repo.query_open_items():
        clarification = text_output.strip() if text_output else None
    return _rebuild_from_repo(fallback_repo, clarification=clarification)
