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
    Task,
    TaskStatus,
)
from kollege.orchestrator import (
    Orchestrator,
    dedupe_result,
    format_contacts,
    format_date_de,
    format_open_tasks,
    format_projects,
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


@pytest.fixture(autouse=True)
def _passthrough_gap_check() -> object:
    """Zweiten Durchgang (Schritt 8.18) standardmäßig als Passthrough neutralisieren.

    Die meisten Orchestrator-Tests mocken nur den *ersten* Durchgang
    (``run_extraction``) und erwarten dessen Ergebnis unverändert im Vorschlag.
    ``_extract`` ruft danach ``run_gap_check`` auf — hier als Identität gemockt
    (gibt das Erstergebnis zurück), damit kein echtes Modell gebaut wird. Tests,
    die den zweiten Durchgang gezielt prüfen, überschreiben diesen Patch lokal.
    """
    with patch(
        "kollege.orchestrator.run_gap_check",
        side_effect=lambda original_transcript, first_result, *a, **k: first_result,
    ):
        yield


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
    assert "fällig: Mi. 15. Juli 2026" in text  # deutsche Anzeige (Schritt 8.18)


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


def test_format_proposal_mentions_correction_via_quote_reply() -> None:
    """Jeder Vorschlag erklärt auch die Korrektur-Funktion (Zitat-Antwort), nicht nur ja/nein."""
    single = format_proposal(ExtractionResult(tasks=[ExtractedTask(title="Eins")]))
    multi = format_proposal(_result_contact_and_task())
    for text in (single, multi):
        assert "Zitat" in text
        assert "korrigieren" in text.lower()


# ---------------------------------------------------------------------------
# format_proposal — Neue-Projekte-Markierung (Schritt 8.25)
# ---------------------------------------------------------------------------


def test_format_proposal_marks_unknown_project_as_new_on_task(repo: Repository) -> None:
    result = ExtractionResult(
        tasks=[ExtractedTask(title="Planung starten", project="Neuer Garten")]
    )
    text = format_proposal(result, repo)
    assert "[Neuer Garten — neu]" in text


def test_format_proposal_marks_unknown_project_as_new_on_update(repo: Repository) -> None:
    result = ExtractionResult(
        project_updates=[ExtractedProjectUpdate(project="Neuprojekt", status=ProjectStatus.PLANUNG)]
    )
    text = format_proposal(result, repo)
    assert "📁 Projekt: Neuprojekt — neu" in text


def test_format_proposal_does_not_mark_existing_project(repo: Repository) -> None:
    repo.get_or_create_project("Bestehender Garten")
    result = ExtractionResult(
        tasks=[ExtractedTask(title="Nachpflege", project="Bestehender Garten")]
    )
    text = format_proposal(result, repo)
    assert "[Bestehender Garten]" in text
    assert "neu" not in text.lower()


def test_format_proposal_without_repo_shows_no_marker() -> None:
    """Ohne Repo-Argument (Rückwärtskompatibilität) entfällt die Neu-Markierung."""
    result = ExtractionResult(tasks=[ExtractedTask(title="X", project="Irgendein Projekt")])
    text = format_proposal(result)
    assert "neu" not in text.lower()


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
    summary = persist_result(result, None, repo, log_dir)
    assert summary.count == 1
    assert repo.get_contact_by_name("Max Muster") is not None


def test_persist_result_task_resolves_contact(repo: Repository, log_dir: Path) -> None:
    result = ExtractionResult(
        contacts=[ExtractedContact(name="Fam. Schulz")],
        tasks=[ExtractedTask(title="Besichtigung", contact="Fam. Schulz")],
    )
    summary = persist_result(result, None, repo, log_dir)
    assert summary.count == 2
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
    summary = persist_result(result, [0], repo, log_dir)
    assert summary.count == 1
    assert repo.get_contact_by_name("Herr Bauer") is not None
    assert repo.query_open_items() == []


def test_persist_result_empty_returns_zero(repo: Repository, log_dir: Path) -> None:
    summary = persist_result(_result_empty(), None, repo, log_dir)
    assert summary.count == 0


def test_persist_result_project_update_creates_log_file(repo: Repository, log_dir: Path) -> None:
    result = ExtractionResult(
        project_updates=[ExtractedProjectUpdate(project="Waldpark", status=ProjectStatus.UMSETZUNG)]
    )
    persist_result(result, None, repo, log_dir)
    log_files = list(log_dir.glob("*.md"))
    assert len(log_files) == 1


def test_persist_result_project_update_writes_log_entry(repo: Repository, log_dir: Path) -> None:
    """Schritt 8.16: eine bestätigte Projektaktualisierung schreibt einen Log-Eintrag,
    nicht nur die leere Log-Datei."""
    result = ExtractionResult(
        project_updates=[
            ExtractedProjectUpdate(
                project="Waldpark", status=ProjectStatus.UMSETZUNG, phase_note="Zaun gestrichen"
            )
        ]
    )
    persist_result(result, None, repo, log_dir)
    log_file = next(log_dir.glob("*.md"))
    content = log_file.read_text(encoding="utf-8")
    assert "Status: umsetzung" in content
    assert "Zaun gestrichen" in content
    assert "Sprachnotiz" in content


def test_persist_result_task_with_project_writes_log_entry(repo: Repository, log_dir: Path) -> None:
    """Schritt 8.16: eine bestätigte projektbezogene Aufgabe schreibt einen Log-Eintrag."""
    result = ExtractionResult(tasks=[ExtractedTask(title="Angebot erstellen", project="Stadtpark")])
    persist_result(result, None, repo, log_dir)
    log_file = next(log_dir.glob("*.md"))
    content = log_file.read_text(encoding="utf-8")
    assert "Neue Aufgabe: Angebot erstellen" in content


def test_persist_result_appends_multiple_entries_to_same_log(
    repo: Repository, log_dir: Path
) -> None:
    """Zwei bestätigte Änderungen zum selben Projekt ergeben zwei Log-Einträge, nicht ein
    Überschreiben des ersten (append-only, Prinzip 4)."""
    first = ExtractionResult(
        project_updates=[ExtractedProjectUpdate(project="Waldpark", status=ProjectStatus.PLANUNG)]
    )
    persist_result(first, None, repo, log_dir)
    second = ExtractionResult(tasks=[ExtractedTask(title="Zaun streichen", project="Waldpark")])
    persist_result(second, None, repo, log_dir)

    log_files = list(log_dir.glob("*.md"))
    assert len(log_files) == 1
    content = log_files[0].read_text(encoding="utf-8")
    assert "Status: planung" in content
    assert "Neue Aufgabe: Zaun streichen" in content


# ---------------------------------------------------------------------------
# persist_result — PersistSummary.new_projects (Schritt 8.25)
# ---------------------------------------------------------------------------


def test_persist_result_summary_lists_new_project_from_task(
    repo: Repository, log_dir: Path
) -> None:
    result = ExtractionResult(tasks=[ExtractedTask(title="Planung", project="Frischer Garten")])
    summary = persist_result(result, None, repo, log_dir)
    assert summary.count == 1
    assert summary.new_projects == ["Frischer Garten"]


def test_persist_result_summary_lists_new_project_from_update(
    repo: Repository, log_dir: Path
) -> None:
    result = ExtractionResult(
        project_updates=[
            ExtractedProjectUpdate(project="Frischer Park", status=ProjectStatus.PLANUNG)
        ]
    )
    summary = persist_result(result, None, repo, log_dir)
    assert summary.new_projects == ["Frischer Park"]


def test_persist_result_summary_empty_for_existing_project(repo: Repository, log_dir: Path) -> None:
    repo.get_or_create_project("Alter Garten")
    result = ExtractionResult(tasks=[ExtractedTask(title="Pflege", project="Alter Garten")])
    summary = persist_result(result, None, repo, log_dir)
    assert summary.count == 1
    assert summary.new_projects == []


def test_persist_result_summary_dedupes_same_new_project_across_tasks(
    repo: Repository, log_dir: Path
) -> None:
    """Zwei Aufgaben im selben neuen Projekt → Projekt taucht nur einmal in new_projects auf."""
    result = ExtractionResult(
        tasks=[
            ExtractedTask(title="Erste", project="Doppelt Neu"),
            ExtractedTask(title="Zweite", project="Doppelt Neu"),
        ]
    )
    summary = persist_result(result, None, repo, log_dir)
    assert summary.count == 2
    assert summary.new_projects == ["Doppelt Neu"]


# ---------------------------------------------------------------------------
# format_date_de — deutsche Datumsanzeige (Schritt 8.18)
# ---------------------------------------------------------------------------


def test_format_date_de_example() -> None:
    """DoD-Beispiel: 2026-07-02 → »Do. 2. Juli 2026« (kein führende Null)."""
    assert format_date_de(datetime.date(2026, 7, 2)) == "Do. 2. Juli 2026"


def test_format_date_de_umlaut_month_and_weekday() -> None:
    """März mit Umlaut, Montag als »Mo.«, zweistelliger Tag ohne Änderung."""
    assert format_date_de(datetime.date(2026, 3, 30)) == "Mo. 30. März 2026"


def test_format_date_de_shown_in_proposal_and_open_tasks() -> None:
    """Fälligkeit wird im Vorschlag *und* in /offen deutsch formatiert angezeigt."""
    due = datetime.date(2026, 12, 1)  # Dienstag
    result = ExtractionResult(tasks=[ExtractedTask(title="Winterschnitt", due=due)])
    assert "Di. 1. Dezember 2026" in format_proposal(result)
    task = Task(id=7, title="Winterschnitt", due=due, status=TaskStatus.OFFEN)
    assert "Di. 1. Dezember 2026" in format_open_tasks([task])


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


# ---------------------------------------------------------------------------
# Zwei-Durchgang-Extraktion (Schritt 8.18)
# ---------------------------------------------------------------------------


def test_second_pass_enriches_and_fills_gaps(orc: Orchestrator, channel: MemoryChannel) -> None:
    """Der zweite Durchgang füllt Lücken und trägt Übersehenes nach.

    Erster Durchgang: eine Aufgabe ohne Frist. Zweiter Durchgang (``run_gap_check``):
    ergänzt die Frist und eine im Text übersehene zweite Aufgabe. Der Vorschlag an
    die Nutzerin muss das *angereicherte* Ergebnis zeigen.
    """
    first = ExtractionResult(tasks=[ExtractedTask(title="Angebot schicken")])
    enriched = ExtractionResult(
        tasks=[
            ExtractedTask(title="Angebot schicken", due=datetime.date(2026, 7, 2)),
            ExtractedTask(title="Vor dem Termin Unterlagen prüfen"),
        ]
    )
    with (
        patch("kollege.orchestrator.run_extraction", return_value=first),
        patch("kollege.orchestrator.run_gap_check", return_value=enriched) as gap,
    ):
        orc.handle_message(IncomingMessage(sender=SENDER, text="Angebot an Müller"))

    gap.assert_called_once()
    # Erstergebnis wird als zweites Positionsargument an run_gap_check gereicht.
    assert gap.call_args.args[1] is first
    proposal = channel.sent[-1][1]
    assert "Vor dem Termin Unterlagen prüfen" in proposal  # übersehene Aufgabe ergänzt
    assert "Do. 2. Juli 2026" in proposal  # ergänzte Frist, deutsch formatiert
    assert SENDER in orc._pending


def test_clarification_in_first_pass_skips_second_pass(
    orc: Orchestrator, channel: MemoryChannel
) -> None:
    """Stellt der erste Durchgang eine Rückfrage, läuft kein zweiter Durchgang."""
    with (
        patch("kollege.orchestrator.run_extraction", return_value=_result_clarification()),
        patch("kollege.orchestrator.run_gap_check") as gap,
    ):
        orc.handle_message(IncomingMessage(sender=SENDER, text="Irgendwas"))
    gap.assert_not_called()
    assert "Rückfrage" in channel.sent[-1][1]


def test_second_pass_failure_falls_back_to_first_result(
    orc: Orchestrator, channel: MemoryChannel
) -> None:
    """Scheitert der zweite Durchgang, wird das Erstergebnis genutzt (kein Abbruch)."""
    with (
        patch("kollege.orchestrator.run_extraction", return_value=_result_task()),
        patch("kollege.orchestrator.run_gap_check", side_effect=RuntimeError("LLM weg")),
    ):
        orc.handle_message(IncomingMessage(sender=SENDER, text="Ruf bei Müller an"))
    assert "📋" in channel.sent[-1][1]  # Vorschlag aus Erstergebnis
    assert SENDER in orc._pending


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


# ---------------------------------------------------------------------------
# Neue Projekte in Vorschlag & Bestätigung sichtbar (Schritt 8.25, E2E)
# ---------------------------------------------------------------------------


def test_new_project_marked_in_proposal_and_named_in_confirmation(
    orc: Orchestrator, channel: MemoryChannel, repo: Repository
) -> None:
    """DoD: Notiz mit Aufgabe in unbekanntem Projekt → Vorschlag markiert das Projekt
    als neu, Bestätigungs-Nachricht nennt es explizit."""
    result = ExtractionResult(
        tasks=[ExtractedTask(title="Erstgespräch", project="Neuer Kundengarten")]
    )
    with patch("kollege.orchestrator.run_extraction", return_value=result):
        orc.handle_message(IncomingMessage(sender=SENDER, text="Notiz"))
    proposal_text = channel.sent[-1][1]
    assert "Neuer Kundengarten — neu" in proposal_text

    channel.sent.clear()
    orc.handle_message(IncomingMessage(sender=SENDER, text="ja"))
    confirm_text = channel.sent[0][1]
    assert "✅" in confirm_text
    assert "Neues Projekt angelegt" in confirm_text
    assert '"Neuer Kundengarten"' in confirm_text
    assert repo.get_project_by_title("Neuer Kundengarten") is not None


def test_existing_project_not_marked_and_not_named_in_confirmation(
    orc: Orchestrator, channel: MemoryChannel, repo: Repository
) -> None:
    """DoD: bestehendes Projekt → keine Neu-Markierung, Zählung bleibt korrekt."""
    repo.get_or_create_project("Alter Kundengarten")
    result = ExtractionResult(
        tasks=[ExtractedTask(title="Nachpflege", project="Alter Kundengarten")]
    )
    with patch("kollege.orchestrator.run_extraction", return_value=result):
        orc.handle_message(IncomingMessage(sender=SENDER, text="Notiz"))
    proposal_text = channel.sent[-1][1]
    assert "neu" not in proposal_text.lower()

    channel.sent.clear()
    orc.handle_message(IncomingMessage(sender=SENDER, text="ja"))
    confirm_text = channel.sent[0][1]
    assert confirm_text == "✅ 1 Eintrag/Einträge gespeichert."


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


@pytest.mark.parametrize("emoji", ["👍", "👍🏼", "👍️", "👌", "✅"])
def test_reaction_variants_confirm_pending(
    orc: Orchestrator, channel: MemoryChannel, repo: Repository, emoji: str
) -> None:
    """👍 mit Hautton/Variation-Selector sowie 👌/✅ gelten als Bestätigung."""
    _prime_pending(orc, channel)
    orc.handle_message(IncomingMessage(sender=SENDER, text=emoji, is_reaction=True))
    assert SENDER not in orc._pending
    assert len(repo.query_open_items()) == 1


def test_thumbsdown_reaction_rejects_pending(
    orc: Orchestrator, channel: MemoryChannel, repo: Repository
) -> None:
    """👎 auf einen offenen Vorschlag verwirft ihn (keine Persistenz)."""
    _prime_pending(orc, channel)
    orc.handle_message(IncomingMessage(sender=SENDER, text="👎", is_reaction=True))
    assert SENDER not in orc._pending
    assert repo.query_open_items() == []
    assert "Verworfen" in channel.sent[-1][1]


# ---------------------------------------------------------------------------
# Rückfrage-Antwort-Schleife (Schritt 8.13)
# ---------------------------------------------------------------------------


def _prime_clarification(orc: Orchestrator, channel: MemoryChannel) -> None:
    """Eine offene Rückfrage in den Pending-State bringen."""
    with patch("kollege.orchestrator.run_extraction", return_value=_result_clarification()):
        orc.handle_message(IncomingMessage(sender=SENDER, text="Kräutergarten anlegen"))
    channel.sent.clear()


def test_clarification_creates_pending_clarification(
    orc: Orchestrator, channel: MemoryChannel
) -> None:
    """Eine Rückfrage legt einen offenen Klärungs-Zustand an (nicht mehr Sackgasse)."""
    _prime_clarification(orc, channel)
    assert SENDER in orc._pending_clarifications
    assert SENDER not in orc._pending
    assert orc._pending_clarifications[SENDER].question == "Welches Projekt meinst du?"


def test_thumbsup_on_clarification_triggers_response_run(
    orc: Orchestrator, channel: MemoryChannel, repo: Repository
) -> None:
    """👍 auf eine Rückfrage wird als 'Ja' beantwortet → Vorschlag entsteht."""
    _prime_clarification(orc, channel)
    with patch(
        "kollege.orchestrator.run_clarification_response", return_value=_result_task()
    ) as mock_resp:
        orc.handle_message(IncomingMessage(sender=SENDER, text="👍", is_reaction=True))
    mock_resp.assert_called_once()
    # Antwort "Ja." wird an den Klärungs-Lauf durchgereicht.
    assert mock_resp.call_args.kwargs["answer"] == "Ja."
    # Ergebnis wird zum normalen Vorschlag → Bestätigungs-Loop.
    assert SENDER in orc._pending
    assert SENDER not in orc._pending_clarifications
    assert "📋" in channel.sent[-1][1]


def test_text_answer_to_clarification_triggers_response_run(
    orc: Orchestrator, channel: MemoryChannel
) -> None:
    """Freitext-Antwort auf eine Rückfrage geht in den Klärungs-Lauf, nicht in neue Extraktion."""
    _prime_clarification(orc, channel)
    with (
        patch("kollege.orchestrator.run_extraction") as mock_extract,
        patch(
            "kollege.orchestrator.run_clarification_response", return_value=_result_task()
        ) as mock_resp,
    ):
        orc.handle_message(IncomingMessage(sender=SENDER, text="Ja, als Dienstleister"))
    mock_extract.assert_not_called()
    mock_resp.assert_called_once()
    assert mock_resp.call_args.kwargs["answer"] == "Ja, als Dienstleister"
    assert SENDER in orc._pending


def test_nein_to_clarification_discards_without_llm(
    orc: Orchestrator, channel: MemoryChannel
) -> None:
    """'nein' verwirft die Rückfrage ohne LLM-Lauf."""
    _prime_clarification(orc, channel)
    with (
        patch("kollege.orchestrator.run_clarification_response") as mock_resp,
        patch("kollege.orchestrator.run_extraction") as mock_extract,
    ):
        orc.handle_message(IncomingMessage(sender=SENDER, text="nein"))
    mock_resp.assert_not_called()
    mock_extract.assert_not_called()
    assert SENDER not in orc._pending_clarifications
    assert "Verworfen" in channel.sent[-1][1]


def test_thumbsdown_on_clarification_discards(orc: Orchestrator, channel: MemoryChannel) -> None:
    """👎 auf eine Rückfrage verwirft sie ohne LLM-Lauf."""
    _prime_clarification(orc, channel)
    with patch("kollege.orchestrator.run_clarification_response") as mock_resp:
        orc.handle_message(IncomingMessage(sender=SENDER, text="👎", is_reaction=True))
    mock_resp.assert_not_called()
    assert SENDER not in orc._pending_clarifications
    assert "Verworfen" in channel.sent[-1][1]


def test_clarification_answer_can_ask_again(orc: Orchestrator, channel: MemoryChannel) -> None:
    """Bleibt es nach der Antwort unklar, wird erneut eine Rückfrage gestellt."""
    _prime_clarification(orc, channel)
    followup = ExtractionResult(clarification="Welcher Nachname genau?")
    with patch("kollege.orchestrator.run_clarification_response", return_value=followup):
        orc.handle_message(IncomingMessage(sender=SENDER, text="Der Neue"))
    assert SENDER in orc._pending_clarifications
    assert orc._pending_clarifications[SENDER].question == "Welcher Nachname genau?"
    assert SENDER not in orc._pending
    assert "Rückfrage" in channel.sent[-1][1]


def test_thumbsup_on_clarification_uses_original_transcript(
    orc: Orchestrator, channel: MemoryChannel
) -> None:
    """Der Klärungs-Lauf bekommt das Ursprungstranskript + die gestellte Frage."""
    _prime_clarification(orc, channel)
    with patch(
        "kollege.orchestrator.run_clarification_response", return_value=_result_task()
    ) as mock_resp:
        orc.handle_message(IncomingMessage(sender=SENDER, text="👍", is_reaction=True))
    kwargs = mock_resp.call_args.kwargs
    assert kwargs["original_transcript"] == "Kräutergarten anlegen"
    assert kwargs["clarification_question"] == "Welches Projekt meinst du?"


def test_first_clarification_answer_passes_empty_history(
    orc: Orchestrator, channel: MemoryChannel
) -> None:
    """Die erste Rückfrage-Antwort einer Interaktion hat noch keine Vorgeschichte."""
    _prime_clarification(orc, channel)
    with patch(
        "kollege.orchestrator.run_clarification_response", return_value=_result_task()
    ) as mock_resp:
        orc.handle_message(IncomingMessage(sender=SENDER, text="Ja, als Dienstleister"))
    assert mock_resp.call_args.kwargs["history"] == []


def test_resolved_clarification_stores_qa_in_proposal_history(
    orc: Orchestrator, channel: MemoryChannel
) -> None:
    """Nach Auflösung einer Rückfrage trägt der neue Vorschlag Frage+Antwort als Historie."""
    _prime_clarification(orc, channel)
    with patch("kollege.orchestrator.run_clarification_response", return_value=_result_task()):
        orc.handle_message(IncomingMessage(sender=SENDER, text="Ja, als Dienstleister"))
    assert orc._pending[SENDER].history == [
        ("Rückfrage", "Welches Projekt meinst du?"),
        ("Antwort", "Ja, als Dienstleister"),
    ]


def test_repeated_clarification_accumulates_history(
    orc: Orchestrator, channel: MemoryChannel
) -> None:
    """Bleibt es nach der Antwort unklar, akkumuliert die neue Rückfrage die Historie."""
    _prime_clarification(orc, channel)
    followup = ExtractionResult(clarification="Welcher Nachname genau?")
    with patch("kollege.orchestrator.run_clarification_response", return_value=followup):
        orc.handle_message(IncomingMessage(sender=SENDER, text="Der Neue"))
    assert orc._pending_clarifications[SENDER].history == [
        ("Rückfrage", "Welches Projekt meinst du?"),
        ("Antwort", "Der Neue"),
    ]

    with patch(
        "kollege.orchestrator.run_clarification_response", return_value=_result_task()
    ) as mock_resp:
        orc.handle_message(IncomingMessage(sender=SENDER, text="Schmidt"))
    assert mock_resp.call_args.kwargs["history"] == [
        ("Rückfrage", "Welches Projekt meinst du?"),
        ("Antwort", "Der Neue"),
    ]
    assert orc._pending[SENDER].history == [
        ("Rückfrage", "Welches Projekt meinst du?"),
        ("Antwort", "Der Neue"),
        ("Rückfrage", "Welcher Nachname genau?"),
        ("Antwort", "Schmidt"),
    ]


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
    from kollege.models import TaskSource

    task = repo.create_task(
        Task(title="Testaufgabe", status=TaskStatus.OFFEN, source=TaskSource.MANUELL)
    )
    assert task.id is not None
    updated = repo.update_task_status(task.id, TaskStatus.ERLEDIGT)
    assert updated.status == TaskStatus.ERLEDIGT


def test_update_task_status_unknown_id_raises(repo: Repository) -> None:
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


# ---------------------------------------------------------------------------
# Vollständige Interaktions-Historie (Schritt 8.14)
# ---------------------------------------------------------------------------


def test_first_revision_passes_empty_history(orc: Orchestrator, channel: MemoryChannel) -> None:
    """Der erste Korrektur-Lauf einer Interaktion hat noch keine Vorgeschichte."""
    _prime_pending(orc, channel)
    with patch("kollege.orchestrator.run_revision", return_value=_result_revised()) as mock_rev:
        orc.handle_message(
            IncomingMessage(
                sender=SENDER,
                text="Das ist nicht Herr Schnitt, sondern Schmidt",
                quote_target_timestamp=1_234_567_890,
            )
        )
    assert mock_rev.call_args.kwargs["history"] == []


def test_revision_stores_correction_in_history(orc: Orchestrator, channel: MemoryChannel) -> None:
    """Nach einer Korrektur trägt der neue Vorschlag die Korrektur als Historien-Turn."""
    _prime_pending(orc, channel)
    with patch("kollege.orchestrator.run_revision", return_value=_result_revised()):
        orc.handle_message(
            IncomingMessage(
                sender=SENDER,
                text="Das ist nicht Herr Schnitt, sondern Schmidt",
                quote_target_timestamp=1_234_567_890,
            )
        )
    assert orc._pending[SENDER].history == [
        ("Korrektur", "Das ist nicht Herr Schnitt, sondern Schmidt")
    ]


def test_second_revision_receives_first_correction_as_history(
    orc: Orchestrator, channel: MemoryChannel
) -> None:
    """Eine zweite Korrektur-Runde bekommt die erste Korrektur als history mitgegeben —
    das behebt genau den Live-Fall aus 8.14 (Referenz auf »die letzte Nachricht«)."""
    _prime_pending(orc, channel)
    with patch("kollege.orchestrator.run_revision", return_value=_result_revised()):
        orc.handle_message(
            IncomingMessage(
                sender=SENDER,
                text="Seine Nummer ist übrigens 08031/12345.",
                quote_target_timestamp=1_111_111_111,
            )
        )

    with patch("kollege.orchestrator.run_revision", return_value=_result_revised()) as mock_rev:
        orc.handle_message(
            IncomingMessage(
                sender=SENDER,
                text="Trag zusätzlich die Nummer ein, wie eben gesagt.",
                quote_target_timestamp=2_222_222_222,
            )
        )
    assert mock_rev.call_args.kwargs["history"] == [
        ("Korrektur", "Seine Nummer ist übrigens 08031/12345.")
    ]
    assert orc._pending[SENDER].history == [
        ("Korrektur", "Seine Nummer ist übrigens 08031/12345."),
        ("Korrektur", "Trag zusätzlich die Nummer ein, wie eben gesagt."),
    ]


def test_revision_after_resolved_clarification_carries_qa_history(
    orc: Orchestrator, channel: MemoryChannel
) -> None:
    """Eine Korrektur auf einen aus einer Rückfrage entstandenen Vorschlag bekommt die
    Rückfrage+Antwort-Runde als Historie mit — die Interaktion umfasst beides."""
    _prime_clarification(orc, channel)
    with patch("kollege.orchestrator.run_clarification_response", return_value=_result_task()):
        orc.handle_message(IncomingMessage(sender=SENDER, text="Ja, als Dienstleister"))
    channel.sent.clear()

    with patch("kollege.orchestrator.run_revision", return_value=_result_revised()) as mock_rev:
        orc.handle_message(
            IncomingMessage(
                sender=SENDER,
                text="Nicht Müller, sondern Schmidt",
                quote_target_timestamp=3_333_333_333,
            )
        )
    assert mock_rev.call_args.kwargs["history"] == [
        ("Rückfrage", "Welches Projekt meinst du?"),
        ("Antwort", "Ja, als Dienstleister"),
    ]


def test_revision_keeps_prior_completions(orc: Orchestrator, channel: MemoryChannel) -> None:
    """Regression (Schritt 8.20): Eine Korrektur, die eine Erledigung ergänzt, lässt die
    bereits im Vorschlag erkannten Erledigungen unangetastet.

    Statt ``run_revision`` zu mocken, läuft hier der echte Revisions-Pfad gegen ein
    FunctionModel, das nur die im Prompt sichtbaren Aufgaben-IDs zurückgibt ('treues'
    Modell). Ohne den Fix fehlten die bereits erkannten Erledigungen im Prompt und
    gingen verloren; mit dem Fix stehen sie dort und bleiben erhalten.
    """
    import re

    from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    from kollege.models import ExtractedCompletion

    # Vorschlag mit zwei erkannten Erledigungen in den Pending-State bringen.
    primed = ExtractionResult(
        completed=[
            ExtractedCompletion(task_id=6, task_title="Plan finalisieren"),
            ExtractedCompletion(task_id=7, task_title="Stauden prüfen"),
        ]
    )
    with patch("kollege.orchestrator.run_extraction", return_value=primed):
        orc.handle_message(IncomingMessage(sender=SENDER, text="Mehrere Aufgaben erledigt."))
    channel.sent.clear()

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

    with patch("kollege.agent.build_model", return_value=FunctionModel(fn)):
        orc.handle_message(
            IncomingMessage(
                sender=SENDER,
                text="Du hast eine vergessen: Aufgabe #8 ist auch erledigt.",
                quote_target_timestamp=1_234_567_890,
            )
        )

    assert SENDER in orc._pending
    assert {c.task_id for c in orc._pending[SENDER].result.completed} == {6, 7, 8}


# ---------------------------------------------------------------------------
# Deutsche Slash-Commands (Schritt 8.15) — deterministische DB-Abfragen ohne LLM
# ---------------------------------------------------------------------------


def test_format_open_tasks_empty() -> None:
    assert format_open_tasks([]) == "Keine offenen Aufgaben."


def test_format_open_tasks_shows_id_title_due() -> None:
    text = format_open_tasks([Task(id=3, title="Zaun streichen", due=datetime.date(2026, 7, 5))])
    assert text == "#3 Zaun streichen, fällig: So. 5. Juli 2026"  # deutsche Anzeige (8.18)


def test_format_contacts_empty() -> None:
    assert format_contacts([]) == "Keine Kontakte gespeichert."


def test_format_projects_empty() -> None:
    assert format_projects([]) == "Keine Projekte gespeichert."


def test_command_offen_lists_open_tasks(
    orc: Orchestrator, channel: MemoryChannel, repo: Repository
) -> None:
    repo.create_task(Task(title="Rasen mähen"))
    orc.handle_message(IncomingMessage(sender=SENDER, text="/offen"))
    assert len(channel.sent) == 1
    assert "Rasen mähen" in channel.sent[0][1]


def test_command_offen_no_tasks(orc: Orchestrator, channel: MemoryChannel) -> None:
    orc.handle_message(IncomingMessage(sender=SENDER, text="/offen"))
    assert channel.sent[0][1] == "Keine offenen Aufgaben."


def test_command_dringend_sorts_overdue_first(
    orc: Orchestrator, channel: MemoryChannel, repo: Repository
) -> None:
    repo.create_task(Task(title="Ohne Datum"))
    repo.create_task(Task(title="Später", due=datetime.date(2026, 12, 1)))
    repo.create_task(Task(title="Überfällig", due=datetime.date(2026, 1, 1)))

    orc.handle_message(IncomingMessage(sender=SENDER, text="/dringend"))

    text = channel.sent[0][1]
    assert text.index("Überfällig") < text.index("Später") < text.index("Ohne Datum")


def test_command_kontakte_lists_contacts(
    orc: Orchestrator, channel: MemoryChannel, repo: Repository
) -> None:
    repo.upsert_contact(ExtractedContact(name="Familie Müller"))
    orc.handle_message(IncomingMessage(sender=SENDER, text="/kontakte"))
    assert "Familie Müller" in channel.sent[0][1]


def test_command_projekte_lists_projects(
    orc: Orchestrator, channel: MemoryChannel, repo: Repository
) -> None:
    repo.get_or_create_project("Kräutergarten Aibling")
    orc.handle_message(IncomingMessage(sender=SENDER, text="/projekte"))
    assert "Kräutergarten Aibling" in channel.sent[0][1]


def test_command_erledigt_closes_exactly_one_task(
    orc: Orchestrator, channel: MemoryChannel, repo: Repository
) -> None:
    t1 = repo.create_task(Task(title="Aufgabe 1"))
    t2 = repo.create_task(Task(title="Aufgabe 2"))
    assert t1.id is not None

    orc.handle_message(IncomingMessage(sender=SENDER, text=f"/erledigt {t1.id}"))

    assert "erledigt" in channel.sent[0][1].lower()
    open_tasks = repo.query_open_items()
    assert len(open_tasks) == 1
    assert open_tasks[0].id == t2.id


def test_command_erledigt_unknown_id_gives_friendly_message(
    orc: Orchestrator, channel: MemoryChannel
) -> None:
    orc.handle_message(IncomingMessage(sender=SENDER, text="/erledigt 999"))
    assert "999" in channel.sent[0][1]
    assert "gefunden" in channel.sent[0][1].lower()


def test_command_erledigt_without_id_shows_usage_hint(
    orc: Orchestrator, channel: MemoryChannel
) -> None:
    orc.handle_message(IncomingMessage(sender=SENDER, text="/erledigt"))
    assert "id" in channel.sent[0][1].lower()


def test_command_hilfe_lists_all_commands(orc: Orchestrator, channel: MemoryChannel) -> None:
    orc.handle_message(IncomingMessage(sender=SENDER, text="/hilfe"))
    text = channel.sent[0][1]
    for cmd in (
        "/offen",
        "/dringend",
        "/kontakte",
        "/projekte",
        "/erledigt",
        "/loeschen",
        "/zuruecksetzen",
        "/hilfe",
    ):
        assert cmd in text


def test_unknown_command_gives_friendly_hint_and_help(
    orc: Orchestrator, channel: MemoryChannel
) -> None:
    orc.handle_message(IncomingMessage(sender=SENDER, text="/foobar"))
    text = channel.sent[0][1]
    assert "/foobar" in text
    assert "/hilfe" in text


def test_command_is_case_insensitive(
    orc: Orchestrator, channel: MemoryChannel, repo: Repository
) -> None:
    orc.handle_message(IncomingMessage(sender=SENDER, text="/OFFEN"))
    assert channel.sent[0][1] == "Keine offenen Aufgaben."


def test_command_takes_priority_over_open_proposal(
    orc: Orchestrator, channel: MemoryChannel, repo: Repository
) -> None:
    """Ein Kommando wird sofort ausgeführt, ohne den offenen Vorschlag zu berühren."""
    _prime_pending(orc, channel)
    channel.sent.clear()

    orc.handle_message(IncomingMessage(sender=SENDER, text="/offen"))

    assert channel.sent[0][1] == "Keine offenen Aufgaben."
    assert SENDER in orc._pending  # Vorschlag bleibt unangetastet


def test_command_takes_priority_over_open_clarification(
    orc: Orchestrator, channel: MemoryChannel
) -> None:
    """Ein Kommando wird auch bei offener Rückfrage sofort ausgeführt."""
    _prime_clarification(orc, channel)
    channel.sent.clear()

    orc.handle_message(IncomingMessage(sender=SENDER, text="/hilfe"))

    assert "/hilfe" in channel.sent[0][1]
    assert SENDER in orc._pending_clarifications  # Rückfrage bleibt unangetastet


def test_plain_text_starting_without_slash_is_not_a_command(
    orc: Orchestrator, channel: MemoryChannel
) -> None:
    """Regressionstest: normale Notizen laufen weiterhin über die Extraktion."""
    with patch("kollege.orchestrator.run_extraction", return_value=_result_task()):
        orc.handle_message(IncomingMessage(sender=SENDER, text="Ruf bei Müller an"))
    assert SENDER in orc._pending


# ---------------------------------------------------------------------------
# Löschen von Einträgen (Schritt 8.22)
# ---------------------------------------------------------------------------


def test_command_loeschen_kontakt_shows_preview_and_waits_for_confirmation(
    orc: Orchestrator, channel: MemoryChannel, repo: Repository
) -> None:
    contact = repo.upsert_contact(ExtractedContact(name="Familie Müller"))
    assert contact.id is not None

    orc.handle_message(IncomingMessage(sender=SENDER, text=f"/loeschen kontakt {contact.id}"))

    text = channel.sent[0][1]
    assert "Familie Müller" in text
    assert "löschen" in text.lower()
    assert SENDER in orc._pending_deletions
    assert repo.get_contact_by_name("Familie Müller") is not None  # noch nicht gelöscht


def test_command_loeschen_kontakt_unknown_id_gives_friendly_message(
    orc: Orchestrator, channel: MemoryChannel
) -> None:
    orc.handle_message(IncomingMessage(sender=SENDER, text="/loeschen kontakt 999"))
    text = channel.sent[0][1]
    assert "999" in text
    assert "gefunden" in text.lower()
    assert SENDER not in orc._pending_deletions


def test_command_loeschen_without_valid_args_shows_usage_hint(
    orc: Orchestrator, channel: MemoryChannel
) -> None:
    orc.handle_message(IncomingMessage(sender=SENDER, text="/loeschen"))
    text = channel.sent[0][1]
    assert "loeschen" in text.lower()
    assert SENDER not in orc._pending_deletions


def test_command_loeschen_projekt_preview_mentions_task_count(
    orc: Orchestrator, channel: MemoryChannel, repo: Repository
) -> None:
    project = repo.get_or_create_project("Kräutergarten")
    assert project.id is not None
    repo.create_task(Task(title="Beete anlegen", project_id=project.id))
    repo.create_task(Task(title="Kräuter kaufen", project_id=project.id))

    orc.handle_message(IncomingMessage(sender=SENDER, text=f"/loeschen projekt {project.id}"))

    text = channel.sent[0][1]
    assert "Kräutergarten" in text
    assert "2" in text


def test_command_loeschen_aufgabe_unknown_id_gives_friendly_message(
    orc: Orchestrator, channel: MemoryChannel
) -> None:
    orc.handle_message(IncomingMessage(sender=SENDER, text="/loeschen aufgabe 999"))
    text = channel.sent[0][1]
    assert "999" in text
    assert "gefunden" in text.lower()


def test_confirm_loeschen_kontakt_deletes_it(
    orc: Orchestrator, channel: MemoryChannel, repo: Repository
) -> None:
    contact = repo.upsert_contact(ExtractedContact(name="Familie Müller"))
    assert contact.id is not None
    orc.handle_message(IncomingMessage(sender=SENDER, text=f"/loeschen kontakt {contact.id}"))
    channel.sent.clear()

    orc.handle_message(IncomingMessage(sender=SENDER, text="ja"))

    assert SENDER not in orc._pending_deletions
    assert repo.get_contact_by_name("Familie Müller") is None
    assert "✅" in channel.sent[0][1]


def test_confirm_loeschen_projekt_cascades_tasks(
    orc: Orchestrator, channel: MemoryChannel, repo: Repository
) -> None:
    project = repo.get_or_create_project("Kräutergarten")
    assert project.id is not None
    task = repo.create_task(Task(title="Beete anlegen", project_id=project.id))
    assert task.id is not None
    orc.handle_message(IncomingMessage(sender=SENDER, text=f"/loeschen projekt {project.id}"))
    channel.sent.clear()

    orc.handle_message(IncomingMessage(sender=SENDER, text="👍", is_reaction=True))

    assert repo.get_task_by_id(task.id) is None


def test_confirm_loeschen_aufgabe_deletes_task(
    orc: Orchestrator, channel: MemoryChannel, repo: Repository
) -> None:
    task = repo.create_task(Task(title="Weg damit"))
    assert task.id is not None
    orc.handle_message(IncomingMessage(sender=SENDER, text=f"/loeschen aufgabe {task.id}"))
    channel.sent.clear()

    orc.handle_message(IncomingMessage(sender=SENDER, text="ja"))

    assert repo.get_task_by_id(task.id) is None


def test_reject_loeschen_nein_keeps_entry(
    orc: Orchestrator, channel: MemoryChannel, repo: Repository
) -> None:
    contact = repo.upsert_contact(ExtractedContact(name="Familie Müller"))
    assert contact.id is not None
    orc.handle_message(IncomingMessage(sender=SENDER, text=f"/loeschen kontakt {contact.id}"))
    channel.sent.clear()

    orc.handle_message(IncomingMessage(sender=SENDER, text="nein"))

    assert SENDER not in orc._pending_deletions
    assert "Verworfen" in channel.sent[0][1]
    assert repo.get_contact_by_name("Familie Müller") is not None


def test_loeschen_thumbsdown_rejects(
    orc: Orchestrator, channel: MemoryChannel, repo: Repository
) -> None:
    task = repo.create_task(Task(title="Bleib bitte"))
    assert task.id is not None
    orc.handle_message(IncomingMessage(sender=SENDER, text=f"/loeschen aufgabe {task.id}"))
    channel.sent.clear()

    orc.handle_message(IncomingMessage(sender=SENDER, text="👎", is_reaction=True))

    assert SENDER not in orc._pending_deletions
    assert repo.get_task_by_id(task.id) is not None


def test_confirm_loeschen_race_already_gone_gives_friendly_message(
    orc: Orchestrator, channel: MemoryChannel, repo: Repository
) -> None:
    """Zwischen Vorschau und Bestätigung anderweitig gelöscht → freundliche Meldung,
    kein Absturz (analog zum Race-Handling in ``persist_result``)."""
    task = repo.create_task(Task(title="Wird zwischendurch gelöscht"))
    assert task.id is not None
    orc.handle_message(IncomingMessage(sender=SENDER, text=f"/loeschen aufgabe {task.id}"))
    channel.sent.clear()
    repo.delete_task(task.id)

    orc.handle_message(IncomingMessage(sender=SENDER, text="ja"))

    assert SENDER not in orc._pending_deletions
    assert "nicht mehr vorhanden" in channel.sent[0][1]


def test_command_zuruecksetzen_shows_totals_and_waits_for_confirmation(
    orc: Orchestrator, channel: MemoryChannel, repo: Repository
) -> None:
    repo.upsert_contact(ExtractedContact(name="Familie Müller"))
    repo.get_or_create_project("Kräutergarten")
    repo.create_task(Task(title="Beete anlegen"))

    orc.handle_message(IncomingMessage(sender=SENDER, text="/zuruecksetzen"))

    text = channel.sent[0][1]
    assert "1 Kontakt" in text
    assert "1 Projekt" in text
    assert "1 Aufgabe" in text
    assert SENDER in orc._pending_deletions


def test_command_zuruecksetzen_on_empty_db_gives_message_without_pending(
    orc: Orchestrator, channel: MemoryChannel
) -> None:
    orc.handle_message(IncomingMessage(sender=SENDER, text="/zuruecksetzen"))
    assert SENDER not in orc._pending_deletions
    assert "nichts gespeichert" in channel.sent[0][1].lower()


def test_confirm_zuruecksetzen_clears_everything(
    orc: Orchestrator, channel: MemoryChannel, repo: Repository
) -> None:
    repo.upsert_contact(ExtractedContact(name="Familie Müller"))
    repo.get_or_create_project("Kräutergarten")
    repo.create_task(Task(title="Beete anlegen"))
    orc.handle_message(IncomingMessage(sender=SENDER, text="/zuruecksetzen"))
    channel.sent.clear()

    orc.handle_message(IncomingMessage(sender=SENDER, text="ja"))

    assert repo.get_all_contacts() == []
    assert repo.get_all_projects() == []
    assert repo.get_all_tasks() == []
    assert "✅" in channel.sent[0][1]


def test_loeschen_command_discards_open_proposal(
    orc: Orchestrator, channel: MemoryChannel, repo: Repository
) -> None:
    """Ein Lösch-Command verwirft einen offenen Vorschlag — nie zwei Dialoge gleichzeitig."""
    task = repo.create_task(Task(title="Zu löschen"))
    assert task.id is not None
    _prime_pending(orc, channel)
    assert SENDER in orc._pending

    orc.handle_message(IncomingMessage(sender=SENDER, text=f"/loeschen aufgabe {task.id}"))

    assert SENDER not in orc._pending
    assert SENDER in orc._pending_deletions


def test_loeschen_command_discards_open_clarification(
    orc: Orchestrator, channel: MemoryChannel, repo: Repository
) -> None:
    task = repo.create_task(Task(title="Zu löschen"))
    assert task.id is not None
    _prime_clarification(orc, channel)
    assert SENDER in orc._pending_clarifications

    orc.handle_message(IncomingMessage(sender=SENDER, text=f"/loeschen aufgabe {task.id}"))

    assert SENDER not in orc._pending_clarifications
    assert SENDER in orc._pending_deletions


def test_new_note_while_pending_deletion_drops_it(
    orc: Orchestrator, channel: MemoryChannel, repo: Repository
) -> None:
    """Eine neue Notiz (kein ja/nein) beendet eine noch unbeantwortete Lösch-Bestätigung."""
    task = repo.create_task(Task(title="Zu löschen"))
    assert task.id is not None
    orc.handle_message(IncomingMessage(sender=SENDER, text=f"/loeschen aufgabe {task.id}"))
    assert SENDER in orc._pending_deletions

    with patch("kollege.orchestrator.run_extraction", return_value=_result_task()):
        orc.handle_message(IncomingMessage(sender=SENDER, text="Neue Notiz"))

    assert SENDER not in orc._pending_deletions
    assert repo.get_task_by_id(task.id) is not None  # nicht versehentlich gelöscht


# ---------------------------------------------------------------------------
# LLM-/Verlaufs-Traces (Schritt 8.21)
# ---------------------------------------------------------------------------


def _read_trace_events(trace_dir: Path) -> list[dict[str, object]]:
    """Alle Ereignisse der heutigen Trace-Datei einlesen (chronologisch)."""
    import datetime
    import json

    today = datetime.datetime.now(tz=datetime.UTC).date().isoformat()
    path = trace_dir / f"{today}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_orchestrator_without_trace_argument_defaults_to_noop(
    channel: MemoryChannel, repo: Repository, settings: Settings, log_dir: Path
) -> None:
    """Ohne ``trace``-Argument läuft der Orchestrator unverändert (Default: Noop)."""
    orchestrator = Orchestrator(
        channel=channel, repo=repo, transcriber=None, settings=settings, log_dir=log_dir
    )
    with patch("kollege.orchestrator.run_extraction", return_value=_result_task()):
        orchestrator.handle_message(IncomingMessage(sender=SENDER, text="Test"))
    assert SENDER in orchestrator._pending


