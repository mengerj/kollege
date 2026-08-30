"""Tests für die Bekannte-Namen-Abgleich-Logik (Schritt 8.7).

Strategie:
- ``filter_known_names`` / ``build_known_names_context`` / ``get_known_names_context``
  ohne LLM testbar.
- ``run_extraction`` mit bekanntem Kontext über ``FunctionModel``, das die
  tatsächlich gelieferte Nutzernachricht prüft (kein echter LLM).
- Orchestrator-Integration über ``unittest.mock.patch`` auf ``run_extraction``.

Kein echter LLM-Aufruf, kein Netzwerk: CI-sicher.
"""

from __future__ import annotations

import datetime
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from kollege.agent import (
    build_known_names_context,
    filter_known_names,
    get_known_names_context,
    run_extraction,
)
from kollege.channels import IncomingMessage, MemoryChannel
from kollege.config import Settings
from kollege.db import Repository
from kollege.models import (
    Contact,
    ExtractedContact,
    ExtractionResult,
    Ort,
    Project,
)
from kollege.orchestrator import Orchestrator

# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------


def _repo() -> Repository:
    return Repository(sqlite3.connect(":memory:", check_same_thread=False))


def _contact(name: str, updated_at: datetime.datetime | None = None) -> Contact:
    dt = updated_at or datetime.datetime.now(tz=datetime.UTC)
    return Contact(name=name, created_at=dt, updated_at=dt)


def _project(title: str, updated_at: datetime.datetime | None = None) -> Project:
    dt = updated_at or datetime.datetime.now(tz=datetime.UTC)
    return Project(title=title, created_at=dt, updated_at=dt)


def _ort(name: str, updated_at: datetime.datetime | None = None) -> Ort:
    dt = updated_at or datetime.datetime.now(tz=datetime.UTC)
    return Ort(name=name, created_at=dt, updated_at=dt)


# ---------------------------------------------------------------------------
# filter_known_names
# ---------------------------------------------------------------------------


def test_filter_known_names_empty() -> None:
    names, projects, orte = filter_known_names([], [])
    assert names == []
    assert projects == []
    assert orte == []


def test_filter_known_names_below_limit() -> None:
    contacts = [_contact("Frau Schmidt"), _contact("Familie Wagner")]
    projects = [_project("Stadtpark"), _project("Bebauungsplan")]
    orte = [_ort("Flurstück 12")]
    c_names, p_names, o_names = filter_known_names(contacts, projects, orte, max_names=80)
    assert set(c_names) == {"Frau Schmidt", "Familie Wagner"}
    assert set(p_names) == {"Stadtpark", "Bebauungsplan"}
    assert set(o_names) == {"Flurstück 12"}


def test_filter_known_names_respects_max_limit() -> None:
    # Erzeuge mehr Namen als das Limit erlaubt.
    contacts = [_contact(f"Kontakt {i}") for i in range(60)]
    projects = [_project(f"Projekt {i}") for i in range(60)]
    orte = [_ort(f"Ort {i}") for i in range(60)]
    c_names, p_names, o_names = filter_known_names(contacts, projects, orte, max_names=9)
    assert len(c_names) <= 3
    assert len(p_names) <= 3
    assert len(o_names) <= 3


def test_filter_known_names_sorts_by_updated_at_descending() -> None:
    old = datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)
    new = datetime.datetime(2026, 6, 1, tzinfo=datetime.UTC)
    newer = datetime.datetime(2026, 6, 15, tzinfo=datetime.UTC)

    contacts = [
        _contact("Alt", updated_at=old),
        _contact("Neu", updated_at=new),
        _contact("Neuer", updated_at=newer),
    ]
    c_names, _, _ = filter_known_names(contacts, [], max_names=6)
    assert c_names[0] == "Neuer"
    assert c_names[1] == "Neu"


