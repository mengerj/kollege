"""Tests für kollege/agent/.

Strategie:
- ``TestModel(call_tools=[])`` — Agent-Struktur ohne Tool-Aufrufe prüfen.
- ``FunctionModel`` — kontrollierte Tool-Aufrufe + DB-Seiteneffekte prüfen.

Eval-Set (Fixture-Transkripte) lebt in ``tests/test_eval.py``.
Kein echter LLM-Aufruf, kein Netzwerk: CI-sicher.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from kollege.agent import _SYSTEM_PROMPT, agent, build_model
from kollege.config import LLMProvider, Settings
from kollege.db import Repository
from kollege.models import (
    ExtractedCompletion,
    ExtractionResult,
    Task,
    TaskSource,
    TaskStatus,
    WaitingOn,
)

# --------------------------------------------------------------------------- #
# Hilfsfunktionen                                                               #
# --------------------------------------------------------------------------- #


def _repo() -> Repository:
    """In-Memory-Repository für isolierte Tests.

    check_same_thread=False: Tools laufen in pydantic-ai's ThreadPoolExecutor.
    """
    return Repository(sqlite3.connect(":memory:", check_same_thread=False))


# --------------------------------------------------------------------------- #
# Struktur-Tests (kein Tool-Aufruf, kein LLM)                                  #
# --------------------------------------------------------------------------- #


def test_agent_output_type_is_extraction_result() -> None:
    """Agent gibt ExtractionResult zurück — auch ohne Tool-Aufrufe."""
    repo = _repo()
    result = agent.run_sync("Einfacher Text", model=TestModel(call_tools=[]), deps=repo)
    assert isinstance(result.output, ExtractionResult)


def test_agent_output_is_valid_when_no_tools_called() -> None:
    """ExtractionResult ist bei leerem Run gültig (kein Crash)."""
    repo = _repo()
    result = agent.run_sync("nichts zu extrahieren", model=TestModel(call_tools=[]), deps=repo)
    out = result.output
    assert isinstance(out, ExtractionResult)
    assert isinstance(out.contacts, list)
    assert isinstance(out.tasks, list)
    assert isinstance(out.project_updates, list)


def test_system_prompt_points_delete_intent_to_slash_commands() -> None:
    """Schritt 8.22: Eine Lösch-Absicht im Freitext soll nicht mehr leer im
    ExtractionResult verschwinden, sondern per clarification auf die
    deterministischen Lösch-Commands verweisen (Regressionsschutz für die
    Prompt-Instruktion)."""
    assert "/loeschen" in _SYSTEM_PROMPT
    assert "/zuruecksetzen" in _SYSTEM_PROMPT
    assert "clarification" in _SYSTEM_PROMPT.split("Lösch-Absicht")[1]


# --------------------------------------------------------------------------- #
# build_model                                                                   #
# --------------------------------------------------------------------------- #


def test_build_model_returns_ollama_model() -> None:
    """build_model() erzeugt bei Provider=OLLAMA ein OllamaModel."""
    from pydantic_ai.models.ollama import OllamaModel

    settings = Settings.model_construct(
        llm_provider=LLMProvider.OLLAMA,
        llm_model="qwen2.5:7b-instruct",
        ollama_base_url="http://localhost:11434/v1",
    )
    model = build_model(settings)
    assert isinstance(model, OllamaModel)


def test_build_model_returns_openai_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """build_model() erzeugt bei Provider=OPENAI ein OpenAIChatModel."""
    from pydantic_ai.models.openai import OpenAIChatModel

    monkeypatch.setenv("OPENAI_API_KEY", "sk-dummy")
    settings = Settings.model_construct(
        llm_provider=LLMProvider.OPENAI,
        llm_model="gpt-4o-mini",
    )
    model = build_model(settings)
    assert isinstance(model, OpenAIChatModel)


def test_build_model_returns_openrouter_model() -> None:
    """build_model() erzeugt bei Provider=OPENROUTER ein OpenAIChatModel (OpenAI-kompatibel)."""
    from pydantic_ai.models.openai import OpenAIChatModel

    settings = Settings.model_construct(
        llm_provider=LLMProvider.OPENROUTER,
        llm_model="mistralai/mistral-large",
        openrouter_base_url="https://openrouter.ai/api/v1",
        openrouter_api_key="sk-or-dummy",
    )
    model = build_model(settings)
    assert isinstance(model, OpenAIChatModel)


# --------------------------------------------------------------------------- #
# Tool-Tests via FunctionModel                                                  #
# --------------------------------------------------------------------------- #


def _make_tool_model(tool_name: str, tool_args: dict[str, object]) -> FunctionModel:
    """FunctionModel: ruft genau einen Tool auf, gibt dann ein ExtractionResult aus.

    Der Agent läuft im Tool-Output-Modus (allow_text_output=False).
    Finale Antwort muss über das synthetische 'final_result'-Tool kommen.
    """
    calls: list[int] = []
    _empty_result = ExtractionResult().model_dump_json()

    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if not calls:
            calls.append(1)
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name=tool_name,
                        args=json.dumps(tool_args),
                    )
                ]
            )
        return ModelResponse(parts=[ToolCallPart(tool_name="final_result", args=_empty_result)])

    return FunctionModel(fn)


def test_upsert_contact_tool_writes_to_db() -> None:
    """Tool upsert_contact legt Kontakt in der DB an."""
    repo = _repo()
    model = _make_tool_model(
        "upsert_contact",
        {"name": "Frau Müller", "contact_type": "privat", "email": "mueller@example.com"},
    )
    agent.run_sync("...", model=model, deps=repo)

    contact = repo.get_contact_by_name("Frau Müller")
    assert contact is not None
    assert contact.email == "mueller@example.com"


def test_upsert_contact_tool_handles_invalid_type_gracefully() -> None:
    """Tool upsert_contact ignoriert unbekannte contact_type-Werte."""
    repo = _repo()
    model = _make_tool_model(
        "upsert_contact",
        {"name": "Unbekannt GmbH", "contact_type": "ungültig"},
    )
    agent.run_sync("...", model=model, deps=repo)

    contact = repo.get_contact_by_name("Unbekannt GmbH")
    assert contact is not None
    assert contact.type is None


def test_create_task_tool_writes_to_db() -> None:
    """Tool create_task legt Task in der DB an."""
    repo = _repo()
    model = _make_tool_model(
        "create_task",
        {"title": "Angebot Musterpark schreiben", "due": "2026-07-15"},
    )
    agent.run_sync("...", model=model, deps=repo)

    tasks = repo.query_open_items()
    assert len(tasks) == 1
    assert tasks[0].title == "Angebot Musterpark schreiben"
    assert tasks[0].status == TaskStatus.OFFEN


def test_create_task_tool_resolves_project() -> None:
    """create_task legt Projekt automatisch an, wenn es noch nicht existiert."""
    repo = _repo()
    model = _make_tool_model(
        "create_task",
        {"title": "Pflanzplan erstellen", "project_title": "Garten Schneider"},
    )
    agent.run_sync("...", model=model, deps=repo)

    tasks = repo.query_open_items()
    assert tasks[0].project_id is not None


def test_update_project_status_tool_updates_db() -> None:
    """Tool update_project_status aktualisiert den Projektstatus."""
    repo = _repo()
    repo.get_or_create_project("Stadtpark Revitalisierung")

    model = _make_tool_model(
        "update_project_status",
        {
            "project_title": "Stadtpark Revitalisierung",
            "status": "planung",
            "waiting_on": "kunde",
            "next_action": "Kostenvoranschlag vorlegen",
        },
    )
    agent.run_sync("...", model=model, deps=repo)

    projects = repo.query_waiting_on(WaitingOn.KUNDE)
    assert len(projects) == 1
    assert projects[0].next_action == "Kostenvoranschlag vorlegen"


def test_link_ort_tool_writes_to_db() -> None:
    """Tool link_ort legt Örtlichkeit in der DB an (Schritt 8.26)."""
    repo = _repo()
    model = _make_tool_model(
        "link_ort",
        {"name": "Flurstück 12", "adresse": "Musterweg 3", "flurnummer": "12/3"},
    )
    agent.run_sync("...", model=model, deps=repo)

    ort = repo.get_ort_by_name("Flurstück 12")
    assert ort is not None
    assert ort.adresse == "Musterweg 3"
    assert ort.flurnummer == "12/3"


def test_link_ort_tool_links_existing_contact() -> None:
    """link_ort verknüpft mit einem bereits bestehenden Kontakt."""
    repo = _repo()
    from kollege.models import ExtractedContact

    contact = repo.upsert_contact(ExtractedContact(name="Familie Müller"))
    assert contact.id is not None

    model = _make_tool_model(
        "link_ort",
        {"name": "Flurstück 12", "contact_name": "Familie Müller"},
    )
    agent.run_sync("...", model=model, deps=repo)

    updated_contact = repo.get_contact_by_id(contact.id)
    assert updated_contact is not None
    assert updated_contact.ort_id is not None


def test_link_ort_tool_resolves_project() -> None:
    """link_ort legt Projekt automatisch an, wenn es noch nicht existiert (wie create_task)."""
    repo = _repo()
    model = _make_tool_model(
        "link_ort",
        {"name": "Flurstück 12", "project_title": "Garten Schneider"},
    )
    agent.run_sync("...", model=model, deps=repo)

    project = repo.get_project_by_title("Garten Schneider")
    assert project is not None
    assert project.ort_id is not None


def test_query_open_items_tool_returns_string() -> None:
    """Tool query_open_items gibt lesbare Zusammenfassung zurück (kein Crash)."""
    repo = _repo()
    repo.create_task(Task(title="Test-Task", status=TaskStatus.OFFEN, source=TaskSource.MANUELL))

    model = _make_tool_model("query_open_items", {})
    agent.run_sync("...", model=model, deps=repo)


# --------------------------------------------------------------------------- #
# run_clarification_response — Prompt-Komposition (Schritt 8.13)               #
# --------------------------------------------------------------------------- #


def test_run_clarification_response_builds_prompt() -> None:
    """Der Klärungs-Lauf reicht Transkript, Rückfrage und Antwort an run_extraction."""
    from unittest.mock import patch

    from kollege.agent import run_clarification_response

    captured: dict[str, str] = {}

    def _capture(transcript: str, *args: object, **kwargs: object) -> ExtractionResult:
        captured["prompt"] = transcript
        return ExtractionResult()

    with patch("kollege.agent.run_extraction", side_effect=_capture):
        run_clarification_response(
            original_transcript="Kräutergarten Aibling als Dienstleister",
            clarification_question="Neuen Kontakt anlegen?",
            answer="Ja.",
            settings=Settings(),
        )

    prompt = captured["prompt"]
    assert "Kräutergarten Aibling als Dienstleister" in prompt
    assert "Neuen Kontakt anlegen?" in prompt
    assert "Ja." in prompt
    assert "RÜCKFRAGE-ANTWORT" in prompt


# --------------------------------------------------------------------------- #
# run_gap_check — Zweiter Durchgang / Lücken-Prüfung (Schritt 8.18)            #
# --------------------------------------------------------------------------- #


def test_run_gap_check_builds_prompt() -> None:
    """Der zweite Durchgang reicht Transkript + Erstergebnis an run_extraction.

    Fehlende Frist/Projektzuordnung müssen im Prompt explizit als Lücke sichtbar
    sein, damit das Modell sie füllen kann; Kontext (bekannte Namen, offene
    Aufgaben) wird durchgereicht.
    """
    from unittest.mock import patch

    from kollege.agent import run_gap_check
    from kollege.models import ExtractedTask

    captured: dict[str, object] = {}

    def _capture(transcript: str, *args: object, **kwargs: object) -> ExtractionResult:
        captured["prompt"] = transcript
        captured["kwargs"] = kwargs
        return ExtractionResult()

    first = ExtractionResult(tasks=[ExtractedTask(title="Angebot schicken")])
    with patch("kollege.agent.run_extraction", side_effect=_capture):
        run_gap_check(
            original_transcript="Ich muss Müller ein Angebot schicken.",
            first_result=first,
            settings=Settings(),
            known_names_context="[BEKANNTE NAMEN] Kontakte: Müller",
            open_tasks_context="[OFFENE AUFGABEN] #1 Zaun streichen",
        )

    prompt = captured["prompt"]
    assert isinstance(prompt, str)
    assert "LÜCKEN-PRÜFUNG" in prompt
    assert "Ich muss Müller ein Angebot schicken." in prompt
    assert "Angebot schicken" in prompt
    assert "OHNE Fälligkeitsdatum" in prompt  # Lücke explizit markiert
    assert "OHNE Projektzuordnung" in prompt
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs.get("known_names_context") == "[BEKANNTE NAMEN] Kontakte: Müller"
    assert kwargs.get("open_tasks_context") == "[OFFENE AUFGABEN] #1 Zaun streichen"


def test_run_gap_check_compacts_completed_and_edit_refs_when_open_tasks_present() -> None:
    """Schritt 8.23: Ist ``open_tasks_context`` gesetzt (Titel bereits dort sichtbar),
    referenziert der Gap-Check-Prompt Erledigungen/Änderungen nur noch per ID, statt
    den vollen Aufgaben-Titel ein zweites Mal aufzulisten (Kontext-Redundanz)."""
    from unittest.mock import patch

    from kollege.agent import run_gap_check
    from kollege.models import ExtractedTaskEdit

    captured: dict[str, object] = {}

    def _capture(transcript: str, *args: object, **kwargs: object) -> ExtractionResult:
        captured["prompt"] = transcript
        return ExtractionResult()

    first = ExtractionResult(
        completed=[ExtractedCompletion(task_id=3, task_title="Zaun bei Müller streichen")],
        edits=[
            ExtractedTaskEdit(
                task_id=4, task_title="Angebot an Gemeinde Aßling", new_due=date(2026, 7, 10)
            )
        ],
    )
    with patch("kollege.agent.run_extraction", side_effect=_capture):
        run_gap_check(
            original_transcript="Zaun ist fertig, Angebot bitte bis Freitag.",
            first_result=first,
            settings=Settings(),
            open_tasks_context="[OFFENE AUFGABEN] #3 Zaun bei Müller streichen",
        )

    prompt = captured["prompt"]
    assert isinstance(prompt, str)
    assert "#3" in prompt
    assert "#4" in prompt
    assert "Zaun bei Müller streichen" not in prompt  # Titel nicht doppelt
    assert "Angebot an Gemeinde Aßling" not in prompt
    assert "Frist → 2026-07-10" in prompt  # tatsächliche Änderung bleibt sichtbar


def test_run_gap_check_keeps_full_titles_without_open_tasks_context() -> None:
    """Ohne ``open_tasks_context`` bleibt der volle Titel erhalten (kein Informations-
    verlust, falls der Aufrufer die offenen Aufgaben nicht mitschickt)."""
    from unittest.mock import patch

    from kollege.agent import run_gap_check

    captured: dict[str, object] = {}

    def _capture(transcript: str, *args: object, **kwargs: object) -> ExtractionResult:
        captured["prompt"] = transcript
        return ExtractionResult()

    first = ExtractionResult(
        completed=[ExtractedCompletion(task_id=3, task_title="Zaun bei Müller streichen")]
    )
    with patch("kollege.agent.run_extraction", side_effect=_capture):
        run_gap_check(
            original_transcript="Zaun ist fertig.",
            first_result=first,
            settings=Settings(),
        )

    prompt = captured["prompt"]
    assert isinstance(prompt, str)
    assert "Zaun bei Müller streichen" in prompt


# --------------------------------------------------------------------------- #
# history — vollständige Interaktions-Historie (Schritt 8.14)                  #
# --------------------------------------------------------------------------- #


def test_run_revision_without_history_omits_history_block() -> None:
    """Ohne history-Argument enthält der Prompt keinen Historie-Block (Default)."""
    from unittest.mock import patch

    from kollege.agent import run_revision

    captured: dict[str, str] = {}

    def _capture(transcript: str, *args: object, **kwargs: object) -> ExtractionResult:
        captured["prompt"] = transcript
        return ExtractionResult()

    with patch("kollege.agent.run_extraction", side_effect=_capture):
        run_revision(
            original_transcript="Herr Schmidt ruft an.",
            current_result=ExtractionResult(),
            correction="Nicht Schmidt, sondern Schnitt.",
            settings=Settings(),
        )

    assert "Bisherige Turns" not in captured["prompt"]


def test_run_revision_includes_history_block() -> None:
    """Ein history-Argument wird als eigener Block vor dem Transkript eingefügt."""
    from unittest.mock import patch

    from kollege.agent import run_revision

    captured: dict[str, str] = {}

    def _capture(transcript: str, *args: object, **kwargs: object) -> ExtractionResult:
        captured["prompt"] = transcript
        return ExtractionResult()

    with patch("kollege.agent.run_extraction", side_effect=_capture):
        run_revision(
            original_transcript="Herr Schmidt ruft an.",
            current_result=ExtractionResult(),
            correction="Trag auch seine Nummer ein, wie eben gesagt.",
            settings=Settings(),
            history=[("Korrektur", "Seine Nummer ist übrigens 08031/12345.")],
        )

    prompt = captured["prompt"]
    assert "Bisherige Turns dieser Interaktion" in prompt
    assert "[Korrektur] Seine Nummer ist übrigens 08031/12345." in prompt
    # Historie-Block steht vor dem Ursprungstranskript
    assert prompt.index("Bisherige Turns") < prompt.index("Ursprüngliches Transkript")


def test_run_clarification_response_includes_history_block() -> None:
    """history wird auch im Rückfrage-Antwort-Prompt vorangestellt."""
    from unittest.mock import patch

    from kollege.agent import run_clarification_response

    captured: dict[str, str] = {}

    def _capture(transcript: str, *args: object, **kwargs: object) -> ExtractionResult:
        captured["prompt"] = transcript
        return ExtractionResult()

    with patch("kollege.agent.run_extraction", side_effect=_capture):
        run_clarification_response(
            original_transcript="Kräutergarten Aibling als Dienstleister",
            clarification_question="Welcher Nachname genau?",
            answer="Schmidt.",
            settings=Settings(),
            history=[("Rückfrage", "Neuen Kontakt anlegen?"), ("Antwort", "Ja.")],
        )

    prompt = captured["prompt"]
    assert "[Rückfrage] Neuen Kontakt anlegen?" in prompt
    assert "[Antwort] Ja." in prompt


def test_run_revision_uses_history_to_resolve_earlier_reference() -> None:
    """FunctionModel-Test (Schritt 8.14 DoD): Eine Korrektur, die auf einen Wert aus
    einem früheren Turn derselben Interaktion verweist ("wie eben gesagt"), landet
    im Ergebnis — weil dieser frühere Turn über ``history`` im Prompt steht.

    Ohne history (oder wenn die Telefonnummer nicht im Prompt vorkommt) liefert das
    FunctionModel bewusst keinen Telefon-Wert zurück, um zu zeigen, dass die
    History tatsächlich der entscheidende Kanal ist — nicht Zufall.
    """
    from unittest.mock import patch

    from kollege.agent import run_revision
    from kollege.models import ExtractedContact

    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        full = " ".join(
            str(part.content) for msg in messages for part in msg.parts if hasattr(part, "content")
        )
        phone = "08031/12345" if "08031/12345" in full else None
        result = ExtractionResult(contacts=[ExtractedContact(name="Herr Schmidt", phone=phone)])
        return ModelResponse(
            parts=[ToolCallPart(tool_name="final_result", args=result.model_dump_json())]
        )

    model = FunctionModel(fn)
    current = ExtractionResult(contacts=[ExtractedContact(name="Herr Schmidt")])

    with patch("kollege.agent.build_model", return_value=model):
        without_history = run_revision(
            original_transcript="Herr Schmidt vom Gartenbau ruft an.",
            current_result=current,
            correction="Trag zusätzlich seine Nummer ein, wie eben gesagt.",
            settings=Settings(),
        )
        with_history = run_revision(
            original_transcript="Herr Schmidt vom Gartenbau ruft an.",
            current_result=current,
            correction="Trag zusätzlich seine Nummer ein, wie eben gesagt.",
            settings=Settings(),
            history=[("Korrektur", "Seine Nummer ist übrigens 08031/12345.")],
        )

    assert without_history.contacts[0].phone is None
    assert with_history.contacts[0].phone == "08031/12345"


# --------------------------------------------------------------------------- #
# Revisions-Prompt zeigt Erledigungen + Änderungen (Schritt 8.20)              #
# --------------------------------------------------------------------------- #


def test_run_revision_prompt_includes_completed_and_edits() -> None:
    """Der Korrektur-Lauf muss ``completed`` und ``edits`` des bisherigen Vorschlags
    im Prompt zeigen — sonst verliert der frische One-Shot sie (Live-Bug 8.20).
    """
    from unittest.mock import patch

    from kollege.agent import run_revision
    from kollege.models import ExtractedCompletion, ExtractedTaskEdit

    captured: dict[str, str] = {}

    def _capture(transcript: str, *args: object, **kwargs: object) -> ExtractionResult:
        captured["prompt"] = transcript
        return ExtractionResult()

    current = ExtractionResult(
        completed=[
            ExtractedCompletion(task_id=7, task_title="Angebot Kindergarten absenden"),
            ExtractedCompletion(task_id=8, task_title="Sabine zurückrufen"),
        ],
        edits=[ExtractedTaskEdit(task_id=6, task_title="Plan Eibling", new_title="Plan Aibling")],
    )

    with patch("kollege.agent.run_extraction", side_effect=_capture):
        run_revision(
            original_transcript="Langes Update mit mehreren erledigten Aufgaben.",
            current_result=current,
            correction="Aufgabe #9 ist auch erledigt.",
            settings=Settings(),
        )

    prompt = captured["prompt"]
    # Beide bereits erkannten Erledigungen sind im Prompt sichtbar.
    assert "Erledigung: #7 Angebot Kindergarten absenden" in prompt
    assert "Erledigung: #8 Sabine zurückrufen" in prompt
    # Die Änderung inkl. Zieltitel ist sichtbar.
    assert "Aufgabe ändern: #6 Plan Eibling" in prompt
    assert "Titel → «Plan Aibling»" in prompt
    # Die Übernahme-Anweisung steht im Prompt.
    assert "unverändert" in prompt


def test_run_revision_prompt_includes_locations() -> None:
    """Örtlichkeiten des bisherigen Vorschlags müssen im Korrektur-Prompt sichtbar
    sein — sonst gilt dieselbe Verlust-Gefahr wie bei Erledigungen/Änderungen (8.20)."""
    from unittest.mock import patch

    from kollege.agent import run_revision
    from kollege.models import ExtractedOrt

    captured: dict[str, str] = {}

    def _capture(transcript: str, *args: object, **kwargs: object) -> ExtractionResult:
        captured["prompt"] = transcript
        return ExtractionResult()

    current = ExtractionResult(
        locations=[
            ExtractedOrt(
                name="Flurstück 12", adresse="Musterweg 3", flurnummer="12/3", project="Stadtpark"
            )
        ]
    )

    with patch("kollege.agent.run_extraction", side_effect=_capture):
        run_revision(
            original_transcript="Notiz zum Flurstück.",
            current_result=current,
            correction="Die Adresse ist Musterweg 5.",
            settings=Settings(),
        )

    prompt = captured["prompt"]
    assert "Örtlichkeit: Flurstück 12" in prompt
    assert "Musterweg 3" in prompt
    assert "Projekt: Stadtpark" in prompt


def test_run_revision_prompt_completed_survive_reflecting_model() -> None:
    """Verhaltens-Regression: Ein 'treues' FunctionModel, das nur die im Prompt
    sichtbaren Aufgaben-IDs zurückgibt, behält dank des Fixes (8.20) die zuvor
    erkannten Erledigungen und ergänzt die neu genannte.
    """
    import re
    from unittest.mock import patch

    from kollege.agent import run_revision
    from kollege.models import ExtractedCompletion

    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        full = " ".join(
            str(part.content) for msg in messages for part in msg.parts if hasattr(part, "content")
        )
        ids = sorted({int(n) for n in re.findall(r"#(\d+)", full)})
        result = ExtractionResult(
            completed=[ExtractedCompletion(task_id=i, task_title=f"Aufgabe {i}") for i in ids]
        )
        return ModelResponse(
            parts=[ToolCallPart(tool_name="final_result", args=result.model_dump_json())]
        )

    current = ExtractionResult(
        completed=[
            ExtractedCompletion(task_id=7, task_title="Angebot Kindergarten absenden"),
            ExtractedCompletion(task_id=8, task_title="Sabine zurückrufen"),
        ]
    )

    with patch("kollege.agent.build_model", return_value=FunctionModel(fn)):
        revised = run_revision(
            original_transcript="Langes Update mit mehreren erledigten Aufgaben.",
            current_result=current,
            correction="Du hast eine vergessen: Aufgabe #9 ist auch erledigt.",
            settings=Settings(),
        )

    assert {c.task_id for c in revised.completed} == {7, 8, 9}


# --------------------------------------------------------------------------- #
# LLM-Traces (Schritt 8.21)                                                    #
# --------------------------------------------------------------------------- #


class _RecordingTraceWriter:
    """Test-Double: sammelt geschriebene Ereignisse statt sie zu persistieren."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, object]]] = []

    def write(self, event: str, run_id: str, payload: dict[str, object]) -> None:
        self.events.append((event, run_id, payload))