def test_full_thread_writes_orchestrator_trace_events(
    channel: MemoryChannel, repo: Repository, settings: Settings, log_dir: Path, tmp_path: Path
) -> None:
    """Nachricht → Vorschlag → Korrektur → Bestätigung erzeugt eine lesbare
    Trace-Datei mit dem kompletten Faden (Schritt 8.21 DoD).
    """
    from kollege.trace import JsonlTraceWriter

    trace_dir = tmp_path / "traces"
    writer = JsonlTraceWriter(trace_dir)
    orchestrator = Orchestrator(
        channel=channel,
        repo=repo,
        transcriber=None,
        settings=settings,
        log_dir=log_dir,
        trace=writer,
    )

    with patch("kollege.orchestrator.run_extraction", return_value=_result_task()):
        orchestrator.handle_message(IncomingMessage(sender=SENDER, text="Ruf bei Müller an"))

    with patch("kollege.orchestrator.run_revision", return_value=_result_revised()):
        orchestrator.handle_message(
            IncomingMessage(
                sender=SENDER,
                text="Nicht Schnitt, sondern Schmidt",
                quote_target_timestamp=1_234_567_890,
            )
        )

    orchestrator.handle_message(IncomingMessage(sender=SENDER, text="ja"))

    events = _read_trace_events(trace_dir)
    event_names = [e["event"] for e in events]
    # Drei Nachrichten-Zyklen → drei message_received-Ereignisse, mit eigener run_id.
    assert event_names.count("message_received") == 3
    assert "routing" in event_names
    assert event_names.count("proposal_sent") == 2  # Erst-Vorschlag + Korrektur
    assert "confirmed" in event_names
    assert "persisted" in event_names

    run_ids = {e["run_id"] for e in events}
    assert len(run_ids) == 3  # jede Nachricht bekommt eine eigene run_id

    persisted_payload = next(e["payload"] for e in events if e["event"] == "persisted")
    assert persisted_payload["count"] == 1  # type: ignore[index]


