"""Tests für den Orchestrator (Schritt 7: Bestätigungs-Loop).

Strategie:
- ``MemoryChannel`` + In-Memory-Repo + ``StubTranscriber`` — kein Netz, kein LLM.
- ``run_extraction`` wird via ``unittest.mock.patch`` gemockt — CI-sicher.
- Geprüft: Vorschlag, Bestätigung (ja / 👍 / Zahlenauswahl), Ablehnung (nein),
  Audio-Transkription, leere Extraktion, Rückfrage, Pending-Ersatz.
"""

from __future__ import annotations

import datetime
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from kollege.channels import IncomingMessage, MemoryChannel
from kollege.config import Settings
from kollege.db import Repository
from kollege.models import (
    ExtractedContact,
    ExtractedProjectUpdate,
    ExtractedTask,
    ExtractionResult,
    ProjectStatus,
)
from kollege.orchestrator import (
    Orchestrator,
    dedupe_result,
    format_proposal,
    persist_result,
)
from kollege.transcription import StubTranscriber

SENDER = "+491234567890"
OTHER = "+4999999999"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _repo() -> Repository:
    return Repository(sqlite3.connect(":memory:", check_same_thread=False))


@pytest.fixture
def repo() -> Repository:
    return _repo()


@pytest.fixture
def channel() -> MemoryChannel:
    return MemoryChannel()


@pytest.fixture
def settings() -> Settings:
    return Settings()


@pytest.fixture
def log_dir(tmp_path: Path) -> Path:
    return tmp_path / "logs"


@pytest.fixture
def orc(
    channel: MemoryChannel,
    repo: Repository,
    settings: Settings,
    log_dir: Path,
) -> Orchestrator:
    return Orchestrator(
        channel=channel,
        repo=repo,
        transcriber=None,
        settings=settings,
        log_dir=log_dir,
    )


# ---------------------------------------------------------------------------
# Beispiel-Extraktionsergebnisse
# ---------------------------------------------------------------------------


def _result_task() -> ExtractionResult:
    return ExtractionResult(tasks=[ExtractedTask(title="Rückruf bei Müller")])


def _result_contact_and_task() -> ExtractionResult:
    return ExtractionResult(
        contacts=[ExtractedContact(name="Familie Müller")],
        tasks=[ExtractedTask(title="Angebot schicken", contact="Familie Müller")],
    )


def _result_empty() -> ExtractionResult:
    return ExtractionResult()


def _result_clarification() -> ExtractionResult:
    return ExtractionResult(clarification="Welches Projekt meinst du?")


# ---------------------------------------------------------------------------
# format_proposal
# ---------------------------------------------------------------------------


def test_format_proposal_single_item() -> None:
    result = ExtractionResult(tasks=[ExtractedTask(title="Test-Task")])
    text = format_proposal(result)
    assert "📋 Aufgabe: Test-Task" in text
    assert "ja" in text.lower()
    assert "1." not in text  # Keine Nummerierung bei Einzeleintrag


def test_format_proposal_multiple_items() -> None:
    result = _result_contact_and_task()
    text = format_proposal(result)
    assert "1." in text
    assert "2." in text
    assert "👤 Kontakt: Familie Müller" in text
    assert "📋 Aufgabe: Angebot schicken" in text


def test_format_proposal_due_date() -> None:
    result = ExtractionResult(
        tasks=[ExtractedTask(title="Fristaufgabe", due=datetime.date(2026, 7, 15))]
    )
    text = format_proposal(result)
    assert "fällig: 2026-07-15" in text


def test_format_proposal_project_update() -> None:
    result = ExtractionResult(
        project_updates=[ExtractedProjectUpdate(project="Hausgarten", status=ProjectStatus.PLANUNG)]
    )
    text = format_proposal(result)
    assert "📁 Projekt: Hausgarten" in text
    assert "planung" in text.lower()


def test_format_proposal_task_without_due_shows_kein_datum() -> None:
    """Eine Aufgabe ohne Frist zeigt explizit '(kein Datum)' — sichtbar VOR Bestätigung."""
    result = ExtractionResult(tasks=[ExtractedTask(title="Ohne Frist")])
    text = format_proposal(result)
    assert "(kein Datum)" in text