def test_run_extraction_without_trace_is_a_noop() -> None:
    """Ohne ``trace``-Argument entsteht kein Fehler (Default: NoopTraceWriter)."""
    from unittest.mock import patch

    from kollege.agent import run_extraction

    repo = _repo()
    with patch("kollege.agent.build_model", return_value=TestModel(call_tools=[])):
        result = run_extraction("Ein Test-Transkript.", repo, Settings())
    assert isinstance(result, ExtractionResult)


def test_run_extraction_traces_primary_path_success() -> None:
    """Ein erfolgreicher Primär-Lauf schreibt genau ``llm_run_start``/``llm_run_result``
    mit Kind, Pfad, Messages (Tool-Calls/Antwort) und Token-Usage.
    """
    from unittest.mock import patch

    from kollege.agent import run_extraction
    from kollege.models import ExtractedTask

    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        result = ExtractionResult(tasks=[ExtractedTask(title="Testaufgabe")])
        return ModelResponse(
            parts=[ToolCallPart(tool_name="final_result", args=result.model_dump_json())]
        )

    writer = _RecordingTraceWriter()
    repo = _repo()
    with patch("kollege.agent.build_model", return_value=FunctionModel(fn)):
        run_extraction(
            "Ein Test-Transkript.",
            repo,
            Settings(),
            kind="gap_check",
            trace=writer,
            run_id="rid-1",
        )

    events = {e: (rid, payload) for e, rid, payload in writer.events}
    assert set(events) == {"llm_run_start", "llm_run_result"}
    assert events["llm_run_start"][0] == "rid-1"
    assert events["llm_run_start"][1]["kind"] == "gap_check"
    assert events["llm_run_start"][1]["prompt"] == "Ein Test-Transkript."
    result_payload = events["llm_run_result"][1]
    assert result_payload["path"] == "primär"
    assert result_payload["kind"] == "gap_check"
    assert len(result_payload["messages"]) >= 2  # type: ignore[arg-type]
    assert "requests" in result_payload["usage"]  # type: ignore[operator]
    assert result_payload["output"]["tasks"][0]["title"] == "Testaufgabe"  # type: ignore[index]


