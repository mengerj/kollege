"""Tests für Schritt 8.9 — Robuster Dauerbetrieb.

Abgedeckt:
- pre_warm_model(): Ollama-Vorladen bei Dienststart.
- Retry-Logik in Orchestrator._extract(): transiente Fehler werden wiederholt.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kollege.agent import pre_warm_model
from kollege.channels import IncomingMessage, MemoryChannel
from kollege.config import LLMProvider, Settings
from kollege.db import Repository
from kollege.models import ExtractedTask, ExtractionResult
from kollege.orchestrator import Orchestrator

SENDER = "+491234567890"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _repo() -> Repository:
    return Repository(sqlite3.connect(":memory:", check_same_thread=False))


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(db_path=str(tmp_path / "test.db"), markdown_dir=str(tmp_path / "logs"))


@pytest.fixture
def log_dir(tmp_path: Path) -> Path:
    d = tmp_path / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def channel() -> MemoryChannel:
    return MemoryChannel()


@pytest.fixture
def orc(channel: MemoryChannel, settings: Settings, log_dir: Path) -> Orchestrator:
    return Orchestrator(
        channel=channel,
        repo=_repo(),
        transcriber=None,
        settings=settings,
        log_dir=log_dir,
        retry_delay=0.0,  # Tests ohne Wartezeit
    )


def _success_result() -> ExtractionResult:
    return ExtractionResult(
        contacts=[],
        tasks=[ExtractedTask(title="Test-Aufgabe")],
        project_updates=[],
    )


# ---------------------------------------------------------------------------
# pre_warm_model
# ---------------------------------------------------------------------------


def test_pre_warm_calls_ollama_api(settings: Settings) -> None:
    """pre_warm_model sendet POST an /api/generate mit dem konfigurierten Modell."""
    settings = Settings(
        llm_provider=LLMProvider.OLLAMA,
        ollama_base_url="http://localhost:11434/v1",
        llm_model="test-model",
    )
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.post", return_value=mock_resp) as mock_post:
        pre_warm_model(settings)

    mock_post.assert_called_once_with(
        "http://localhost:11434/api/generate",
        json={"model": "test-model", "prompt": "", "stream": False},
        timeout=120.0,
    )
    mock_resp.raise_for_status.assert_called_once()


def test_pre_warm_strips_v1_suffix() -> None:
    """pre_warm_model entfernt /v1 aus der Basis-URL für die native Ollama-API."""
    settings = Settings(
        llm_provider=LLMProvider.OLLAMA,
        ollama_base_url="http://custom-host:11434/v1",
        llm_model="my-model",
    )
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.post", return_value=mock_resp) as mock_post:
        pre_warm_model(settings)

    called_url: str = mock_post.call_args[0][0]
    assert called_url == "http://custom-host:11434/api/generate"


def test_pre_warm_skips_non_ollama() -> None:
    """pre_warm_model tut nichts für Cloud-Provider (kein HTTP-Aufruf)."""
    settings = Settings(llm_provider=LLMProvider.ANTHROPIC)

    with patch("httpx.post") as mock_post:
        pre_warm_model(settings)

    mock_post.assert_not_called()


def test_pre_warm_handles_connection_error_gracefully() -> None:
    """pre_warm_model scheitert ohne Exception, wenn Ollama nicht erreichbar."""
    settings = Settings(llm_provider=LLMProvider.OLLAMA)

    with patch("httpx.post", side_effect=OSError("Connection refused")):
        pre_warm_model(settings)  # darf nicht werfen


def test_pre_warm_handles_http_error_gracefully() -> None:
    """pre_warm_model scheitert ohne Exception, wenn Ollama einen Fehler zurückgibt."""
    settings = Settings(llm_provider=LLMProvider.OLLAMA)
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = Exception("404 Not Found")

    with patch("httpx.post", return_value=mock_resp):
        pre_warm_model(settings)  # darf nicht werfen


# ---------------------------------------------------------------------------
# Retry-Logik in _extract() / handle_message()
# ---------------------------------------------------------------------------


def test_extract_retries_on_transient_failure_and_succeeds(
    orc: Orchestrator, channel: MemoryChannel
) -> None:
    """Nach zwei Fehlern liefert der dritte Versuch ein Ergebnis."""
    attempt_counter = {"n": 0}

    def flaky_extraction(
        transcript: str, repo: object, settings: object, **_: object
    ) -> ExtractionResult:
        attempt_counter["n"] += 1
        if attempt_counter["n"] < 3:
            raise RuntimeError("Ollama temporär nicht erreichbar")
        return _success_result()

    with patch("kollege.orchestrator.run_extraction", side_effect=flaky_extraction):
        orc.handle_message(IncomingMessage(sender=SENDER, text="Notiz"))

    assert attempt_counter["n"] == 3
    # Ack-Nachricht + Vorschlags-Nachricht
    texts = [text for _, text in channel.sent]
    assert any("Notiz erhalten" in t for t in texts)
    assert any("Aufgabe" in t for t in texts)


def test_extract_raises_after_all_retries_exhausted(
    orc: Orchestrator, channel: MemoryChannel
) -> None:
    """Nach allen Fehlversuchen wird die Exception weitergereicht."""
    with (
        patch("kollege.orchestrator.run_extraction", side_effect=RuntimeError("Dauerfehler")),
        pytest.raises(RuntimeError, match="Dauerfehler"),
    ):
        # handle_message wirft nicht selbst (run_once fängt es ab),
        # aber direkt aufgerufen propagiert der Fehler.
        orc.handle_message(IncomingMessage(sender=SENDER, text="Notiz"))


def test_extract_does_not_retry_if_first_attempt_succeeds(
    orc: Orchestrator, channel: MemoryChannel
) -> None:
    """Kein Retry wenn der erste Versuch erfolgreich ist."""
    attempt_counter = {"n": 0}

    def counting_extraction(
        transcript: str, repo: object, settings: object, **_: object
    ) -> ExtractionResult:
        attempt_counter["n"] += 1
        return _success_result()

    with patch("kollege.orchestrator.run_extraction", side_effect=counting_extraction):
        orc.handle_message(IncomingMessage(sender=SENDER, text="Notiz"))

    assert attempt_counter["n"] == 1


def test_run_once_catches_exhausted_retries_and_sends_error(
    orc: Orchestrator, channel: MemoryChannel
) -> None:
    """run_once() fängt den Fehler nach erschöpften Retries und sendet Fehlermeldung."""
    channel.inbox.append(IncomingMessage(sender=SENDER, text="Notiz"))

    with patch("kollege.orchestrator.run_extraction", side_effect=RuntimeError("Ollama weg")):
        orc.run_once()

    texts = [text for _, text in channel.sent]
    assert any("⚠" in t for t in texts)
