"""Tests für Schritt 8.27 — Orchestrator.check_reminders()/run_forever-Verdrahtung.

Reine Regel-/Fällig-Logik ist bereits in ``test_reminders.py`` abgedeckt; hier
geht es um die Verdrahtung: Versand über den Channel, Neustart-Sicherheit über
das Repository, und dass eine Erinnerung offene Pending-Zustände nie stört.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from kollege.channels import MemoryChannel
from kollege.config import Settings
from kollege.db import Repository
from kollege.models import ExtractedContact, ExtractedTask, ExtractionResult, Task, TaskSource
from kollege.orchestrator import Orchestrator, PendingProposal, format_reminder_list

SENDER = "+491234567890"
SIGNAL_NUMBER = "+49170000000"

_RULES_PING_ONLY = """
[[erinnerung]]
typ = "ping"
wochentage = ["Mo", "Fr"]
uhrzeit = "08:00"
"""

_RULES_LISTE_ONLY = """
[[erinnerung]]
typ = "liste"
wochentage = ["Mo", "Fr"]
uhrzeit = "08:00"
"""


def _repo() -> Repository:
    return Repository(sqlite3.connect(":memory:", check_same_thread=False))


@pytest.fixture
def repo() -> Repository:
    return _repo()


@pytest.fixture
def log_dir(tmp_path: Path) -> Path:
    d = tmp_path / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def channel() -> MemoryChannel:
    return MemoryChannel()


def _settings(tmp_path: Path, config_text: str | None) -> Settings:
    config_path = tmp_path / "reminders.toml"
    if config_text is not None:
        config_path.write_text(config_text, encoding="utf-8")
    return Settings(
        db_path=str(tmp_path / "test.db"),
        markdown_dir=str(tmp_path / "logs"),
        signal_number=SIGNAL_NUMBER,
        reminders_config_path=str(config_path),
    )


def _orc(
    channel: MemoryChannel, repo: Repository, settings: Settings, log_dir: Path
) -> Orchestrator:
    return Orchestrator(
        channel=channel, repo=repo, transcriber=None, settings=settings, log_dir=log_dir
    )


# 2026-07-13 ist ein Montag.
_MONDAY_0800 = datetime(2026, 7, 13, 8, 0)


def test_check_reminders_without_config_file_sends_nothing(
    channel: MemoryChannel, repo: Repository, log_dir: Path, tmp_path: Path
) -> None:
    settings = _settings(tmp_path, config_text=None)
    orc = _orc(channel, repo, settings, log_dir)

    orc.check_reminders(now=_MONDAY_0800)

    assert channel.sent == []


def test_check_reminders_skips_when_signal_number_unset(
    channel: MemoryChannel, repo: Repository, log_dir: Path, tmp_path: Path
) -> None:
    settings = _settings(tmp_path, config_text=_RULES_PING_ONLY)
    settings = settings.model_copy(update={"signal_number": ""})
    orc = _orc(channel, repo, settings, log_dir)

    orc.check_reminders(now=_MONDAY_0800)

    assert channel.sent == []


def test_check_reminders_sends_ping_text_when_due(
    channel: MemoryChannel, repo: Repository, log_dir: Path, tmp_path: Path
) -> None:
    settings = _settings(tmp_path, config_text=_RULES_PING_ONLY)
    orc = _orc(channel, repo, settings, log_dir)

    orc.check_reminders(now=_MONDAY_0800)

    assert len(channel.sent) == 1
    recipient, text = channel.sent[0]
    assert recipient == SIGNAL_NUMBER
    assert "Neues" in text


def test_check_reminders_sends_task_list_when_due(
    channel: MemoryChannel, repo: Repository, log_dir: Path, tmp_path: Path
) -> None:
    settings = _settings(tmp_path, config_text=_RULES_LISTE_ONLY)
    orc = _orc(channel, repo, settings, log_dir)
    repo.create_task(Task(title="Angebot schreiben", source=TaskSource.MANUELL))

    orc.check_reminders(now=_MONDAY_0800)

    assert len(channel.sent) == 1
    recipient, text = channel.sent[0]
    assert recipient == SIGNAL_NUMBER
    assert "Angebot schreiben" in text


def test_check_reminders_not_due_yet_sends_nothing(
    channel: MemoryChannel, repo: Repository, log_dir: Path, tmp_path: Path
) -> None:
    """Dasselbe geplante Vorkommen wird nicht zweimal am selben Poll-Tag gesendet."""
    settings = _settings(tmp_path, config_text=_RULES_PING_ONLY)
    orc = _orc(channel, repo, settings, log_dir)

    orc.check_reminders(now=_MONDAY_0800)
    assert len(channel.sent) == 1  # erste Instanz wurde gesendet

    orc.check_reminders(now=_MONDAY_0800.replace(hour=8, minute=30))
    assert len(channel.sent) == 1  # keine zweite Sendung fürs selbe Vorkommen


def test_check_reminders_persists_last_sent_for_restart_safety(
    channel: MemoryChannel, repo: Repository, log_dir: Path, tmp_path: Path
) -> None:
    settings = _settings(tmp_path, config_text=_RULES_PING_ONLY)
    orc = _orc(channel, repo, settings, log_dir)
    orc.check_reminders(now=_MONDAY_0800)
    assert len(channel.sent) == 1

    # Neuer Orchestrator (simuliert Neustart) mit demselben Repository —
    # keine Doppel-Sendung, weil last_sent im Repository steht.
    channel2 = MemoryChannel()
    orc2 = _orc(channel2, repo, settings, log_dir)
    orc2.check_reminders(now=_MONDAY_0800.replace(minute=5))
    assert channel2.sent == []


def test_check_reminders_fires_again_at_next_scheduled_occurrence(
    channel: MemoryChannel, repo: Repository, log_dir: Path, tmp_path: Path
) -> None:
    settings = _settings(tmp_path, config_text=_RULES_PING_ONLY)
    orc = _orc(channel, repo, settings, log_dir)
    orc.check_reminders(now=_MONDAY_0800)
    assert len(channel.sent) == 1

    friday_0800 = datetime(2026, 7, 17, 8, 0)
    orc.check_reminders(now=friday_0800)
    assert len(channel.sent) == 2


def test_check_reminders_does_not_disturb_pending_proposal(
    channel: MemoryChannel, repo: Repository, log_dir: Path, tmp_path: Path
) -> None:
    """Ein offener Vorschlag desselben (oder eines anderen) Absenders bleibt unangetastet."""
    settings = _settings(tmp_path, config_text=_RULES_PING_ONLY)
    orc = _orc(channel, repo, settings, log_dir)
    pending_result = ExtractionResult(
        contacts=[], tasks=[ExtractedTask(title="Testaufgabe")], project_updates=[]
    )
    orc._pending[SENDER] = PendingProposal(
        sender=SENDER, transcript="Testaufgabe morgen erledigen", result=pending_result
    )

    orc.check_reminders(now=_MONDAY_0800)

    assert SENDER in orc._pending  # unverändert, keine Erinnerung hat es angefasst
    assert orc._pending[SENDER].result == pending_result
    # Die Erinnerung selbst wurde trotzdem an die Nutzerin (signal_number) gesendet.
    assert len(channel.sent) == 1


def test_run_forever_calls_run_once_and_check_reminders_each_cycle(
    channel: MemoryChannel, repo: Repository, log_dir: Path, tmp_path: Path
) -> None:
    settings = _settings(tmp_path, config_text=None)
    orc = _orc(channel, repo, settings, log_dir)
    calls: dict[str, int] = {"run_once": 0, "check_reminders": 0}

    class _StopLoop(Exception):
        pass

    def fake_sleep(_seconds: float) -> None:
        raise _StopLoop

    with (
        patch.object(
            orc,
            "run_once",
            side_effect=lambda: calls.__setitem__("run_once", calls["run_once"] + 1),
        ),
        patch.object(
            orc,
            "check_reminders",
            side_effect=lambda: calls.__setitem__("check_reminders", calls["check_reminders"] + 1),
        ),
        patch("kollege.orchestrator.time.sleep", side_effect=fake_sleep),
        pytest.raises(_StopLoop),
    ):
        orc.run_forever(poll_interval=0.0)

    assert calls == {"run_once": 1, "check_reminders": 1}


# ---------------------------------------------------------------------------
# format_reminder_list — Projekt-/Kontakt-/Ort-Bezug
# ---------------------------------------------------------------------------


def test_format_reminder_list_empty() -> None:
    repo = _repo()
    assert format_reminder_list([], repo) == "📋 Keine offenen Aufgaben."


def test_format_reminder_list_includes_project_and_ort(repo: Repository) -> None:
    ort = repo.get_or_create_ort("Flurstück 12")
    project = repo.get_or_create_project("Garten Schneider")
    assert project.id is not None
    assert ort.id is not None
    repo.link_project_ort(project.id, ort.id)
    task = repo.create_task(
        Task(title="Angebot senden", project_id=project.id, due=None, source=TaskSource.MANUELL)
    )

    text = format_reminder_list([task], repo)

    assert "Angebot senden" in text
    assert "Projekt: Garten Schneider" in text
    assert "Ort: Flurstück 12" in text
    assert "(kein Datum)" in text


def test_format_reminder_list_includes_contact_and_ort_without_project(repo: Repository) -> None:
    ort = repo.get_or_create_ort("Flurstück 7")
    contact = repo.upsert_contact(ExtractedContact(name="Herr Schneider"))
    assert contact.id is not None
    assert ort.id is not None
    repo.link_contact_ort(contact.id, ort.id)
    task = repo.create_task(Task(title="Anrufen", contact_id=contact.id, source=TaskSource.MANUELL))

    text = format_reminder_list([task], repo)

    assert "Anrufen" in text
    assert "Kontakt: Herr Schneider" in text
    assert "Ort: Flurstück 7" in text