def test_run_extraction_trace_does_not_duplicate_prompt_in_messages() -> None:
    """Schritt 8.23: Der volle Prompt-Text steht bereits in ``llm_run_start.prompt``
    — die ``user-prompt``-Part in ``llm_run_result.messages`` darf ihn nicht noch
    einmal Byte-für-Byte enthalten (Trace-Datei wuchs sonst mit doppeltem Text)."""
    from unittest.mock import patch

    from kollege.agent import run_extraction
    from kollege.models import ExtractedTask

    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        result = ExtractionResult(tasks=[ExtractedTask(title="Testaufgabe")])
        return ModelResponse(
            parts=[ToolCallPart(tool_name="final_result", args=result.model_dump_json())]
        )

    writer = _RecordingTraceWriter()
    repo = _repo()
    prompt_text = "Ein längeres Test-Transkript, das im Trace nicht doppelt stehen soll."
    with patch("kollege.agent.build_model", return_value=FunctionModel(fn)):
        run_extraction(prompt_text, repo, Settings(), trace=writer, run_id="rid-dedup")

    events = {e: payload for e, _, payload in writer.events}
    assert events["llm_run_start"]["prompt"] == prompt_text

    messages = events["llm_run_result"]["messages"]
    assert isinstance(messages, list)
    user_prompt_parts = [
        part for msg in messages for part in msg["parts"] if part["part_kind"] == "user-prompt"
    ]
    assert user_prompt_parts  # die Part existiert weiterhin (Struktur bleibt sichtbar) …
    assert all(part["content"] != prompt_text for part in user_prompt_parts)  # … aber ohne Duplikat