# ---------------------------------------------------------------------------
# dedupe_result
# ---------------------------------------------------------------------------


def test_dedupe_result_removes_duplicate_tasks() -> None:
    result = ExtractionResult(
        tasks=[
            ExtractedTask(title="Müller anrufen"),
            ExtractedTask(title="  müller   anrufen "),  # nur Whitespace/Case anders
        ]
    )
    deduped = dedupe_result(result)
    assert len(deduped.tasks) == 1


def test_dedupe_result_keeps_tasks_with_different_due() -> None:
    result = ExtractionResult(
        tasks=[
            ExtractedTask(title="Anruf", due=datetime.date(2026, 7, 1)),
            ExtractedTask(title="Anruf", due=datetime.date(2026, 7, 2)),
        ]
    )
    deduped = dedupe_result(result)
    assert len(deduped.tasks) == 2


def test_dedupe_result_dedups_contacts_and_updates() -> None:
    result = ExtractionResult(
        contacts=[ExtractedContact(name="Tom"), ExtractedContact(name="tom")],
        project_updates=[
            ExtractedProjectUpdate(project="Park"),
            ExtractedProjectUpdate(project="Park"),
        ],
    )
    deduped = dedupe_result(result)
    assert len(deduped.contacts) == 1
    assert len(deduped.project_updates) == 1


def test_dedupe_result_preserves_clarification_and_order() -> None:
    result = ExtractionResult(
        tasks=[ExtractedTask(title="Erste"), ExtractedTask(title="Zweite")],
        clarification="Hinweis",
    )
    deduped = dedupe_result(result)
    assert [t.title for t in deduped.tasks] == ["Erste", "Zweite"]
    assert deduped.clarification == "Hinweis"


# ---------------------------------------------------------------------------
# persist_result
# ---------------------------------------------------------------------------


def test_persist_result_contact(repo: Repository, log_dir: Path) -> None:
    result = ExtractionResult(contacts=[ExtractedContact(name="Max Muster")])
    count = persist_result(result, None, repo, log_dir)
    assert count == 1
    assert repo.get_contact_by_name("Max Muster") is not None


def test_persist_result_task_resolves_contact(repo: Repository, log_dir: Path) -> None:
    result = ExtractionResult(
        contacts=[ExtractedContact(name="Fam. Schulz")],
        tasks=[ExtractedTask(title="Besichtigung", contact="Fam. Schulz")],
    )
    count = persist_result(result, None, repo, log_dir)
    assert count == 2
    tasks = repo.query_open_items()
    assert len(tasks) == 1
    assert tasks[0].contact_id is not None


def test_persist_result_task_creates_project_log(repo: Repository, log_dir: Path) -> None:
    result = ExtractionResult(tasks=[ExtractedTask(title="Besprechung", project="Stadtpark")])
    persist_result(result, None, repo, log_dir)
    tasks = repo.query_open_items()
    assert len(tasks) == 1
    assert tasks[0].project_id is not None


def test_persist_result_partial_selection(repo: Repository, log_dir: Path) -> None:
    """Nur Index 0 (Kontakt) soll gespeichert werden, nicht Index 1 (Task)."""
    result = ExtractionResult(
        contacts=[ExtractedContact(name="Herr Bauer")],
        tasks=[ExtractedTask(title="Anruf vorbereiten")],
    )
    count = persist_result(result, [0], repo, log_dir)
    assert count == 1
    assert repo.get_contact_by_name("Herr Bauer") is not None
    assert repo.query_open_items() == []


def test_persist_result_empty_returns_zero(repo: Repository, log_dir: Path) -> None:
    count = persist_result(_result_empty(), None, repo, log_dir)
    assert count == 0


def test_persist_result_project_update_creates_log_file(repo: Repository, log_dir: Path) -> None:
    result = ExtractionResult(
        project_updates=[ExtractedProjectUpdate(project="Waldpark", status=ProjectStatus.UMSETZUNG)]
    )
    persist_result(result, None, repo, log_dir)
    log_files = list(log_dir.glob("*.md"))
    assert len(log_files) == 1


# ---------------------------------------------------------------------------
# Orchestrator — normaler Ablauf
# ---------------------------------------------------------------------------


