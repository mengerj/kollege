"""Tests für Schritt 8.27 — Regel-Modell, TOML-Loader, Fällig-Berechnung.

Reine Logik ohne Repository/Channel (die Verdrahtung testet
``test_orchestrator.py`` bzw. eine eigene Reminder-Sektion dort).
"""

from __future__ import annotations

from datetime import datetime, time
from pathlib import Path

import pytest
from pydantic import ValidationError

from kollege.reminders import ReminderRule, ReminderType, due_reminders, load_reminder_rules

# ---------------------------------------------------------------------------
# ReminderRule
# ---------------------------------------------------------------------------


def test_reminder_rule_valid_construction() -> None:
    rule = ReminderRule(typ=ReminderType.PING, wochentage=["Mo", "Fr"], uhrzeit=time(8, 0))
    assert rule.typ == ReminderType.PING
    assert rule.wochentage == ["Mo", "Fr"]


def test_reminder_rule_rejects_unknown_weekday() -> None:
    with pytest.raises(ValidationError):
        ReminderRule(typ="ping", wochentage=["Montag"], uhrzeit=time(8, 0))


def test_reminder_rule_rejects_empty_weekdays() -> None:
    with pytest.raises(ValidationError):
        ReminderRule(typ="ping", wochentage=[], uhrzeit=time(8, 0))


def test_reminder_rule_key_stable_regardless_of_weekday_order() -> None:
    a = ReminderRule(typ=ReminderType.PING, wochentage=["Fr", "Mo"], uhrzeit=time(8, 0))
    b = ReminderRule(typ=ReminderType.PING, wochentage=["Mo", "Fr"], uhrzeit=time(8, 0))
    assert a.key() == b.key()


def test_reminder_rule_key_differs_by_typ_or_uhrzeit() -> None:
    ping = ReminderRule(typ=ReminderType.PING, wochentage=["Mo"], uhrzeit=time(8, 0))
    liste = ReminderRule(typ=ReminderType.LISTE, wochentage=["Mo"], uhrzeit=time(8, 0))
    later = ReminderRule(typ=ReminderType.PING, wochentage=["Mo"], uhrzeit=time(18, 0))
    assert ping.key() != liste.key()
    assert ping.key() != later.key()


# ---------------------------------------------------------------------------
# load_reminder_rules
# ---------------------------------------------------------------------------


def test_load_reminder_rules_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_reminder_rules(tmp_path / "nicht_da.toml") == []


def test_load_reminder_rules_parses_entries(tmp_path: Path) -> None:
    config = tmp_path / "reminders.toml"
    config.write_text(
        """
        [[erinnerung]]
        typ = "ping"
        wochentage = ["Mo", "Fr"]
        uhrzeit = "08:00"

        [[erinnerung]]
        typ = "liste"
        wochentage = ["Mo", "Fr"]
        uhrzeit = "18:00"
        """,
        encoding="utf-8",
    )
    rules = load_reminder_rules(config)
    assert len(rules) == 2
    assert rules[0].typ == ReminderType.PING
    assert rules[0].uhrzeit == time(8, 0)
    assert rules[1].typ == ReminderType.LISTE


def test_load_reminder_rules_empty_file_returns_empty(tmp_path: Path) -> None:
    config = tmp_path / "reminders.toml"
    config.write_text("", encoding="utf-8")
    assert load_reminder_rules(config) == []


# ---------------------------------------------------------------------------
# due_reminders — Fällig-Berechnung inkl. Nachhol-Logik
# ---------------------------------------------------------------------------

# 2026-07-13 ist ein Montag.
_MONDAY = datetime(2026, 7, 13)
_FRIDAY = datetime(2026, 7, 17)


def _rule(
    typ: ReminderType = ReminderType.PING, wochentage: list[str] | None = None
) -> ReminderRule:
    return ReminderRule(typ=typ, wochentage=wochentage or ["Mo", "Fr"], uhrzeit=time(8, 0))


def test_due_reminders_fires_exactly_at_scheduled_time() -> None:
    rule = _rule()
    now = _MONDAY.replace(hour=8, minute=0)
    result = due_reminders([rule], now, last_sent={})
    assert result == [(rule, now)]


def test_due_reminders_not_due_before_scheduled_time_same_day() -> None:
    rule = _rule()
    now = _MONDAY.replace(hour=7, minute=59)
    # Vorwoche (Freitag) liegt weiter zurück als 8 Tage? nein — genau 5 Tage,
    # also wird der Freitag der Vorwoche als jüngste Instanz gefunden.
    result = due_reminders([rule], now, last_sent={})
    assert len(result) == 1
    occurrence = result[0][1]
    assert occurrence < now
    assert occurrence.date() < _MONDAY.date()


def test_due_reminders_not_due_on_non_matching_weekday() -> None:
    rule = _rule(wochentage=["Di", "Mi", "Do"])
    now = _MONDAY.replace(hour=14, minute=0)
    result = due_reminders([rule], now, last_sent={})
    # jüngste Instanz ist der Donnerstag der Vorwoche, nicht "nicht fällig"
    assert len(result) == 1
    assert result[0][1].date() < _MONDAY.date()


def test_due_reminders_skips_already_sent_occurrence() -> None:
    rule = _rule()
    now = _MONDAY.replace(hour=8, minute=0)
    last_sent = {rule.key(): now}
    assert due_reminders([rule], now, last_sent) == []


def test_due_reminders_fires_again_next_scheduled_occurrence() -> None:
    rule = _rule()
    monday_occurrence = _MONDAY.replace(hour=8, minute=0)
    last_sent = {rule.key(): monday_occurrence}
    friday_now = _FRIDAY.replace(hour=8, minute=0)
    result = due_reminders([rule], friday_now, last_sent)
    assert result == [(rule, friday_now)]


def test_due_reminders_catches_up_at_most_the_most_recent_missed_occurrence() -> None:
    """Laptop schlief eine Woche — nur die jüngste verpasste Instanz wird nachgeholt."""
    rule = _rule()
    two_mondays_ago = datetime(2026, 6, 29, 8, 0)  # vor > 8 Tagen, außerhalb Lookback
    last_sent = {rule.key(): two_mondays_ago}
    # "Jetzt" ist Freitagabend — mehrere Instanzen wurden zwischenzeitlich verpasst.
    now = _FRIDAY.replace(hour=20, minute=0)
    result = due_reminders([rule], now, last_sent)
    assert len(result) == 1
    _, occurrence = result[0]
    # Nur der Freitag (jüngste), nicht auch noch der Montag derselben Woche.
    assert occurrence == _FRIDAY.replace(hour=8, minute=0)


def test_due_reminders_multiple_rules_independent() -> None:
    ping = _rule(typ=ReminderType.PING)
    liste = _rule(typ=ReminderType.LISTE)
    now = _MONDAY.replace(hour=8, minute=0)
    last_sent = {ping.key(): now}  # ping schon versendet, liste noch nicht
    result = due_reminders([ping, liste], now, last_sent)
    assert result == [(liste, now)]


def test_due_reminders_empty_rules_returns_empty() -> None:
    assert due_reminders([], _MONDAY, {}) == []