def test_run_extraction_traces_primary_error_then_fallback_result() -> None:
    """Scheitert der Primär-Pfad (kein ``final_result``-Tool), landet ein
    ``llm_run_error`` fürs Primär im Trace — inkl. der gescheiterten Messages —
    gefolgt vom ``llm_run_result`` des Fallback-Pfads.
    """
    from unittest.mock import patch

    from pydantic_ai.messages import TextPart

    from kollege.agent import run_extraction

    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(content="Ich bin unsicher, was gemeint ist.")])

    writer = _RecordingTraceWriter()
    repo = _repo()
    with patch("kollege.agent.build_model", return_value=FunctionModel(fn)):
        result = run_extraction(
            "Ein unklares Transkript.",
            repo,
            Settings(),
            trace=writer,
            run_id="rid-2",
        )

    event_names = [e for e, _, _ in writer.events]
    assert event_names == ["llm_run_start", "llm_run_error", "llm_run_result"]
    error_payload = writer.events[1][2]
    assert error_payload["path"] == "primär"
    assert error_payload["exception_type"]
    assert error_payload["messages"]  # gescheiterte Messages sind nicht leer
    result_payload = writer.events[2][2]
    assert result_payload["path"] == "fallback"
    assert result.clarification == "Ich bin unsicher, was gemeint ist."