def test_handle_text_message_sends_proposal(orc: Orchestrator, channel: MemoryChannel) -> None:
    with patch("kollege.orchestrator.run_extraction", return_value=_result_task()):
        orc.handle_message(IncomingMessage(sender=SENDER, text="Ruf bei Müller an"))
    assert len(channel.sent) == 2  # Sofort-Quittung + Vorschlag
    assert "verarbeite" in channel.sent[0][1].lower()  # Quittung zuerst
    assert "📋" in channel.sent[-1][1]  # Vorschlag als letzte Nachricht
    assert SENDER in orc._pending


def test_handle_empty_result_no_pending(orc: Orchestrator, channel: MemoryChannel) -> None:
    with patch("kollege.orchestrator.run_extraction", return_value=_result_empty()):
        orc.handle_message(IncomingMessage(sender=SENDER, text="Hallo"))
    assert len(channel.sent) == 2  # Sofort-Quittung + "nichts erkannt"
    assert "konnte" in channel.sent[-1][1].lower()
    assert SENDER not in orc._pending


def test_handle_clarification_sends_question(orc: Orchestrator, channel: MemoryChannel) -> None:
    with patch("kollege.orchestrator.run_extraction", return_value=_result_clarification()):
        orc.handle_message(IncomingMessage(sender=SENDER, text="Irgendwas"))
    assert len(channel.sent) == 2  # Sofort-Quittung + Rückfrage
    assert "Rückfrage" in channel.sent[-1][1]
    assert SENDER not in orc._pending


