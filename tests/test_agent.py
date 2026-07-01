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