def test_run_extraction_generates_run_id_when_omitted() -> None:
    """Ohne ``run_id``-Argument wird pro Aufruf eine frische ID erzeugt."""
    from unittest.mock import patch

    from kollege.agent import run_extraction

    writer = _RecordingTraceWriter()
    repo = _repo()
    with patch("kollege.agent.build_model", return_value=TestModel(call_tools=[])):
        run_extraction("Text 1", repo, Settings(), trace=writer)
        run_extraction("Text 2", repo, Settings(), trace=writer)

    run_ids = {rid for _, rid, _ in writer.events}
    assert len(run_ids) == 2


def test_run_gap_check_passes_trace_and_run_id_through() -> None:
    """``run_gap_check`` reicht ``trace``/``run_id`` an ``run_extraction`` durch
    und setzt ``kind='gap_check'``."""
    from unittest.mock import patch

    from kollege.agent import run_gap_check

    captured: dict[str, object] = {}

    def _capture(transcript: str, *args: object, **kwargs: object) -> ExtractionResult:
        captured.update(kwargs)
        return ExtractionResult()

    writer = _RecordingTraceWriter()
    with patch("kollege.agent.run_extraction", side_effect=_capture):
        run_gap_check(
            original_transcript="Text",
            first_result=ExtractionResult(),
            settings=Settings(),
            trace=writer,
            run_id="rid-3",
        )

    assert captured["kind"] == "gap_check"
    assert captured["trace"] is writer
    assert captured["run_id"] == "rid-3"