def test_handle_audio_uses_transcriber(
    repo: Repository,
    channel: MemoryChannel,
    settings: Settings,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    audio_file = tmp_path / "test.ogg"
    audio_file.write_bytes(b"fake-audio")
    stub = StubTranscriber(canned_text="Ruf bei Schmidt an")

    orchestrator = Orchestrator(
        channel=channel,
        repo=repo,
        transcriber=stub,
        settings=settings,
        log_dir=log_dir,
    )
    fake_result = ExtractionResult(tasks=[ExtractedTask(title="Ruf bei Schmidt an")])
    with patch("kollege.orchestrator.run_extraction", return_value=fake_result):
        orchestrator.handle_message(IncomingMessage(sender=SENDER, audio_path=audio_file))
    assert len(channel.sent) == 2  # Sofort-Quittung (🎤) + Vorschlag
    assert "🎤" in channel.sent[0][1]
    assert "Schmidt" in channel.sent[-1][1]


def test_no_transcriber_ignores_audio_only_message(
    orc: Orchestrator, channel: MemoryChannel, tmp_path: Path
) -> None:
    """Ohne Transcriber wird eine reine Audio-Nachricht still verworfen."""
    audio_file = tmp_path / "x.ogg"
    audio_file.write_bytes(b"data")
    orc.handle_message(IncomingMessage(sender=SENDER, audio_path=audio_file))
    assert channel.sent == []


# ---------------------------------------------------------------------------
# Orchestrator — Bestätigungs-Loop
# ---------------------------------------------------------------------------


def _prime_pending(orc: Orchestrator, channel: MemoryChannel) -> None:
    """Einen Vorschlag in den Pending-State bringen."""
    with patch("kollege.orchestrator.run_extraction", return_value=_result_task()):
        orc.handle_message(IncomingMessage(sender=SENDER, text="Test"))
    channel.sent.clear()


def test_confirm_ja_persists(orc: Orchestrator, channel: MemoryChannel, repo: Repository) -> None:
    _prime_pending(orc, channel)
    orc.handle_message(IncomingMessage(sender=SENDER, text="ja"))
    assert SENDER not in orc._pending
    assert "✅" in channel.sent[0][1]
    assert len(repo.query_open_items()) == 1


def test_confirm_thumbsup_persists(
    orc: Orchestrator, channel: MemoryChannel, repo: Repository
) -> None:
    _prime_pending(orc, channel)
    orc.handle_message(IncomingMessage(sender=SENDER, text="👍"))
    assert SENDER not in orc._pending
    assert len(repo.query_open_items()) == 1


def test_confirm_ja_case_insensitive(
    orc: Orchestrator, channel: MemoryChannel, repo: Repository
) -> None:
    _prime_pending(orc, channel)
    orc.handle_message(IncomingMessage(sender=SENDER, text="JA"))
    assert len(repo.query_open_items()) == 1


def test_reject_nein_discards(orc: Orchestrator, channel: MemoryChannel, repo: Repository) -> None:
    _prime_pending(orc, channel)
    orc.handle_message(IncomingMessage(sender=SENDER, text="nein"))
    assert SENDER not in orc._pending
    assert "Verworfen" in channel.sent[0][1]
    assert repo.query_open_items() == []


def test_selection_by_number_persists_subset(
    orc: Orchestrator, channel: MemoryChannel, repo: Repository
) -> None:
    """Auswahl "1" → nur erster Eintrag (Kontakt) persistiert, Task nicht."""
    with patch("kollege.orchestrator.run_extraction", return_value=_result_contact_and_task()):
        orc.handle_message(IncomingMessage(sender=SENDER, text="Test"))
    channel.sent.clear()

    orc.handle_message(IncomingMessage(sender=SENDER, text="1"))
    assert SENDER not in orc._pending
    assert repo.get_contact_by_name("Familie Müller") is not None
    assert repo.query_open_items() == []


def test_new_message_while_pending_replaces_proposal(
    orc: Orchestrator, channel: MemoryChannel
) -> None:
    """Neue Nachricht (kein ja/nein) überschreibt alten Vorschlag."""
    _prime_pending(orc, channel)
    assert SENDER in orc._pending

    new_result = ExtractionResult(tasks=[ExtractedTask(title="Neue Aufgabe")])
    with patch("kollege.orchestrator.run_extraction", return_value=new_result):
        orc.handle_message(IncomingMessage(sender=SENDER, text="Neue Notiz"))

    assert SENDER in orc._pending
    assert orc._pending[SENDER].result.tasks[0].title == "Neue Aufgabe"


def test_pending_isolated_per_sender(
    orc: Orchestrator, channel: MemoryChannel, repo: Repository
) -> None:
    """Bestätigung von SENDER lässt OTHER-Pending unberührt."""
    with patch("kollege.orchestrator.run_extraction", return_value=_result_task()):
        orc.handle_message(IncomingMessage(sender=SENDER, text="Notiz 1"))
        orc.handle_message(IncomingMessage(sender=OTHER, text="Notiz 2"))
    channel.sent.clear()

    orc.handle_message(IncomingMessage(sender=SENDER, text="ja"))
    assert SENDER not in orc._pending
    assert OTHER in orc._pending  # unveränderter Pending-State für OTHER


# ---------------------------------------------------------------------------
# run_once
# ---------------------------------------------------------------------------


def test_run_once_processes_multiple_messages(orc: Orchestrator, channel: MemoryChannel) -> None:
    channel.inbox.append(IncomingMessage(sender=SENDER, text="Notiz 1"))
    channel.inbox.append(IncomingMessage(sender=OTHER, text="Notiz 2"))

    with patch("kollege.orchestrator.run_extraction", return_value=_result_task()):
        orc.run_once()

    recipients = {r for r, _ in channel.sent}
    assert SENDER in recipients
    assert OTHER in recipients


def test_run_once_survives_error_and_continues(orc: Orchestrator, channel: MemoryChannel) -> None:
    """Ein Fehler bei einer Nachricht darf die Schleife nicht beenden (§6.2)."""
    channel.inbox.append(IncomingMessage(sender=SENDER, text="kaputt"))
    channel.inbox.append(IncomingMessage(sender=OTHER, text="ok"))

    def _boom_then_ok(transcript: str, *args: object, **kwargs: object) -> ExtractionResult:
        if transcript == "kaputt":
            raise RuntimeError("Ollama-Timeout simuliert")
        return _result_task()

    with patch("kollege.orchestrator.run_extraction", side_effect=_boom_then_ok):
        orc.run_once()

    by_recipient = dict(channel.sent)
    assert "Fehler" in by_recipient[SENDER]  # knappe Fehlermeldung an den Absender
    assert "📋" in by_recipient[OTHER]  # zweite Nachricht wurde trotzdem verarbeitet


# ---------------------------------------------------------------------------
# Reaktions-Bestätigung (👍 als Tapback)
# ---------------------------------------------------------------------------


def test_reaction_thumbsup_confirms_pending(
    orc: Orchestrator, channel: MemoryChannel, repo: Repository
) -> None:
    _prime_pending(orc, channel)
    orc.handle_message(IncomingMessage(sender=SENDER, text="👍", is_reaction=True))
    assert SENDER not in orc._pending
    assert len(repo.query_open_items()) == 1


def test_reaction_without_pending_is_ignored(
    orc: Orchestrator, channel: MemoryChannel, repo: Repository
) -> None:
    """Eine Reaktion ohne offenen Vorschlag wird ignoriert (keine Extraktion)."""
    with patch("kollege.orchestrator.run_extraction") as mock_extract:
        orc.handle_message(IncomingMessage(sender=SENDER, text="👍", is_reaction=True))
    mock_extract.assert_not_called()
    assert channel.sent == []


def test_non_thumbsup_reaction_is_ignored(orc: Orchestrator, channel: MemoryChannel) -> None:
    """Ein anderes Emoji als 👍 bestätigt nicht und löst keine Extraktion aus."""
    _prime_pending(orc, channel)
    with patch("kollege.orchestrator.run_extraction") as mock_extract:
        orc.handle_message(IncomingMessage(sender=SENDER, text="😀", is_reaction=True))
    mock_extract.assert_not_called()
    assert SENDER in orc._pending  # Vorschlag bleibt offen
    assert channel.sent == []


# ---------------------------------------------------------------------------
# Dedup im Verarbeitungsfluss
# ---------------------------------------------------------------------------


def test_handle_message_dedups_overextracted_tasks(
    orc: Orchestrator, channel: MemoryChannel
) -> None:
    """Über-Extraktion (doppelte Tasks) wird vor dem Vorschlag entdoppelt (§6.5)."""
    noisy = ExtractionResult(
        tasks=[
            ExtractedTask(title="Müller anrufen"),
            ExtractedTask(title="Müller anrufen"),
        ]
    )
    with patch("kollege.orchestrator.run_extraction", return_value=noisy):
        orc.handle_message(IncomingMessage(sender=SENDER, text="Müller anrufen"))
    assert len(orc._pending[SENDER].result.tasks) == 1


# ---------------------------------------------------------------------------
# update_task_status (Repository-Erweiterung aus Schritt 7)
# ---------------------------------------------------------------------------


def test_update_task_status(repo: Repository) -> None:
    from kollege.models import Task, TaskSource, TaskStatus

    task = repo.create_task(
        Task(title="Testaufgabe", status=TaskStatus.OFFEN, source=TaskSource.MANUELL)
    )
    assert task.id is not None
    updated = repo.update_task_status(task.id, TaskStatus.ERLEDIGT)
    assert updated.status == TaskStatus.ERLEDIGT


def test_update_task_status_unknown_id_raises(repo: Repository) -> None:
    from kollege.models import TaskStatus

    with pytest.raises(ValueError, match="999"):
        repo.update_task_status(999, TaskStatus.ERLEDIGT)


# ---------------------------------------------------------------------------
# Sofort-Quittung (Schritt 8.8)
# ---------------------------------------------------------------------------


def test_ack_is_first_message_for_text_note(orc: Orchestrator, channel: MemoryChannel) -> None:
    """Sofort-Quittung erscheint als erste Nachricht, Vorschlag als zweite."""
    with patch("kollege.orchestrator.run_extraction", return_value=_result_task()):
        orc.handle_message(IncomingMessage(sender=SENDER, text="Ruf bei Müller an"))
    assert len(channel.sent) == 2
    ack_text = channel.sent[0][1]
    proposal_text = channel.sent[1][1]
    assert "verarbeite" in ack_text.lower()
    assert "📋" in proposal_text


def test_ack_contains_audio_emoji_for_voice_note(
    repo: Repository,
    channel: MemoryChannel,
    settings: Settings,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    """Sofort-Quittung für Sprachnachrichten enthält 🎤."""
    audio_file = tmp_path / "voice.ogg"
    audio_file.write_bytes(b"fake-audio")
    stub = StubTranscriber(canned_text="Test-Transkript")
    orchestrator = Orchestrator(
        channel=channel, repo=repo, transcriber=stub, settings=settings, log_dir=log_dir
    )
    with patch("kollege.orchestrator.run_extraction", return_value=_result_task()):
        orchestrator.handle_message(IncomingMessage(sender=SENDER, audio_path=audio_file))
    assert len(channel.sent) == 2
    assert "🎤" in channel.sent[0][1]


def test_no_ack_for_confirmation_ja(orc: Orchestrator, channel: MemoryChannel) -> None:
    """'ja' ist eine Bestätigungsantwort — keine Sofort-Quittung."""
    _prime_pending(orc, channel)
    orc.handle_message(IncomingMessage(sender=SENDER, text="ja"))
    assert len(channel.sent) == 1
    assert "✅" in channel.sent[0][1]


def test_no_ack_for_confirmation_nein(orc: Orchestrator, channel: MemoryChannel) -> None:
    """'nein' ist eine Ablehnungsantwort — keine Sofort-Quittung."""
    _prime_pending(orc, channel)
    orc.handle_message(IncomingMessage(sender=SENDER, text="nein"))
    assert len(channel.sent) == 1
    assert "Verworfen" in channel.sent[0][1]


def test_no_ack_for_tapback_reaction(
    orc: Orchestrator, channel: MemoryChannel, repo: Repository
) -> None:
    """Tapback-Reaktion (👍) löst keine Sofort-Quittung aus."""
    _prime_pending(orc, channel)
    orc.handle_message(IncomingMessage(sender=SENDER, text="👍", is_reaction=True))
    assert len(channel.sent) == 1
    assert "✅" in channel.sent[0][1]


def test_no_ack_for_audio_without_transcriber(
    orc: Orchestrator, channel: MemoryChannel, tmp_path: Path
) -> None:
    """Ohne Transcriber wird eine reine Sprachnachricht still verworfen — keine Quittung."""
    audio_file = tmp_path / "voice.ogg"
    audio_file.write_bytes(b"data")
    orc.handle_message(IncomingMessage(sender=SENDER, audio_path=audio_file))
    assert channel.sent == []


# ---------------------------------------------------------------------------
# Korrektur-/Revisions-Schleife (Quote-Reply, Schritt 8.6)
# ---------------------------------------------------------------------------


def _result_revised() -> ExtractionResult:
    """Revidiertes Extraktionsergebnis (z. B. korrigierter Name)."""
    return ExtractionResult(tasks=[ExtractedTask(title="Rückruf bei Schmidt")])


def test_quote_reply_triggers_revision(orc: Orchestrator, channel: MemoryChannel) -> None:
    """Eine Quote-Reply bei offenem Vorschlag löst den Revisions-Lauf aus."""
    _prime_pending(orc, channel)

    with patch("kollege.orchestrator.run_revision", return_value=_result_revised()) as mock_rev:
        orc.handle_message(
            IncomingMessage(
                sender=SENDER,
                text="Das ist nicht Herr Schnitt, sondern Schmidt",
                quote_target_timestamp=1_234_567_890,
            )
        )

    mock_rev.assert_called_once()
    # Quittung + revidierter Vorschlag
    assert len(channel.sent) >= 2
    texts = [t for _, t in channel.sent]
    assert any("überarbeite" in t.lower() for t in texts)
    assert any("Schmidt" in t for t in texts)
    # Vorschlag noch offen (nicht persistiert)
    assert SENDER in orc._pending
    assert orc._pending[SENDER].result.tasks[0].title == "Rückruf bei Schmidt"


def test_quote_reply_without_pending_is_new_note(orc: Orchestrator, channel: MemoryChannel) -> None:
    """Quote-Reply ohne offenen Vorschlag wird wie eine neue Notiz behandelt."""
    assert SENDER not in orc._pending

    with patch("kollege.orchestrator.run_extraction", return_value=_result_task()) as mock_ext:
        orc.handle_message(
            IncomingMessage(
                sender=SENDER,
                text="Irgendein zitierter Text",
                quote_target_timestamp=9_999_999_999,
            )
        )

    mock_ext.assert_called_once()
    assert SENDER in orc._pending


def test_quote_reply_yes_still_confirms(
    orc: Orchestrator, channel: MemoryChannel, repo: Repository
) -> None:
    """Quote-Reply mit Text 'ja' bestätigt den Vorschlag (nicht Korrektur-Lauf)."""
    _prime_pending(orc, channel)

    with patch("kollege.orchestrator.run_revision") as mock_rev:
        orc.handle_message(
            IncomingMessage(
                sender=SENDER,
                text="ja",
                quote_target_timestamp=1_234_567_890,
            )
        )

    mock_rev.assert_not_called()
    assert SENDER not in orc._pending
    assert len(repo.query_open_items()) == 1


def test_quote_reply_audio_uses_transcriber(
    repo: Repository,
    channel: MemoryChannel,
    settings: Settings,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    """Quote-Reply mit Audio wird transkribiert, dann als Korrekturtext verwendet."""
    audio_file = tmp_path / "correction.ogg"
    audio_file.write_bytes(b"fake-audio")
    stub = StubTranscriber(canned_text="Das ist nicht Schnitt sondern Schmidt")

    orchestrator = Orchestrator(
        channel=channel, repo=repo, transcriber=stub, settings=settings, log_dir=log_dir
    )
    with patch("kollege.orchestrator.run_extraction", return_value=_result_task()):
        orchestrator.handle_message(IncomingMessage(sender=SENDER, text="Erste Notiz"))
    channel.sent.clear()

    revised = _result_revised()
    with patch("kollege.orchestrator.run_revision", return_value=revised) as mock_rev:
        orchestrator.handle_message(
            IncomingMessage(
                sender=SENDER,
                audio_path=audio_file,
                quote_target_timestamp=1_234_567_890,
            )
        )

    mock_rev.assert_called_once()
    call_kwargs = mock_rev.call_args
    assert "Schmidt" in call_kwargs.kwargs.get("correction", "") or any(
        "Schmidt" in str(a) for a in call_kwargs.args
    )
    assert any("Schmidt" in t for _, t in channel.sent)


def test_quote_reply_revision_replaces_pending(orc: Orchestrator, channel: MemoryChannel) -> None:
    """Nach dem Korrektur-Lauf ist der Pending-State aktualisiert (nicht gelöscht)."""
    _prime_pending(orc, channel)
    original_result = orc._pending[SENDER].result

    revised = _result_revised()
    with patch("kollege.orchestrator.run_revision", return_value=revised):
        orc.handle_message(
            IncomingMessage(
                sender=SENDER,
                text="Korrektur: Schmidt",
                quote_target_timestamp=1_111_111_111,
            )
        )

    assert SENDER in orc._pending
    assert orc._pending[SENDER].result is not original_result
    assert orc._pending[SENDER].result.tasks[0].title == "Rückruf bei Schmidt"


def test_revised_proposal_can_be_confirmed(
    orc: Orchestrator, channel: MemoryChannel, repo: Repository
) -> None:
    """Korrigierter Vorschlag lässt sich anschließend per 'ja' bestätigen."""
    _prime_pending(orc, channel)

    with patch("kollege.orchestrator.run_revision", return_value=_result_revised()):
        orc.handle_message(
            IncomingMessage(
                sender=SENDER,
                text="Nicht Schnitt, sondern Schmidt",
                quote_target_timestamp=1_234_567_890,
            )
        )
    channel.sent.clear()

    orc.handle_message(IncomingMessage(sender=SENDER, text="ja"))
    assert SENDER not in orc._pending
    tasks = repo.query_open_items()
    assert len(tasks) == 1
    assert tasks[0].title == "Rückruf bei Schmidt"


def test_pending_stores_sent_timestamp(orc: Orchestrator, channel: MemoryChannel) -> None:
    """PendingProposal.sent_timestamp wird nach dem Senden des Vorschlags gesetzt."""
    with patch("kollege.orchestrator.run_extraction", return_value=_result_task()):
        orc.handle_message(IncomingMessage(sender=SENDER, text="Notiz"))
    # MemoryChannel.send() gibt None zurück — kein Crash, Wert ist None
    assert orc._pending[SENDER].sent_timestamp is None  # MemoryChannel liefert None
