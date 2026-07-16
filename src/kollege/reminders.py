"""Proaktive Erinnerungen mit konfigurierbarem Zeitplan (Schritt 8.27).

Zwei Nachrichtentypen, je Regel in ``data/reminders.toml`` konfiguriert
(Beispiel: [`docs/reminders.example.toml`](../../docs/reminders.example.toml)):

- ``ping``  — kurze Erinnerung, lädt zur Sprachnotiz ein.
- ``liste`` — formatierte Liste aller offenen Aufgaben.

Der Zeitplan ist **frei konfigurierbar** (Wochentage + Uhrzeit je Regel), ohne
Code anzufassen — die Datei wird bei jedem Tick neu gelesen. Dieses Modul
enthält nur die reine Logik (Regeln laden, Fälligkeit berechnen); Versand und
Repository-Zugriff übernimmt der ``Orchestrator``.

**Verpasste Zeitpunkte** (Laptop schlief): ``due_reminders`` holt höchstens den
**jüngsten** verpassten Zeitpunkt einer Regel nach, nie mehrere gestapelt —
wurde z. B. eine Woche lang nicht gepollt, wird nur die zuletzt fällige
Instanz einer Regel gesendet, ältere verpasste stillschweigend übersprungen.
"""

from __future__ import annotations

import tomllib
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, field_validator

__all__ = [
    "ReminderRule",
    "ReminderType",
    "due_reminders",
    "load_reminder_rules",
]


class ReminderType(StrEnum):
    PING = "ping"
    LISTE = "liste"


# Kurzform-Wochentagscodes (deutsch, ohne Punkt) — Reihenfolge = ISO-Wochentag
# (Montag = 0), analog ``orchestrator._WEEKDAYS_DE_SHORT`` (dort mit Punkt für
# die Datumsanzeige; hier ohne, da es Konfig-Werte statt Fließtext sind).
_WEEKDAY_CODES = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")


class ReminderRule(BaseModel):
    """Eine Zeitplan-Regel aus ``reminders.toml``: Nachrichtentyp + Wann."""

    typ: ReminderType
    wochentage: list[str]
    uhrzeit: time

    @field_validator("wochentage")
    @classmethod
    def _validate_wochentage(cls, value: list[str]) -> list[str]:
        unknown = [w for w in value if w not in _WEEKDAY_CODES]
        if unknown:
            raise ValueError(
                f"Unbekannte Wochentag-Kürzel {unknown} — gültig sind {_WEEKDAY_CODES}"
            )
        if not value:
            raise ValueError("wochentage darf nicht leer sein")
        return value

    def key(self) -> str:
        """Stabiler Bezeichner der Regel — Persistenz-Schlüssel für ``last_sent``.

        Inhaltsbasiert (nicht Listenindex), damit Umsortieren der Regeln in der
        Konfig-Datei keine falsche Zuordnung zu einem gespeicherten Zeitpunkt
        einer *anderen* Regel erzeugt.
        """
        tage = ",".join(sorted(self.wochentage, key=_WEEKDAY_CODES.index))
        return f"{self.typ}:{tage}:{self.uhrzeit.isoformat()}"


def load_reminder_rules(path: Path) -> list[ReminderRule]:
    """Regeln aus einer TOML-Datei laden — ``[[erinnerung]]``-Einträge.

    Fehlt die Datei (z. B. Testphase ohne konfigurierten Zeitplan), gibt es
    schlicht keine Regeln — kein Fehler, keine Erinnerungen versendet.
    """
    if not path.exists():
        return []
    with path.open("rb") as f:
        data = tomllib.load(f)
    return [ReminderRule.model_validate(entry) for entry in data.get("erinnerung", [])]


# Bis zu wie viele Tage zurück nach der jüngsten fälligen Instanz einer Regel
# gesucht wird — deckt "über's Wochenende/eine Woche nicht gelaufen" ab, ohne
# unbegrenzt weit in die Vergangenheit zu suchen.
_LOOKBACK_DAYS = 8


def _most_recent_occurrence(rule: ReminderRule, now: datetime) -> datetime | None:
    """Jüngste geplante Instanz von ``rule`` zum Zeitpunkt <= ``now``, falls vorhanden."""
    for days_back in range(_LOOKBACK_DAYS):
        day: date = now.date() - timedelta(days=days_back)
        if _WEEKDAY_CODES[day.weekday()] not in rule.wochentage:
            continue
        candidate = datetime.combine(day, rule.uhrzeit)
        if candidate <= now:
            return candidate
    return None


def due_reminders(
    rules: list[ReminderRule], now: datetime, last_sent: dict[str, datetime]
) -> list[tuple[ReminderRule, datetime]]:
    """Regeln ermitteln, die jetzt (oder nachzuholen) fällig sind.

    ``last_sent`` bildet ``rule.key()`` auf den zuletzt tatsächlich versendeten
    Zeitpunkt ab (aus dem Repository, Neustart-sicher). Eine Regel ist fällig,
    wenn ihre jüngste geplante Instanz <= ``now`` noch nicht (oder für eine
    frühere Instanz) versendet wurde. Ergebnis enthält je Regel den Zeitpunkt,
    der als ``last_sent`` vermerkt werden soll.
    """
    due: list[tuple[ReminderRule, datetime]] = []
    for rule in rules:
        occurrence = _most_recent_occurrence(rule, now)
        if occurrence is None:
            continue
        prior = last_sent.get(rule.key())
        if prior is None or prior < occurrence:
            due.append((rule, occurrence))
    return due