def test_rejection_writes_rejected_event(
    channel: MemoryChannel, repo: Repository, settings: Settings, log_dir: Path, tmp_path: Path
) -> None:
    """Ablehnung eines Vorschlags ("nein") schreibt ein ``rejected``-Ereignis."""
    from kollege.trace import JsonlTraceWriter

    trace_dir = tmp_path / "traces"
    writer = JsonlTraceWriter(trace_dir)
    orchestrator = Orchestrator(
        channel=channel,
        repo=repo,
        transcriber=None,
        settings=settings,
        log_dir=log_dir,
        trace=writer,
    )
    with patch("kollege.orchestrator.run_extraction", return_value=_result_task()):
        orchestrator.handle_message(IncomingMessage(sender=SENDER, text="Test"))

    orchestrator.handle_message(IncomingMessage(sender=SENDER, text="nein"))

    events = _read_trace_events(trace_dir)
    assert "rejected" in [e["event"] for e in events]


def test_clarification_writes_clarification_sent_event(
    channel: MemoryChannel, repo: Repository, settings: Settings, log_dir: Path, tmp_path: Path
) -> None:
    """Eine Rückfrage aus der Extraktion schreibt ein ``clarification_sent``-Ereignis."""
    from kollege.trace import JsonlTraceWriter

    trace_dir = tmp_path / "traces"
    writer = JsonlTraceWriter(trace_dir)
    orchestrator = Orchestrator(
        channel=channel,
        repo=repo,
        transcriber=None,
        settings=settings,
        log_dir=log_dir,
        trace=writer,
    )
    with patch("kollege.orchestrator.run_extraction", return_value=_result_clarification()):
        orchestrator.handle_message(IncomingMessage(sender=SENDER, text="Unklare Notiz"))

    events = _read_trace_events(trace_dir)
    payload = next(e["payload"] for e in events if e["event"] == "clarification_sent")
    assert payload["frage"] == "Welches Projekt meinst du?"  # type: ignore[index]


def test_error_during_extraction_writes_error_event(
    channel: MemoryChannel, repo: Repository, settings: Settings, log_dir: Path, tmp_path: Path
) -> None:
    """Ein unerwarteter Fehler beim Verarbeiten schreibt ein ``error``-Ereignis
    mit derselben ``run_id`` wie der ``message_received`` der auslösenden Nachricht.
    """
    from kollege.trace import JsonlTraceWriter

    trace_dir = tmp_path / "traces"
    writer = JsonlTraceWriter(trace_dir)
    orchestrator = Orchestrator(
        channel=channel,
        repo=repo,
        transcriber=None,
        settings=settings,
        log_dir=log_dir,
        trace=writer,
        retry_delay=0.0,
    )
    channel.inbox.append(IncomingMessage(sender=SENDER, text="Löst einen Fehler aus"))
    with patch("kollege.orchestrator.run_extraction", side_effect=RuntimeError("kaputt")):
        orchestrator.run_once()

    events = _read_trace_events(trace_dir)
    by_event = {e["event"]: e for e in events}
    assert "error" in by_event
    assert by_event["error"]["run_id"] == by_event["message_received"]["run_id"]
    assert by_event["error"]["payload"]["exception_type"] == "RuntimeError"  # type: ignore[index]