def test_filter_known_names_without_orte_returns_empty_third_list() -> None:
    """``orte`` ist optional (Rückwärtskompatibilität für Aufrufer ohne Orte)."""
    c_names, p_names, o_names = filter_known_names(
        [_contact("Frau Schmidt")], [_project("Stadtpark")]
    )
    assert c_names == ["Frau Schmidt"]
    assert p_names == ["Stadtpark"]
    assert o_names == []


# ---------------------------------------------------------------------------
# build_known_names_context
# ---------------------------------------------------------------------------


def test_build_known_names_context_empty_lists() -> None:
    ctx = build_known_names_context([], [])
    assert ctx == ""


def test_build_known_names_context_contacts_only() -> None:
    ctx = build_known_names_context(["Frau Schmidt", "Familie Wagner"], [])
    assert "Frau Schmidt" in ctx
    assert "Familie Wagner" in ctx
    assert "Kontakte" in ctx


def test_build_known_names_context_projects_only() -> None:
    ctx = build_known_names_context([], ["Stadtpark", "Bebauungsplan"])
    assert "Stadtpark" in ctx
    assert "Projekte" in ctx


def test_build_known_names_context_both() -> None:
    ctx = build_known_names_context(["Frau Schmidt"], ["Stadtpark"])
    assert "Frau Schmidt" in ctx
    assert "Stadtpark" in ctx
    assert "Kontakte" in ctx
    assert "Projekte" in ctx


def test_build_known_names_context_orte_only() -> None:
    ctx = build_known_names_context([], [], ["Flurstück 12"])
    assert "Flurstück 12" in ctx
    assert "Orte" in ctx


def test_build_known_names_context_all_three() -> None:
    ctx = build_known_names_context(["Frau Schmidt"], ["Stadtpark"], ["Flurstück 12"])
    assert "Frau Schmidt" in ctx
    assert "Stadtpark" in ctx
    assert "Flurstück 12" in ctx
    assert "Orte" in ctx


def test_build_known_names_context_contains_normalisation_hint() -> None:
    ctx = build_known_names_context(["Frau Schmidt"], [])
    assert "Normali" in ctx or "normali" in ctx or "gleich" in ctx or "Gleich" in ctx


# ---------------------------------------------------------------------------
# get_known_names_context
# ---------------------------------------------------------------------------


def test_get_known_names_context_empty_repo() -> None:
    repo = _repo()
    ctx = get_known_names_context(repo)
    assert ctx == ""


def test_get_known_names_context_with_contacts_and_projects() -> None:
    from kollege.models import ExtractedContact

    repo = _repo()

    repo.upsert_contact(ExtractedContact(name="Frau Schmidt"))
    repo.get_or_create_project("Stadtpark Revitalisierung")

    ctx = get_known_names_context(repo)
    assert "Frau Schmidt" in ctx
    assert "Stadtpark Revitalisierung" in ctx


def test_get_known_names_context_with_orte() -> None:
    repo = _repo()
    repo.get_or_create_ort("Flurstück 12")

    ctx = get_known_names_context(repo)
    assert "Flurstück 12" in ctx
    assert "Orte" in ctx


# ---------------------------------------------------------------------------
# run_extraction mit known_names_context
# ---------------------------------------------------------------------------


def _capture_model(captured: list[str]) -> FunctionModel:
    """FunctionModel, das den User-Prompt in ``captured`` speichert."""
    result_json = ExtractionResult().model_dump_json()

    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        for msg in messages:
            for part in msg.parts:
                if hasattr(part, "content"):
                    captured.append(str(part.content))
        return ModelResponse(parts=[ToolCallPart(tool_name="final_result", args=result_json)])

    return FunctionModel(fn)


def test_run_extraction_without_known_names_passes_transcript() -> None:
    captured: list[str] = []
    repo = _repo()
    settings = Settings()
    model = _capture_model(captured)

    with patch("kollege.agent.build_model", return_value=model):
        run_extraction("Testnachricht", repo, settings)

    full = " ".join(captured)
    assert "Testnachricht" in full


