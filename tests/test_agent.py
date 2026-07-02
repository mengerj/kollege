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

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from kollege.agent import agent, build_model
from kollege.config import LLMProvider, Settings
from kollege.db import Repository
from kollege.models import (
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