def test_run_extraction_with_known_names_injects_context() -> None:
    captured: list[str] = []
    repo = _repo()
    settings = Settings()
    model = _capture_model(captured)
    known_names = build_known_names_context(["Frau Schmidt"], ["Stadtpark"])

    with patch("kollege.agent.build_model", return_value=model):
        run_extraction("Herr Schnitt ruft an.", repo, settings, known_names_context=known_names)

    full = " ".join(captured)
    assert "Frau Schmidt" in full
    assert "Herr Schnitt" in full


def test_run_extraction_empty_known_names_context_no_injection() -> None:
    """Leerer Kontext → Transkript wird unverändert übergeben (kein Wrapper)."""
    captured: list[str] = []
    repo = _repo()
    settings = Settings()
    model = _capture_model(captured)

    with patch("kollege.agent.build_model", return_value=model):
        run_extraction("Reine Notiz", repo, settings, known_names_context="")

    full = " ".join(captured)
    assert "Reine Notiz" in full
    # Kein BEKANNTE-NAMEN-Block, weil Kontext leer war
    assert "BEKANNTE NAMEN" not in full


# ---------------------------------------------------------------------------
# Orchestrator ruft get_known_names_context auf
# ---------------------------------------------------------------------------

SENDER = "+491234567890"


@pytest.fixture
def log_dir(tmp_path: Path) -> Path:
    return tmp_path / "logs"


@pytest.fixture
def orc_with_known_contact(log_dir: Path) -> tuple[Orchestrator, MemoryChannel, Repository]:
    repo = _repo()
    from kollege.models import ExtractedContact

    repo.upsert_contact(ExtractedContact(name="Frau Schmidt"))
    channel = MemoryChannel()
    settings = Settings()
    orc = Orchestrator(
        channel=channel,
        repo=repo,
        transcriber=None,
        settings=settings,
        log_dir=log_dir,
    )
    return orc, channel, repo


def test_orchestrator_passes_known_names_to_run_extraction(
    orc_with_known_contact: tuple[Orchestrator, MemoryChannel, Repository],
    log_dir: Path,
) -> None:
    """Orchestrator gibt bekannte Namen aus dem echten Repo an run_extraction."""
    orc, _channel, _repo_unused = orc_with_known_contact

    captured_kwargs: list[dict[str, str | None]] = []

    def _fake_extraction(
        transcript: str,
        repo_: Repository,
        settings: Settings,
        known_names_context: str | None = None,
        **_: object,
    ) -> ExtractionResult:
        captured_kwargs.append({"known_names_context": known_names_context})
        return ExtractionResult(
            contacts=[ExtractedContact(name="Frau Schmidt")],
        )

    msg = IncomingMessage(sender=SENDER, text="Ruf Frau Schmidt an.")

    with patch("kollege.orchestrator.run_extraction", side_effect=_fake_extraction):
        orc.handle_message(msg)

    assert len(captured_kwargs) >= 1
    ctx = captured_kwargs[0]["known_names_context"]
    assert ctx is not None and ctx != ""
    assert "Frau Schmidt" in ctx


def test_orchestrator_known_names_empty_for_new_repo(log_dir: Path) -> None:
    """Leeres Repo → kein Namens-Kontext (leerer String)."""
    repo = _repo()
    channel = MemoryChannel()
    settings = Settings()
    orc = Orchestrator(
        channel=channel,
        repo=repo,
        transcriber=None,
        settings=settings,
        log_dir=log_dir,
    )

    captured_kwargs: list[dict[str, str | None]] = []

    def _fake_extraction(
        transcript: str,
        repo_: Repository,
        settings: Settings,
        known_names_context: str | None = None,
        **_: object,
    ) -> ExtractionResult:
        captured_kwargs.append({"known_names_context": known_names_context})
        return ExtractionResult()

    msg = IncomingMessage(sender=SENDER, text="Neue Notiz.")

    with patch("kollege.orchestrator.run_extraction", side_effect=_fake_extraction):
        orc.handle_message(msg)

    assert len(captured_kwargs) >= 1
    ctx = captured_kwargs[0]["known_names_context"]
    assert ctx == "" or ctx is None
