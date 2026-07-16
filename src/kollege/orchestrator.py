"""Orchestrator: verdrahtet Channel → Transcriber → Agent → Repo → Bestätigung.

Ablauf:
1. Nachricht empfangen (Text oder Audio).
2. Audio → Transkript (Transcriber).
3. Transkript → ExtractionResult (Agent, temporäres In-Memory-Repo — kein echter DB-Schreibzugriff).
4. Vorschlag formatieren und an Nutzer senden.
5. Bestätigung (👍 / "ja") → Persistenz im echten Repo.
   Ablehnung (👎 / "nein") → verwerfen.
   Zahlenauswahl ("1 3") → nur gewählte Einträge übernehmen.

Bei Unklarheit stellt der Agent eine Rückfrage (``clarification``) statt zu raten.
Die nächste Nachricht (Text, Sprache oder 👍-Tapback) gilt als Antwort darauf und
wird mit dem Ursprungstranskript neu extrahiert (Rückfrage-Antwort-Schleife).

Pending-State: pro Absender (Rufnummer) genau *ein* offener Zustand im
Arbeitsspeicher — ein ``PendingProposal`` (wartet auf Bestätigung), eine
``PendingClarification`` (wartet auf Antwort) oder eine ``PendingDeletion``
(wartet auf Lösch-Bestätigung, Schritt 8.22), nie mehr als einer gleichzeitig.
``PendingProposal``/``PendingClarification`` führen ein ``history``-Feld: alle
vorangegangenen Turns derselben Interaktion (Rückfragen, Antworten, Korrekturen),
damit Referenzen wie »wie in der letzten Nachricht« über mehrere Runden hinweg
auflösbar bleiben (Schritt 8.14). Die Historie ist strikt an eine laufende
Interaktion gebunden und wird bei Bestätigung/Ablehnung verworfen — kein
senderweites Dauergedächtnis.

Dispatcher-Reihenfolge in ``handle_message`` (Schritt 8.15): Slash-Command? →
offene Lösch-Bestätigung/offener Vorschlag/Rückfrage? → sonst neue Notiz.
Deutsche Kommandos (``/offen``, ``/dringend``, ``/kontakte``, ``/projekte``,
``/erledigt <id>``, ``/loeschen kontakt|projekt|aufgabe <id>``,
``/zuruecksetzen``, ``/hilfe``) fragen den DB-Stand deterministisch ab — ohne
LLM, unabhängig von einem etwaig offenen Vorschlag/einer Rückfrage. Die
destruktiven Lösch-Commands sind eine Ausnahme: sie legen selbst einen neuen
Pending-Zustand an und verwerfen dafür einen etwaig offenen Vorschlag/eine
offene Rückfrage desselben Absenders (Prinzip 3 — nie ohne Bestätigung löschen,
aber auch nie zwei Bestätigungs-Dialoge gleichzeitig offen).
"""

from __future__ import annotations

import contextlib
import logging
import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from kollege.agent import (
    get_known_names_context,
    get_open_tasks_context,
    run_clarification_response,
    run_extraction,
    run_gap_check,
    run_revision,
)
from kollege.channels import Channel, IncomingMessage
from kollege.config import Settings
from kollege.db import Repository
from kollege.logs import open_project_log
from kollege.models import (
    Contact,
    ExtractedCompletion,
    ExtractedContact,
    ExtractedOrt,
    ExtractedProjectUpdate,
    ExtractedTask,
    ExtractedTaskEdit,
    ExtractionResult,
    Ort,
    Project,
    Task,
    TaskSource,
    TaskStatus,
)
from kollege.trace import NoopTraceWriter, TraceWriter, new_run_id
from kollege.transcription import Transcriber

__all__ = [
    "Orchestrator",
    "PendingClarification",
    "PendingDeletion",
    "PendingProposal",
    "PersistSummary",
    "dedupe_result",
    "format_contacts",
    "format_date_de",
    "format_open_tasks",
    "format_orte",
    "format_projects",
    "format_proposal",
    "persist_result",
]

logger = logging.getLogger("kollege.orchestrator")

# ---------------------------------------------------------------------------
# Datumsanzeige für die Nutzerin (deutsch): "Do. 2. Juli 2026"
# ---------------------------------------------------------------------------
# Intern/gegenüber dem LLM bleibt ISO (YYYY-MM-DD); nur die an die Nutzerin
# gesendeten Texte und die Markdown-Logs nutzen diese lesbare Form.

_WEEKDAYS_DE_SHORT = ("Mo.", "Di.", "Mi.", "Do.", "Fr.", "Sa.", "So.")
_MONTHS_DE = (
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
)


def format_date_de(d: date) -> str:
    """Datum menschenlesbar auf Deutsch: Wochentag + Tag, Monat, Jahr.

    Beispiel: ``date(2026, 7, 2)`` → ``"Do. 2. Juli 2026"``. Ohne führende Null
    beim Tag. Verwendet für alle an die Nutzerin gesendeten Fälligkeiten.
    """
    return f"{_WEEKDAYS_DE_SHORT[d.weekday()]} {d.day}. {_MONTHS_DE[d.month - 1]} {d.year}"


# ---------------------------------------------------------------------------
# Typalias für die drei möglichen Extraktionsobjekte
# ---------------------------------------------------------------------------

_Item = (
    ExtractedContact
    | ExtractedTask
    | ExtractedProjectUpdate
    | ExtractedCompletion
    | ExtractedTaskEdit
    | ExtractedOrt
)

# ---------------------------------------------------------------------------
# Regex für Nutzereingaben im Bestätigungs-Dialog
# ---------------------------------------------------------------------------

_YES = re.compile(r"^\s*(ja|yes|👍|bestätigen?|ok|okay|passt)\s*$", re.IGNORECASE)
_NO = re.compile(r"^\s*(nein|no|abbrechen?|verwerfen?|cancel)\s*$", re.IGNORECASE)
_NUMS = re.compile(r"^[\d\s,]+$")

# Emoji-Modifikatoren, die einem Basis-Emoji folgen können: Variation Selectors
# (U+FE0E/U+FE0F) und Hautton-Modifier (U+1F3FB–U+1F3FF). Für den Vergleich
# entfernt, damit 👍, 👍️ und 👍🏼 identisch behandelt werden — je nach Signal-
# Client kommt der Tapback in unterschiedlichen Kodierungen an.
_EMOJI_MODIFIERS = re.compile(r"[\ufe0e\ufe0f\U0001f3fb-\U0001f3ff]")

# Tapback-Emojis, die als Zustimmung ("ja") gelten.
_AFFIRMATIVE_EMOJIS = frozenset({"👍", "👌", "✅", "🆗"})
# Tapback-Emojis, die als Ablehnung ("nein") gelten.
_NEGATIVE_EMOJIS = frozenset({"👎", "❌", "🚫"})


def _emoji_base(emoji: str) -> str:
    """Emoji auf seinen Basis-Codepoint reduzieren (Modifier/Selektoren entfernen)."""
    return _EMOJI_MODIFIERS.sub("", emoji).strip()


def _is_affirmative_reaction(emoji: str | None) -> bool:
    """True, wenn das Tapback-Emoji als Zustimmung zu werten ist (robust ggü. Varianten)."""
    if not emoji:
        return False
    return _emoji_base(emoji) in _AFFIRMATIVE_EMOJIS


def _is_negative_reaction(emoji: str | None) -> bool:
    """True, wenn das Tapback-Emoji als Ablehnung zu werten ist (robust ggü. Varianten)."""
    if not emoji:
        return False
    return _emoji_base(emoji) in _NEGATIVE_EMOJIS


# ---------------------------------------------------------------------------
# Slash-Commands (deutsch) — deterministische DB-Abfragen ohne LLM (Schritt 8.15)
# ---------------------------------------------------------------------------

_COMMAND = re.compile(r"^/(?P<cmd>\S+)\s*(?P<args>.*)$", re.DOTALL)

_HELP_TEXT = (
    "Verfügbare Kommandos:\n"
    "/offen — offene Aufgaben\n"
    "/dringend — offene Aufgaben, überfällige zuerst\n"
    "/kontakte — alle Kontakte\n"
    "/projekte — alle Projekte\n"
    "/orte — alle Örtlichkeiten\n"
    '/erledigt <id> — Aufgabe als erledigt markieren (z.B. "/erledigt 3")\n'
    "/loeschen kontakt|projekt|aufgabe|ort <id> — Eintrag löschen, mit Bestätigung "
    '(z.B. "/loeschen aufgabe 3")\n'
    "/zuruecksetzen — ALLES löschen (Kontakte, Projekte, Aufgaben, Örtlichkeiten), "
    "mit Bestätigung\n"
    "/hilfe — diese Übersicht"
)

# "/loeschen kontakt|projekt|aufgabe|ort <id>" (Schritt 8.22/8.26) — Groß-/
# Kleinschreibung der Entität wie bei allen anderen Kommandos egal.
_LOESCHEN_ARGS = re.compile(r"^(kontakt|projekt|aufgabe|ort)\s+(\d+)$", re.IGNORECASE)
_LOESCHEN_USAGE = (
    'Nutzung: "/loeschen kontakt <id>", "/loeschen projekt <id>", '
    '"/loeschen aufgabe <id>" oder "/loeschen ort <id>" (z.B. "/loeschen aufgabe 3").'
)


def _parse_command(text: str) -> tuple[str, str] | None:
    """Text als Slash-Command parsen: (Kommando ohne "/", kleingeschrieben; Argumente).

    ``None``, wenn der Text nicht mit "/" beginnt (dann ist es eine normale Notiz).
    """
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None
    match = _COMMAND.match(stripped)
    if match is None:
        return None
    return match.group("cmd").lower(), match.group("args").strip()


def format_open_tasks(tasks: list[Task]) -> str:
    """Offene Aufgaben als knappe, ID-beschriftete Liste — für ``/offen``/``/dringend``."""
    if not tasks:
        return "Keine offenen Aufgaben."
    lines = []
    for t in tasks:
        due = f", fällig: {format_date_de(t.due)}" if t.due else ""
        lines.append(f"#{t.id} {t.title}{due}")
    return "\n".join(lines)


def format_contacts(contacts: list[Contact]) -> str:
    """Kontakte als knappe, ID-beschriftete Liste — für ``/kontakte``."""
    if not contacts:
        return "Keine Kontakte gespeichert."
    lines = []
    for c in contacts:
        typ = f" ({c.type})" if c.type else ""
        lines.append(f"#{c.id} {c.name}{typ}")
    return "\n".join(lines)


def format_projects(projects: list[Project]) -> str:
    """Projekte als knappe, ID-beschriftete Liste — für ``/projekte``."""
    if not projects:
        return "Keine Projekte gespeichert."
    lines = [f"#{p.id} {p.title} [{p.status}]" for p in projects]
    return "\n".join(lines)


def format_orte(orte: list[Ort]) -> str:
    """Örtlichkeiten als knappe, ID-beschriftete Liste — für ``/orte``."""
    if not orte:
        return "Keine Örtlichkeiten gespeichert."
    lines = []
    for o in orte:
        details = [d for d in (o.adresse, o.flurnummer and f"Flur {o.flurnummer}") if d]
        suffix = f" ({', '.join(details)})" if details else ""
        lines.append(f"#{o.id} {o.name}{suffix}")
    return "\n".join(lines)


# Anzahl Versuche und Standard-Wartezeit (Sekunden) bei transienten Extraktionsfehlern.
# Transient = Ollama/Whisper/Container kurzfristig nicht erreichbar.
# Standard 10 s Wartezeit; in Tests über retry_delay=0.0 übersteuern.
_EXTRACTION_RETRIES = 3
_EXTRACTION_RETRY_DELAY = 10.0


def _now() -> datetime:
    return datetime.now(tz=UTC)


# ---------------------------------------------------------------------------
# PendingProposal — zwischengespeicherter Vorschlag bis zur Bestätigung
# ---------------------------------------------------------------------------


@dataclass
class PendingProposal:
    """Ausstehendes Extraktionsergebnis, das auf Nutzerbestätigung wartet."""

    sender: str
    transcript: str
    result: ExtractionResult
    created_at: datetime = field(default_factory=_now)
    sent_timestamp: int | None = None
    """Sende-Timestamp der Vorschlags-Nachricht (von ``channel.send()`` geliefert).
    Ermöglicht zukünftiges Matching von Quote-Reply ``quote.id``-Feldern auf den
    genauen Vorschlag. In Phase-A wird per Sender nur ein Vorschlag offen gehalten,
    daher ist jede Quote-Reply eindeutig — der Timestamp dient als Vorbereitung auf
    Stufe B (Korrektur bereits persistierter Einträge)."""
    history: list[tuple[str, str]] = field(default_factory=list)
    """Frühere Turns *dieser* Interaktion vor dem aktuellen Vorschlag — z. B.
    vorangegangene Korrekturen oder eine Rückfrage+Antwort-Runde, als
    (Label, Text)-Paare in chronologischer Reihenfolge. Wird bei jeder weiteren
    Korrektur an ``run_revision`` mitgegeben, damit Referenzen wie »wie in der
    letzten Nachricht« über mehrere Runden hinweg auflösbar bleiben (Schritt 8.14).
    Enthält *nicht* das Ursprungstranskript (steht in ``transcript``)."""


@dataclass
class PendingClarification:
    """Offene Rückfrage, die auf eine Antwort der Nutzerin wartet.

    Entsteht, wenn die Extraktion unsicher war und ``clarification`` gesetzt hat
    (statt zu raten, Designprinzip 3). Die *nächste* Nachricht der Nutzerin
    (Text, Sprache oder ein 👍-Tapback) wird als Antwort behandelt und mit dem
    Ursprungstranskript neu extrahiert — statt als neue Notiz. Pro Sender ist
    maximal eine Rückfrage *oder* ein Vorschlag offen, nie beides gleichzeitig.
    """

    sender: str
    transcript: str
    question: str
    created_at: datetime = field(default_factory=_now)
    history: list[tuple[str, str]] = field(default_factory=list)
    """Frühere Turns *dieser* Interaktion vor dieser Rückfrage — siehe
    ``PendingProposal.history`` (Schritt 8.14)."""


@dataclass
class PendingDeletion:
    """Ausstehende Lösch-Bestätigung (Schritt 8.22).

    Destruktive Commands (``/loeschen ...``, ``/zuruecksetzen``) löschen nie sofort,
    sondern zeigen zuerst eine Vorschau (``label``: Name/Titel, bei einem Projekt
    inkl. Anzahl mitgelöschter Aufgaben) und warten auf ein explizites 👍/„ja" —
    dieselbe Zwei-Schritt-Bestätigung wie bei ``PendingProposal``, aber ohne
    LLM-Ergebnis: die Aktion selbst (``action``/``target_id``) wird erst bei
    Bestätigung ausgeführt.
    """

    sender: str
    action: str
    """"kontakt" | "projekt" | "aufgabe" | "zuruecksetzen"."""
    target_id: int | None
    """Zu löschende ID; ``None`` nur bei ``action == "zuruecksetzen"``."""
    label: str
    """Menschenlesbare Vorschau, die sowohl in der Bestätigungsfrage als auch in
    der Erfolgsmeldung nach der Löschung erscheint."""
    created_at: datetime = field(default_factory=_now)


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------


def _unknown_project_names(result: ExtractionResult, repo: Repository) -> frozenset[str]:
    """Projektnamen aus Aufgaben/Projekt-Updates/Örtlichkeiten, die noch nicht in der DB existieren.

    Nur für die Anzeige im Vorschlag (Schritt 8.25) — die Wahrheit entscheidet sich
    erst beim Persistieren (``persist_result.new_projects``), da zwischen Vorschlag
    und Bestätigung ein Projekt anderweitig entstehen kann (Race).
    """
    names = {t.project for t in result.tasks if t.project}
    names |= {pu.project for pu in result.project_updates}
    names |= {loc.project for loc in result.locations if loc.project}
    return frozenset(name for name in names if repo.get_project_by_title(name) is None)


def _unknown_ort_names(result: ExtractionResult, repo: Repository) -> frozenset[str]:
    """Ortsnamen aus Örtlichkeiten, die noch nicht in der DB existieren (Schritt 8.26).

    Analog zu ``_unknown_project_names`` — reine Anzeige-Markierung ("— neu") im
    Vorschlag, die Wahrheit entscheidet sich erst beim Persistieren.
    """
    names = {loc.name for loc in result.locations}
    return frozenset(name for name in names if repo.get_ort_by_name(name) is None)


def _result_items(
    result: ExtractionResult,
    unknown_projects: frozenset[str] = frozenset(),
    unknown_orte: frozenset[str] = frozenset(),
) -> list[tuple[str, _Item]]:
    """Alle extrahierten Elemente als (Label, Objekt)-Liste (stabile Reihenfolge).

    ``unknown_projects`` (Schritt 8.25): Projektnamen, die noch nicht in der DB
    existieren, werden im Label als "— neu" markiert — implizit über
    ``get_or_create_project`` angelegte Projekte sollen VOR der Bestätigung
    sichtbar sein (Human-in-the-loop-Lücke, Designprinzip 3). ``unknown_orte``
    (Schritt 8.26): analoge Markierung für neue Örtlichkeiten.
    """
    items: list[tuple[str, _Item]] = []
    for c in result.contacts:
        typ = f" ({c.type})" if c.type else ""
        items.append((f"👤 Kontakt: {c.name}{typ}", c))
    for t in result.tasks:
        # due wird IMMER angezeigt — auch "(kein Datum)" —, damit der Nutzer ein
        # fehlendes/falsches Datum schon VOR der Bestätigung erkennt.
        due = f", fällig: {format_date_de(t.due)}" if t.due else ", fällig: (kein Datum)"
        if t.project:
            marker = " — neu" if t.project in unknown_projects else ""
            proj = f" [{t.project}{marker}]"
        else:
            proj = ""
        items.append((f"📋 Aufgabe: {t.title}{proj}{due}", t))
    for pu in result.project_updates:
        status_str = f" → {pu.status}" if pu.status else ""
        marker = " — neu" if pu.project in unknown_projects else ""
        items.append((f"📁 Projekt: {pu.project}{marker}{status_str}", pu))
    for comp in result.completed:
        items.append((f"✅ Aufgabe schließen: #{comp.task_id} {comp.task_title}", comp))
    for ed in result.edits:
        items.append((f"✏️ Aufgabe ändern: #{ed.task_id} {ed.task_title} — {_edit_changes(ed)}", ed))
    for loc in result.locations:
        items.append((f"📍 Örtlichkeit: {_ort_label(loc, unknown_orte, unknown_projects)}", loc))
    return items


def _ort_label(
    loc: ExtractedOrt, unknown_orte: frozenset[str], unknown_projects: frozenset[str]
) -> str:
    """Anzeigeform einer extrahierten Örtlichkeit inkl. Neu-Markierung (Schritt 8.26)."""
    marker = " — neu" if loc.name in unknown_orte else ""
    details = [d for d in (loc.adresse, loc.flurnummer and f"Flur {loc.flurnummer}") if d]
    detail_str = f" ({', '.join(details)})" if details else ""
    refs = []
    if loc.contact:
        refs.append(f"Kontakt: {loc.contact}")
    if loc.project:
        proj_marker = " — neu" if loc.project in unknown_projects else ""
        refs.append(f"Projekt: {loc.project}{proj_marker}")
    ref_str = f" [{', '.join(refs)}]" if refs else ""
    return f"{loc.name}{marker}{detail_str}{ref_str}"


def _edit_changes(ed: ExtractedTaskEdit) -> str:
    """Menschenlesbare Zusammenfassung der geänderten Felder einer Aufgabe.

    Zeigt für jedes gesetzte ``new_*``-Feld die Zieländerung, damit die Nutzerin
    schon VOR der Bestätigung sieht, was geändert wird. Ohne gesetztes Feld
    (sollte nicht vorkommen) ein neutraler Hinweis.
    """
    parts: list[str] = []
    if ed.new_title is not None:
        parts.append(f"Titel → «{ed.new_title}»")
    if ed.new_due is not None:
        parts.append(f"Frist → {format_date_de(ed.new_due)}")
    if ed.new_project is not None:
        parts.append(f"Projekt → {ed.new_project}")
    return ", ".join(parts) if parts else "(keine Änderung)"


def _parse_selection(text: str) -> list[int]:
    """Zahlen aus "1 2 3" oder "1,2" parsen → 0-basierte Indizes."""
    return [int(n) - 1 for n in re.findall(r"\d+", text) if int(n) >= 1]


def _norm(s: str) -> str:
    """Vergleichs-Normalform: getrimmt, kleingeschrieben, Mehrfach-Whitespace zu einem."""
    return re.sub(r"\s+", " ", s.strip().lower())


def dedupe_result(result: ExtractionResult) -> ExtractionResult:
    """Doppelte Einträge aus einem ExtractionResult entfernen (Über-Extraktion).

    Kleinere Modelle (z. B. qwen2.5:7b) zerlegen einen Satz gern in mehrere
    überlappende, identische Einträge. Wir entfernen exakte Dubletten je
    Kategorie und erhalten dabei die ursprüngliche Reihenfolge:

    - Kontakte: gleich bei identischem Namen.
    - Aufgaben: gleich bei identischem Titel **und** gleicher Frist (``due``).
    - Projekt-Updates: gleich bei identischem Projektnamen.
    - Örtlichkeiten: gleich bei identischem Namen.

    Reine Wertkopie — das übergebene ``result`` bleibt unverändert.
    """
    seen_contacts: set[str] = set()
    contacts: list[ExtractedContact] = []
    for c in result.contacts:
        ckey = _norm(c.name)
        if ckey not in seen_contacts:
            seen_contacts.add(ckey)
            contacts.append(c)

    seen_tasks: set[tuple[str, str]] = set()
    tasks: list[ExtractedTask] = []
    for t in result.tasks:
        tkey = (_norm(t.title), t.due.isoformat() if t.due else "")
        if tkey not in seen_tasks:
            seen_tasks.add(tkey)
            tasks.append(t)

    seen_updates: set[str] = set()
    updates: list[ExtractedProjectUpdate] = []
    for pu in result.project_updates:
        ukey = _norm(pu.project)
        if ukey not in seen_updates:
            seen_updates.add(ukey)
            updates.append(pu)

    seen_completions: set[int] = set()
    completions: list[ExtractedCompletion] = []
    for comp in result.completed:
        if comp.task_id not in seen_completions:
            seen_completions.add(comp.task_id)
            completions.append(comp)

    seen_edits: set[int] = set()
    edits: list[ExtractedTaskEdit] = []
    for ed in result.edits:
        if ed.task_id not in seen_edits:
            seen_edits.add(ed.task_id)
            edits.append(ed)

    seen_locations: set[str] = set()
    locations: list[ExtractedOrt] = []
    for loc in result.locations:
        lkey = _norm(loc.name)
        if lkey not in seen_locations:
            seen_locations.add(lkey)
            locations.append(loc)

    return ExtractionResult(
        contacts=contacts,
        tasks=tasks,
        project_updates=updates,
        completed=completions,
        edits=edits,
        locations=locations,
        clarification=result.clarification,
    )


# Hinweis auf die Korrektur-Schleife (Schritt 8.6): Eine Zitat-Antwort auf den
# Vorschlag löst einen Revisions-Lauf aus. Wird jedem Vorschlag angehängt, weil der
# Bestätigungstext bisher nur 👍/ja/nein erklärte — die Korrektur-Funktion aber nicht.
_CORRECTION_HINT = (
    "Zum Korrigieren antworte auf diese Nachricht (Zitat) und sag, was anders soll — "
    "z. B. anderer Name, Datum oder Projekt."
)


def format_proposal(result: ExtractionResult, repo: Repository | None = None) -> str:
    """Bestätigungstext aus ExtractionResult erzeugen.

    ``repo`` (optional, Schritt 8.25): wenn angegeben, werden Aufgaben-/Projekt-
    Update-Referenzen auf noch nicht existierende Projekte im Label markiert
    ("— neu") — ohne Repo (z. B. in isolierten Formatierungstests) entfällt die
    Markierung.
    """
    unknown_projects = _unknown_project_names(result, repo) if repo is not None else frozenset()
    unknown_orte = _unknown_ort_names(result, repo) if repo is not None else frozenset()
    items = _result_items(result, unknown_projects, unknown_orte)
    lines: list[str] = ["Ich habe folgendes erkannt:\n"]
    if len(items) == 1:
        label, _ = items[0]
        lines.append(label)
        lines.append('\nBestätige mit 👍 oder schreib "ja". Abbrechen mit "nein".')
    else:
        for i, (label, _) in enumerate(items, start=1):
            lines.append(f"{i}. {label}")
        lines.append(
            '\nAlles übernehmen? Schreib "ja" oder wähle Nummern (z.B. "1 3").'
            ' Abbrechen mit "nein".'
        )
    lines.append(_CORRECTION_HINT)
    return "\n".join(lines)


def _format_project_update_entry(pu: ExtractedProjectUpdate) -> str:
    """Menschenlesbaren Log-Eintrag aus einem Projekt-Update formulieren."""
    lines: list[str] = []
    if pu.status is not None:
        lines.append(f"Status: {pu.status}")
    if pu.phase_note is not None:
        lines.append(pu.phase_note)
    if pu.next_action is not None:
        lines.append(f"Nächster Schritt: {pu.next_action}")
    if pu.waiting_on is not None:
        lines.append(f"Wartet auf: {pu.waiting_on}")
    if not lines:
        lines.append("Projekt aktualisiert (keine weiteren Details).")
    return "\n".join(lines)


def _format_task_entry(et: ExtractedTask) -> str:
    """Menschenlesbaren Log-Eintrag für eine neue projektbezogene Aufgabe formulieren."""
    due = f" — fällig: {format_date_de(et.due)}" if et.due else ""
    return f"Neue Aufgabe: {et.title}{due}"


def _format_task_edit_entry(ed: ExtractedTaskEdit) -> str:
    """Log-Eintrag für die Änderung einer bestehenden Aufgabe (append-only, 8.19)."""
    return f"Aufgabe geändert: {ed.task_title} — {_edit_changes(ed)}"


@dataclass
class PersistSummary:
    """Ergebnis von ``persist_result`` (Schritt 8.25).

    ``count`` ist die bisherige Gesamtzahl persistierter Elemente; ``new_projects``
    sind die Titel der Projekte, die dabei implizit **neu** angelegt wurden (über
    ``get_or_create_project``) — damit die ✅-Bestätigung sie explizit nennen kann
    (Human-in-the-loop-Sichtbarkeit für einen sonst stillen Nebeneffekt,
    Designprinzip 3). Die Wahrheit entscheidet sich hier, beim Persistieren, nicht
    schon im Vorschlag (``_unknown_project_names``) — zwischen Vorschlag und
    Bestätigung kann das Projekt anderweitig entstehen (Race).
    """

    count: int
    new_projects: list[str] = field(default_factory=list)


def persist_result(
    result: ExtractionResult,
    indices: list[int] | None,
    repo: Repository,
    log_dir: Path,
) -> PersistSummary:
    """ExtractionResult in das echte Repository schreiben.

    indices: ``None`` → alle Einträge übernehmen; sonst 0-basierte Indizes
             der vom Nutzer ausgewählten Elemente.
    Gibt eine ``PersistSummary`` zurück (Anzahl + neu angelegte Projekte).
    """
    items = _result_items(result)
    selected: set[int] = set(range(len(items))) if indices is None else set(indices)

    contacts_to_save: list[ExtractedContact] = []
    tasks_to_save: list[ExtractedTask] = []
    updates_to_save: list[ExtractedProjectUpdate] = []
    completions_to_save: list[ExtractedCompletion] = []
    edits_to_save: list[ExtractedTaskEdit] = []
    locations_to_save: list[ExtractedOrt] = []

    for i, (_, obj) in enumerate(items):
        if i not in selected:
            continue
        if isinstance(obj, ExtractedContact):
            contacts_to_save.append(obj)
        elif isinstance(obj, ExtractedTask):
            tasks_to_save.append(obj)
        elif isinstance(obj, ExtractedProjectUpdate):
            updates_to_save.append(obj)
        elif isinstance(obj, ExtractedCompletion):
            completions_to_save.append(obj)
        elif isinstance(obj, ExtractedTaskEdit):
            edits_to_save.append(obj)
        elif isinstance(obj, ExtractedOrt):
            locations_to_save.append(obj)

    count = 0
    new_projects: list[str] = []

    # 1. Kontakte zuerst — Tasks/Projekte benötigen ggf. contact_id
    for ec in contacts_to_save:
        repo.upsert_contact(ec)
        count += 1

    # 2. Projektaktualisierungen
    for pu in updates_to_save:
        if repo.get_project_by_title(pu.project) is None:
            new_projects.append(pu.project)
        project = repo.get_or_create_project(pu.project)
        if pu.status is not None:
            project.status = pu.status
        if pu.phase_note is not None:
            project.phase_note = pu.phase_note
        if pu.next_action is not None:
            project.next_action = pu.next_action
        if pu.waiting_on is not None:
            project.waiting_on = pu.waiting_on
        log = open_project_log(project, log_dir)
        repo.update_project(project)
        log.append_entry(_format_project_update_entry(pu), source="Sprachnotiz")
        count += 1

    # 3. Tasks
    for et in tasks_to_save:
        contact_id: int | None = None
        if et.contact:
            c = repo.get_contact_by_name(et.contact)
            if c is not None:
                contact_id = c.id
        project_id: int | None = None
        if et.project:
            if repo.get_project_by_title(et.project) is None:
                new_projects.append(et.project)
            p = repo.get_or_create_project(et.project, contact_id=contact_id)
            had_log = p.markdown_log_path is not None
            log = open_project_log(p, log_dir)
            if not had_log:
                repo.update_project(p)
            log.append_entry(_format_task_entry(et), source="Sprachnotiz")
            project_id = p.id
        repo.create_task(
            Task(
                title=et.title,
                contact_id=contact_id,
                project_id=project_id,
                due=et.due,
                time_window=et.time_window,
                status=TaskStatus.OFFEN,
                source=TaskSource.SPRACHNOTIZ,
            )
        )
        count += 1

    # 4. Erledigungen — bestehende offene Aufgaben schließen. Falls die Aufgabe
    # zwischenzeitlich nicht mehr offen/vorhanden ist (Race, doppelte Bestätigung),
    # überspringen statt den gesamten Persistenz-Lauf abzubrechen.
    for comp in completions_to_save:
        with contextlib.suppress(ValueError):
            repo.mark_task_done(comp.task_id)
            count += 1

    # 5. Änderungen an bestehenden Aufgaben (Schritt 8.19). new_project wird zu einer
    # project_id aufgelöst (bei Bedarf angelegt); nur gesetzte Felder werden geändert.
    # Hängt die (geänderte) Aufgabe an einem Projekt mit Log, wird die Korrektur dort
    # append-only vermerkt (Log-Konsistenz, Prinzip 4). Eine nicht mehr vorhandene
    # Aufgabe wird übersprungen statt den ganzen Lauf abzubrechen.
    for ed in edits_to_save:
        new_project_id: int | None = None
        if ed.new_project:
            if repo.get_project_by_title(ed.new_project) is None:
                new_projects.append(ed.new_project)
            p = repo.get_or_create_project(ed.new_project)
            if p.markdown_log_path is None:
                open_project_log(p, log_dir)
                repo.update_project(p)
            new_project_id = p.id
        try:
            updated = repo.update_task(
                ed.task_id,
                title=ed.new_title,
                due=ed.new_due,
                project_id=new_project_id,
            )
        except ValueError:
            continue
        if updated.project_id is not None:
            edit_project = repo.get_project_by_id(updated.project_id)
            if edit_project is not None and edit_project.markdown_log_path is not None:
                log = open_project_log(edit_project, log_dir)
                log.append_entry(_format_task_edit_entry(ed), source="Sprachnotiz")
        count += 1

    # 6. Örtlichkeiten (Schritt 8.26) — nach Kontakten/Projekten, damit eine
    # Verknüpfung auf einen im selben Vorschlag neu angelegten Kontakt/Projekt
    # greift. Kontakt-Verknüpfung nur bei bereits existierendem Kontakt (wie bei
    # Aufgaben, ``et.contact``); Projekt wird bei Bedarf angelegt (wie ``et.project``).
    for loc in locations_to_save:
        if loc.project and repo.get_project_by_title(loc.project) is None:
            new_projects.append(loc.project)
        ort = repo.get_or_create_ort(loc.name, adresse=loc.adresse, flurnummer=loc.flurnummer)
        assert ort.id is not None
        if loc.contact:
            c = repo.get_contact_by_name(loc.contact)
            if c is not None and c.id is not None:
                repo.link_contact_ort(c.id, ort.id)
        if loc.project:
            p = repo.get_or_create_project(loc.project)
            had_log = p.markdown_log_path is not None
            log = open_project_log(p, log_dir)
            if not had_log:
                repo.update_project(p)
            assert p.id is not None
            repo.link_project_ort(p.id, ort.id)
        count += 1

    return PersistSummary(count=count, new_projects=new_projects)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class Orchestrator:
    """Kern-Orchestrator: verdrahtet Channel, Transcriber, Agent und Repository.

    ``handle_message()`` ist die einzeln testbare Basiseinheit.
    ``run_once()`` verarbeitet alle aktuell verfügbaren Nachrichten einmalig.
    ``run_forever()`` ist der Dauerprozess für den Produktionsbetrieb.
    """

    def __init__(
        self,
        channel: Channel,
        repo: Repository,
        transcriber: Transcriber | None,
        settings: Settings,
        log_dir: Path,
        retry_delay: float = _EXTRACTION_RETRY_DELAY,
        trace: TraceWriter | None = None,
    ) -> None:
        self._channel = channel
        self._repo = repo
        self._transcriber = transcriber
        self._settings = settings
        self._log_dir = log_dir
        self._pending: dict[str, PendingProposal] = {}
        self._pending_clarifications: dict[str, PendingClarification] = {}
        self._pending_deletions: dict[str, PendingDeletion] = {}
        self._retry_delay = retry_delay
        self._trace: TraceWriter = trace if trace is not None else NoopTraceWriter()

    # ---------------------------------------------------------------------- #
    # Öffentliche API                                                          #
    # ---------------------------------------------------------------------- #

    def handle_message(self, msg: IncomingMessage, run_id: str | None = None) -> None:
        """Eine eingehende Nachricht verarbeiten (synchron, blockierend).

        ``run_id`` gruppiert alle Trace-Ereignisse (Orchestrator + darin
        ausgelöste LLM-Läufe) dieser einen Nachricht (Schritt 8.21). Ohne
        Angabe (z. B. Aufruf aus Tests) wird eine frische ID erzeugt.
        """
        rid = run_id if run_id is not None else new_run_id()
        kind = "Reaktion" if msg.is_reaction else ("Audio" if msg.audio_path else "Text")
        logger.info(
            "Eingang von %s (%s, pending=%s, rückfrage=%s)",
            msg.sender,
            kind,
            msg.sender in self._pending,
            msg.sender in self._pending_clarifications,
        )
        self._trace.write(
            "message_received",
            rid,
            {"sender": msg.sender, "kind": kind, "text": msg.text},
        )

        # Tapback-Reaktion (👍/👎): auf einen offenen Vorschlag = Bestätigung/Ablehnung,
        # auf eine offene Rückfrage = Ja/Nein-Antwort. Reaktionen ohne offenen
        # Zustand oder mit neutralem Emoji werden ignoriert (keine Extraktion).
        if msg.is_reaction:
            self._handle_reaction(msg, rid)
            return

        # Slash-Command (deutsch, z. B. "/offen")? Hat Vorrang vor einem offenen
        # Vorschlag/einer Rückfrage — deterministische DB-Abfrage ohne LLM, lässt
        # einen etwaig offenen Zustand unangetastet (Schritt 8.15).
        if msg.text:
            parsed = _parse_command(msg.text)
            if parsed is not None:
                cmd, cmd_args = parsed
                self._trace.write("routing", rid, {"entscheidung": f"befehl:/{cmd}"})
                self._handle_command(msg.sender, cmd, cmd_args, rid)
                return

        # Antwort auf eine ausstehende Lösch-Bestätigung (Schritt 8.22)? Destruktiv,
        # daher vor dem normalen Vorschlag geprüft — in der Praxis überschneiden sich
        # beide ohnehin nicht (``/loeschen``/``/zuruecksetzen`` verwerfen einen etwaig
        # offenen Vorschlag/eine offene Rückfrage beim Anlegen der Bestätigung).
        if msg.sender in self._pending_deletions and msg.text:
            text = msg.text.strip()
            if _YES.match(text):
                self._trace.write("routing", rid, {"entscheidung": "loeschen:bestätigung"})
                self._confirm_deletion(msg.sender, rid)
                return
            if _NO.match(text):
                self._trace.write("routing", rid, {"entscheidung": "loeschen:ablehnung"})
                self._reject_deletion(msg.sender, rid)
                return

        # Ist dies eine Antwort auf einen ausstehenden Vorschlag?
        if msg.sender in self._pending and msg.text:
            text = msg.text.strip()
            if _YES.match(text):
                self._trace.write("routing", rid, {"entscheidung": "bestätigung"})
                self._confirm(msg.sender, indices=None, run_id=rid)
                return
            if _NO.match(text):
                self._trace.write("routing", rid, {"entscheidung": "ablehnung"})
                self._reject(msg.sender, rid)
                return
            if _NUMS.match(text):
                sel = _parse_selection(text)
                if sel:
                    self._trace.write("routing", rid, {"entscheidung": "auswahl"})
                    self._confirm(msg.sender, indices=sel, run_id=rid)
                    return

        # Quote-Reply auf offenen Vorschlag = Korrektur (Stufe A, Schritt 8.6).
        # Minimal-Variante: jede Zitat-Antwort bei offenem Vorschlag ist eindeutig
        # eine Korrektur — pro Absender ist maximal ein Vorschlag offen.
        if msg.quote_target_timestamp is not None and msg.sender in self._pending:
            self._trace.write("routing", rid, {"entscheidung": "korrektur"})
            self._revise(msg.sender, msg, rid)
            return

        # Antwort auf eine offene Rückfrage (Text oder Sprache): mit dem
        # Ursprungstranskript neu extrahieren, statt als neue Notiz zu behandeln
        # (Schritt 8.13). Ein explizites "nein" verwirft die Rückfrage ohne LLM-Lauf.
        if msg.sender in self._pending_clarifications:
            if msg.text and _NO.match(msg.text.strip()):
                self._trace.write("routing", rid, {"entscheidung": "rückfrage-ablehnung"})
                self._discard_clarification(msg.sender, rid)
                return
            self._trace.write("routing", rid, {"entscheidung": "rückfrage-antwort"})
            self._answer_clarification(msg.sender, msg=msg, run_id=rid)
            return

        self._trace.write("routing", rid, {"entscheidung": "neue-notiz"})
        # Eine neue Notiz beendet stillschweigend eine noch unbeantwortete
        # Lösch-Bestätigung desselben Absenders — pro Sender ist höchstens ein
        # Pending-Zustand gültig (Schritt 8.22).
        self._pending_deletions.pop(msg.sender, None)

        # Normaler Ablauf: Transkript holen → extrahieren → Vorschlag schicken
        # Sofort-Quittung — knappe Bestätigung vor der langsamen Verarbeitung
        # (Transkription kann Minuten dauern, LLM-Extraktion ebenfalls).
        if msg.audio_path is not None and self._transcriber is not None:
            self._channel.send(msg.sender, "🎤 Sprachnotiz erhalten, ich verarbeite das kurz …")
        elif msg.text is not None:
            self._channel.send(msg.sender, "📝 Notiz erhalten, ich verarbeite das kurz …")

        transcript = self._get_transcript(msg)
        if transcript is None or not transcript.strip():
            return

        result = dedupe_result(self._extract(transcript, rid))

        if result.clarification:
            logger.info("Extraktion: Rückfrage gestellt")
            # Rückfrage merken, damit die nächste Nachricht als Antwort gilt
            # (Schritt 8.13). Etwaigen alten Vorschlag verwerfen — pro Sender
            # ist genau ein offener Zustand erlaubt.
            self._pending.pop(msg.sender, None)
            self._pending_clarifications[msg.sender] = PendingClarification(
                sender=msg.sender,
                transcript=transcript,
                question=result.clarification,
            )
            self._trace.write("clarification_sent", rid, {"frage": result.clarification})
            self._channel.send(msg.sender, f"Rückfrage: {result.clarification}")
            return

        if result.is_empty():
            logger.info("Extraktion: nichts Konkretes erkannt")
            self._channel.send(msg.sender, "Ich konnte nichts Konkretes erkennen.")
            return

        logger.info(
            "Extraktion: %d Kontakt(e), %d Aufgabe(n), %d Projekt-Update(s), "
            "%d Erledigung(en), %d Änderung(en), %d Örtlichkeit(en)",
            len(result.contacts),
            len(result.tasks),
            len(result.project_updates),
            len(result.completed),
            len(result.edits),
            len(result.locations),
        )

        proposal = PendingProposal(
            sender=msg.sender,
            transcript=transcript,
            result=result,
        )
        proposal_text = format_proposal(result, self._repo)
        self._trace.write("proposal_sent", rid, {"text": proposal_text})
        proposal.sent_timestamp = self._channel.send(msg.sender, proposal_text)
        self._pending[msg.sender] = proposal

    def run_once(self) -> None:
        """Alle aktuell verfügbaren Nachrichten einmalig verarbeiten.

        Ein Fehler bei *einer* Nachricht (z. B. Ollama-Timeout, Netzfehler)
        beendet weder die Schleife noch den Prozess: er wird geloggt, dem
        Absender wird eine knappe Meldung geschickt, danach geht es weiter.
        """
        for msg in self._channel.receive():
            rid = new_run_id()
            try:
                self.handle_message(msg, run_id=rid)
            except Exception as exc:
                logger.exception("Fehler bei der Verarbeitung einer Nachricht von %s", msg.sender)
                self._trace.write(
                    "error",
                    rid,
                    {"exception_type": type(exc).__name__, "exception_text": str(exc)},
                )
                with contextlib.suppress(Exception):
                    self._channel.send(
                        msg.sender,
                        "⚠ Bei der Verarbeitung ist ein Fehler aufgetreten. "
                        "Bitte später noch einmal versuchen.",
                    )

    def run_forever(self, poll_interval: float = 1.0) -> None:
        """Dauerprozess: wartet kontinuierlich auf neue Nachrichten (blockiert).

        Robust gegen Fehler in der Empfangs-/Poll-Schleife selbst (z. B.
        WebSocket-Abbruch, fehlerhaftes Envelope): solche Fehler werden geloggt
        und der nächste Poll-Zyklus startet — der Bot stürzt nicht ab.
        """
        logger.info("run_forever gestartet (poll_interval=%.1fs)", poll_interval)
        while True:
            try:
                self.run_once()
            except Exception:
                logger.exception("Fehler in der Empfangs-/Poll-Schleife — fahre fort")
            time.sleep(poll_interval)

    # ---------------------------------------------------------------------- #
    # Interne Methoden                                                         #
    # ---------------------------------------------------------------------- #

    def _handle_reaction(self, msg: IncomingMessage, run_id: str) -> None:
        """Tapback-Reaktion (👍/👎) auf Vorschlag, Rückfrage oder Lösch-Bestätigung auswerten.

        - 👍 auf Vorschlag → bestätigen; auf Rückfrage → als "Ja" beantworten; auf
          eine Lösch-Bestätigung (Schritt 8.22) → löschen.
        - 👎 auf Vorschlag → ablehnen; auf Rückfrage → verwerfen; auf eine
          Lösch-Bestätigung → abbrechen.
        - Neutrales Emoji oder kein offener Zustand → ignorieren (keine Extraktion).
        """
        emoji = msg.text
        if _is_affirmative_reaction(emoji):
            if msg.sender in self._pending_deletions:
                self._trace.write(
                    "routing", run_id, {"entscheidung": "reaktion:loeschen-bestätigung"}
                )
                self._confirm_deletion(msg.sender, run_id)
            elif msg.sender in self._pending:
                self._trace.write("routing", run_id, {"entscheidung": "reaktion:bestätigung"})
                self._confirm(msg.sender, indices=None, run_id=run_id)
            elif msg.sender in self._pending_clarifications:
                self._trace.write("routing", run_id, {"entscheidung": "reaktion:rückfrage-ja"})
                self._answer_clarification(msg.sender, answer="Ja.", run_id=run_id)
            else:
                logger.info("Reaktion 👍 ignoriert (kein offener Vorschlag / keine Rückfrage)")
                self._trace.write("routing", run_id, {"entscheidung": "reaktion:ignoriert"})
            return
        if _is_negative_reaction(emoji):
            if msg.sender in self._pending_deletions:
                self._trace.write(
                    "routing", run_id, {"entscheidung": "reaktion:loeschen-ablehnung"}
                )
                self._reject_deletion(msg.sender, run_id)
            elif msg.sender in self._pending:
                self._trace.write("routing", run_id, {"entscheidung": "reaktion:ablehnung"})
                self._reject(msg.sender, run_id)
            elif msg.sender in self._pending_clarifications:
                self._trace.write("routing", run_id, {"entscheidung": "reaktion:rückfrage-nein"})
                self._discard_clarification(msg.sender, run_id)
            else:
                logger.info("Reaktion 👎 ignoriert (kein offener Vorschlag / keine Rückfrage)")
                self._trace.write("routing", run_id, {"entscheidung": "reaktion:ignoriert"})
            return
        logger.info("Reaktion ignoriert (neutrales Emoji)")
        self._trace.write("routing", run_id, {"entscheidung": "reaktion:ignoriert"})

    def _handle_command(self, sender: str, cmd: str, args: str, run_id: str) -> None:
        """Deterministisches Slash-Command auswerten und Antwort senden (Schritt 8.15)."""
        logger.info("Kommando von %s: /%s %s", sender, cmd, args)
        if cmd == "offen":
            tasks = self._repo.query_open_tasks(sort_by_due=False)
            self._channel.send(sender, format_open_tasks(tasks))
        elif cmd == "dringend":
            tasks = self._repo.query_open_tasks(sort_by_due=True)
            self._channel.send(sender, format_open_tasks(tasks))
        elif cmd == "kontakte":
            self._channel.send(sender, format_contacts(self._repo.list_contacts()))
        elif cmd == "projekte":
            self._channel.send(sender, format_projects(self._repo.list_projects()))
        elif cmd == "orte":
            self._channel.send(sender, format_orte(self._repo.list_orte()))
        elif cmd == "erledigt":
            self._handle_erledigt(sender, args)
        elif cmd == "loeschen":
            self._handle_loeschen(sender, args, run_id)
        elif cmd == "zuruecksetzen":
            self._handle_zuruecksetzen(sender, run_id)
        elif cmd == "hilfe":
            self._channel.send(sender, _HELP_TEXT)
        else:
            self._channel.send(sender, f'Unbekanntes Kommando "/{cmd}".\n\n{_HELP_TEXT}')

    def _handle_erledigt(self, sender: str, args: str) -> None:
        """ "/erledigt <id>": genau eine Aufgabe als erledigt markieren."""
        if not re.fullmatch(r"\d+", args):
            self._channel.send(
                sender, 'Bitte eine Aufgaben-ID angeben, z.B. "/erledigt 3".\n\n' + _HELP_TEXT
            )
            return
        task_id = int(args)
        try:
            task = self._repo.mark_task_done(task_id)
        except ValueError:
            self._channel.send(sender, f"Keine offene Aufgabe mit ID {task_id} gefunden.")
            return
        self._channel.send(sender, f'✅ Aufgabe #{task.id} "{task.title}" erledigt.')

    def _handle_loeschen(self, sender: str, args: str, run_id: str) -> None:
        """ "/loeschen kontakt|projekt|aufgabe|ort <id>": Löschung vorschlagen (Schritt 8.22/8.26).

        Destruktiv → nie sofort ausführen. Zeigt zuerst eine Vorschau (Name/Titel,
        bei einem Projekt inkl. Anzahl mitgelöschter Aufgaben — Cascade, siehe
        ``Repository.delete_project``) und legt eine ``PendingDeletion`` an, die
        erst durch 👍/„ja" ausgeführt wird. Ein etwaig offener Vorschlag/eine
        offene Rückfrage desselben Absenders wird dabei verworfen — pro Absender
        ist höchstens ein Pending-Zustand gleichzeitig offen.
        """
        match = _LOESCHEN_ARGS.match(args.strip())
        if match is None:
            self._channel.send(sender, _LOESCHEN_USAGE)
            return
        kind = match.group(1).lower()
        target_id = int(match.group(2))

        if kind == "kontakt":
            contact = self._repo.get_contact_by_id(target_id)
            if contact is None:
                self._channel.send(sender, f"Kein Kontakt mit ID {target_id} gefunden.")
                return
            label = f'Kontakt #{contact.id} "{contact.name}"'
        elif kind == "projekt":
            project = self._repo.get_project_by_id(target_id)
            if project is None:
                self._channel.send(sender, f"Kein Projekt mit ID {target_id} gefunden.")
                return
            task_count = len(self._repo.get_tasks_by_project(target_id))
            extra = f" inkl. {task_count} Aufgabe(n)" if task_count else ""
            label = f'Projekt #{project.id} "{project.title}"{extra}'
        elif kind == "aufgabe":
            task = self._repo.get_task_by_id(target_id)
            if task is None:
                self._channel.send(sender, f"Keine Aufgabe mit ID {target_id} gefunden.")
                return
            label = f'Aufgabe #{task.id} "{task.title}"'
        else:  # "ort"
            ort = self._repo.get_ort_by_id(target_id)
            if ort is None:
                self._channel.send(sender, f"Keine Örtlichkeit mit ID {target_id} gefunden.")
                return
            label = f'Örtlichkeit #{ort.id} "{ort.name}"'

        self._pending.pop(sender, None)
        self._pending_clarifications.pop(sender, None)
        self._pending_deletions[sender] = PendingDeletion(
            sender=sender, action=kind, target_id=target_id, label=label
        )
        self._trace.write("proposal_sent", run_id, {"text": label, "aktion": f"loeschen:{kind}"})
        self._channel.send(
            sender,
            f'{label} wirklich löschen?\n\nBestätige mit 👍 oder schreib "ja". '
            'Abbrechen mit "nein".',
        )

    def _handle_zuruecksetzen(self, sender: str, run_id: str) -> None:
        """ "/zuruecksetzen": ALLES löschen (Kontakte, Projekte, Aufgaben, Schritt 8.22).

        Für die Testdaten-Situation (siehe Motiv in ROADMAP.md Schritt 8.22): eine
        schnelle Möglichkeit, komplett neu anzufangen. Genau wie ``/loeschen`` nie
        ohne Bestätigung — zeigt zuerst die Gesamtanzahl je Kategorie.
        """
        contacts = self._repo.get_all_contacts()
        projects = self._repo.get_all_projects()
        tasks = self._repo.get_all_tasks()
        orte = self._repo.get_all_orte()
        if not contacts and not projects and not tasks and not orte:
            self._channel.send(sender, "Es ist nichts gespeichert, das gelöscht werden könnte.")
            return
        label = (
            f"{len(contacts)} Kontakt(e), {len(projects)} Projekt(e), "
            f"{len(tasks)} Aufgabe(n), {len(orte)} Örtlichkeit(en)"
        )
        self._pending.pop(sender, None)
        self._pending_clarifications.pop(sender, None)
        self._pending_deletions[sender] = PendingDeletion(
            sender=sender, action="zuruecksetzen", target_id=None, label=label
        )
        self._trace.write(
            "proposal_sent", run_id, {"text": label, "aktion": "loeschen:zuruecksetzen"}
        )
        self._channel.send(
            sender,
            f'Wirklich ALLES löschen? {label}.\n\nBestätige mit 👍 oder schreib "ja". '
            'Abbrechen mit "nein".',
        )

    def _confirm_deletion(self, sender: str, run_id: str) -> None:
        """Bestätigte Lösch-Aktion ausführen (Schritt 8.22).

        Ist das Ziel zwischenzeitlich schon nicht mehr vorhanden (Race, doppelte
        Bestätigung), wird das freundlich gemeldet statt einen Fehler zu werfen —
        wie bei den Erledigungen/Änderungen in ``persist_result``.
        """
        pending = self._pending_deletions.pop(sender)
        try:
            if pending.action == "kontakt":
                assert pending.target_id is not None
                self._repo.delete_contact(pending.target_id)
            elif pending.action == "projekt":
                assert pending.target_id is not None
                self._repo.delete_project(pending.target_id)
            elif pending.action == "aufgabe":
                assert pending.target_id is not None
                self._repo.delete_task(pending.target_id)
            elif pending.action == "ort":
                assert pending.target_id is not None
                self._repo.delete_ort(pending.target_id)
            else:
                self._repo.reset_all()
        except ValueError:
            logger.info("Löschung für %s: Ziel bereits nicht mehr vorhanden", sender)
            self._trace.write("rejected", run_id, {"grund": "bereits entfernt"})
            self._channel.send(sender, "Das war zwischenzeitlich schon nicht mehr vorhanden.")
            return
        logger.info("Löschung bestätigt für %s: %s", sender, pending.label)
        self._trace.write("confirmed", run_id, {"aktion": f"loeschen:{pending.action}"})
        self._trace.write("persisted", run_id, {"count": 1, "labels": [pending.label]})
        self._channel.send(sender, f"✅ {pending.label} gelöscht.")

    def _reject_deletion(self, sender: str, run_id: str) -> None:
        self._pending_deletions.pop(sender, None)
        self._trace.write("rejected", run_id, {})
        self._channel.send(sender, "Verworfen. Keine Änderungen gespeichert.")

    def _get_transcript(self, msg: IncomingMessage) -> str | None:
        """Text aus Nachricht holen: direkt oder via Transcriber (für Audio)."""
        if msg.audio_path is not None and self._transcriber is not None:
            return self._transcriber.transcribe(msg.audio_path)
        return msg.text

    def _extract(self, transcript: str, run_id: str) -> ExtractionResult:
        """Zwei-Durchgang-Extraktion gegen temporäre In-Memory-Repos (Schritt 8.18).

        Bekannte Kontakt-/Projektnamen und offene Aufgaben aus dem echten Repository
        werden dem Transkript vorangestellt (Namensabgleich, Erledigungs-Abgleich).

        **Erster Durchgang** (``_extract_first_pass``): der bisherige One-Shot mit
        Retry bei transienten Fehlern. **Zweiter Durchgang** (``run_gap_check``):
        prüft das Erstergebnis gegen das Transkript, füllt Lücken (fehlende Frist/
        Projektzuordnung) und trägt Übersehenes nach. Läuft immer — außer der erste
        Durchgang stellt bereits eine Rückfrage (die hat Vorrang). Scheitert der
        zweite Durchgang, wird das Erstergebnis genutzt (best-effort, kein Abbruch).

        Nur der Erst-Extraktionspfad ist zweistufig; Korrektur-/Rückfrage-Läufe
        (``run_revision``/``run_clarification_response``) sind bereits von der
        Nutzerin gesteuert und bleiben einstufig.
        """
        known_names = get_known_names_context(self._repo)
        open_tasks = get_open_tasks_context(self._repo)

        first = self._extract_first_pass(transcript, known_names, open_tasks, run_id)

        # Rückfrage aus dem ersten Durchgang hat Vorrang — kein zweiter Lauf.
        if first.clarification:
            return first

        try:
            return run_gap_check(
                transcript,
                first,
                self._settings,
                known_names_context=known_names,
                open_tasks_context=open_tasks,
                trace=self._trace,
                run_id=run_id,
            )
        except Exception as exc:
            logger.exception(
                "Zweiter Durchgang (Lücken-Prüfung) fehlgeschlagen — nutze Erstergebnis"
            )
            self._trace.write(
                "error",
                run_id,
                {
                    "phase": "gap_check",
                    "exception_type": type(exc).__name__,
                    "exception_text": str(exc),
                },
            )
            return first

    def _extract_first_pass(
        self, transcript: str, known_names: str, open_tasks: str, run_id: str
    ) -> ExtractionResult:
        """Erster Extraktionsdurchgang mit Retry bei transienten Fehlern.

        Bei transienten Fehlern (z. B. Ollama gerade nicht erreichbar, RAM-Engpass)
        wird der Aufruf bis zu ``_EXTRACTION_RETRIES``-mal wiederholt. Die Wartezeit
        zwischen den Versuchen ist über ``retry_delay`` konfigurierbar (Standard
        ``_EXTRACTION_RETRY_DELAY`` s; in Tests auf 0.0 setzen).
        """
        last_exc: Exception = RuntimeError("Extraktion: kein Versuch unternommen")
        for attempt in range(_EXTRACTION_RETRIES):
            tmp_repo = Repository(sqlite3.connect(":memory:", check_same_thread=False))
            try:
                return run_extraction(
                    transcript,
                    tmp_repo,
                    self._settings,
                    known_names_context=known_names,
                    open_tasks_context=open_tasks,
                    trace=self._trace,
                    run_id=run_id,
                )
            except Exception as exc:
                last_exc = exc
                if attempt < _EXTRACTION_RETRIES - 1:
                    logger.warning(
                        "Extraktion fehlgeschlagen (Versuch %d/%d) — warte %.0fs …",
                        attempt + 1,
                        _EXTRACTION_RETRIES,
                        self._retry_delay,
                    )
                    time.sleep(self._retry_delay)
        raise last_exc

    def _confirm(self, sender: str, indices: list[int] | None, run_id: str) -> None:
        proposal = self._pending.pop(sender)
        summary = persist_result(proposal.result, indices, self._repo, self._log_dir)
        labels = [
            label
            for i, (label, _) in enumerate(_result_items(proposal.result))
            if indices is None or i in indices
        ]
        logger.info("Persistiert: %d Eintrag/Einträge für %s", summary.count, sender)
        self._trace.write("confirmed", run_id, {"indices": indices})
        self._trace.write(
            "persisted",
            run_id,
            {"count": summary.count, "labels": labels, "neue_projekte": summary.new_projects},
        )
        message = f"✅ {summary.count} Eintrag/Einträge gespeichert."
        if summary.new_projects:
            # Neu angelegte Projekte explizit nennen — sonst stiller Nebeneffekt von
            # get_or_create_project, den die Nutzerin nie bestätigt hat (Schritt 8.25,
            # Designprinzip 3).
            names = ", ".join(f'"{name}"' for name in summary.new_projects)
            suffix = "e" if len(summary.new_projects) > 1 else ""
            message += f" Neues Projekt{suffix} angelegt: {names}."
        self._channel.send(sender, message)

    def _reject(self, sender: str, run_id: str) -> None:
        self._pending.pop(sender)
        self._trace.write("rejected", run_id, {})
        self._channel.send(sender, "Verworfen. Keine Änderungen gespeichert.")

    def _discard_clarification(self, sender: str, run_id: str) -> None:
        self._pending_clarifications.pop(sender, None)
        self._trace.write("rejected", run_id, {})
        self._channel.send(sender, "Verworfen. Keine Änderungen gespeichert.")

    def _answer_clarification(
        self,
        sender: str,
        run_id: str,
        answer: str | None = None,
        msg: IncomingMessage | None = None,
    ) -> None:
        """Beantwortet eine offene Rückfrage und erzeugt daraus einen Vorschlag.

        ``answer`` ist entweder direkt gesetzt (z. B. ``"Ja."`` aus einem 👍-Tapback)
        oder wird aus ``msg`` abgeleitet (Freitext oder transkribierte Sprache). Das
        Ergebnis durchläuft denselben Pfad wie eine normale Extraktion: konkrete
        Einträge → Vorschlag mit Bestätigungs-Loop, erneute Unklarheit → neue Rückfrage,
        leeres Ergebnis (z. B. Ablehnung) → Klärung verwerfen.
        """
        pending = self._pending_clarifications[sender]

        # Sofort-Quittung + Antworttext bestimmen.
        if answer is None and msg is not None:
            if msg.audio_path is not None and self._transcriber is not None:
                self._channel.send(sender, "🎤 Antwort erhalten, ich verarbeite das kurz …")
            else:
                self._channel.send(sender, "📝 Antwort erhalten, ich verarbeite das kurz …")
            answer = self._get_transcript(msg)
        else:
            self._channel.send(sender, "👍 Verstanden, ich bereite den Eintrag vor …")

        if answer is None or not answer.strip():
            self._channel.send(
                sender, "Ich konnte die Antwort nicht lesen. Bitte erneut versuchen."
            )
            return

        logger.info("Rückfrage-Antwort-Lauf für %s: %r", sender, answer[:80])
        known_names = get_known_names_context(self._repo)
        open_tasks = get_open_tasks_context(self._repo)
        try:
            result = dedupe_result(
                run_clarification_response(
                    original_transcript=pending.transcript,
                    clarification_question=pending.question,
                    answer=answer,
                    settings=self._settings,
                    known_names_context=known_names,
                    open_tasks_context=open_tasks,
                    history=pending.history,
                    trace=self._trace,
                    run_id=run_id,
                )
            )
        except Exception as exc:
            logger.exception("Fehler beim Rückfrage-Antwort-Lauf für %s", sender)
            self._trace.write(
                "error",
                run_id,
                {
                    "phase": "clarification_response",
                    "exception_type": type(exc).__name__,
                    "exception_text": str(exc),
                },
            )
            self._channel.send(
                sender,
                "⚠ Beim Verarbeiten der Antwort ist ein Fehler aufgetreten. Bitte erneut.",
            )
            return

        # Diese Rückfrage+Antwort-Runde wird Teil der Historie für den nächsten Turn.
        new_history = [*pending.history, ("Rückfrage", pending.question), ("Antwort", answer)]

        # Weiterhin unklar → Rückfrage aktualisieren, Klärung bleibt offen.
        if result.clarification:
            logger.info("Rückfrage-Antwort: erneute Rückfrage")
            self._pending_clarifications[sender] = PendingClarification(
                sender=sender,
                transcript=pending.transcript,
                question=result.clarification,
                history=new_history,
            )
            self._trace.write("clarification_sent", run_id, {"frage": result.clarification})
            self._channel.send(sender, f"Rückfrage: {result.clarification}")
            return

        # Ab hier ist die Klärung abgeschlossen (bestätigt oder abgelehnt).
        self._pending_clarifications.pop(sender, None)

        if result.is_empty():
            logger.info("Rückfrage-Antwort: nichts Konkretes erkannt")
            self._channel.send(sender, "Ich konnte nichts Konkretes erkennen.")
            return

        # Konkrete Einträge → normaler Vorschlag mit Bestätigungs-Loop.
        proposal = PendingProposal(
            sender=sender, transcript=pending.transcript, result=result, history=new_history
        )
        proposal_text = format_proposal(result, self._repo)
        self._trace.write("proposal_sent", run_id, {"text": proposal_text})
        proposal.sent_timestamp = self._channel.send(sender, proposal_text)
        self._pending[sender] = proposal
        logger.info(
            "Rückfrage-Antwort: %d Kontakt(e), %d Aufgabe(n), %d Projekt-Update(s), "
            "%d Erledigung(en), %d Änderung(en), %d Örtlichkeit(en)",
            len(result.contacts),
            len(result.tasks),
            len(result.project_updates),
            len(result.completed),
            len(result.edits),
            len(result.locations),
        )

    def _revise(self, sender: str, msg: IncomingMessage, run_id: str) -> None:
        """Korrektur-Lauf: revidiert den offenen Vorschlag anhand der Quote-Reply.

        Die Nutzerin zitiert den Vorschlag und schreibt (oder spricht) die Korrektur.
        Das LLM bekommt Ursprungstranskript + aktuellen Vorschlag + Korrekturtext und
        liefert ein überarbeitetes ExtractionResult, das erneut als Vorschlag gezeigt
        wird. Nichts wird bis zur Bestätigung persistiert.
        """
        # Sofort-Quittung vor dem langsamen Revisions-Lauf
        if msg.audio_path is not None and self._transcriber is not None:
            self._channel.send(sender, "🎤 Sprachkorrektur erhalten, überarbeite den Vorschlag …")
        else:
            self._channel.send(sender, "✏️ Korrektur erhalten, überarbeite den Vorschlag …")

        correction_text = self._get_transcript(msg)
        if correction_text is None or not correction_text.strip():
            self._channel.send(
                sender,
                "Ich konnte die Korrektur nicht lesen. Bitte erneut versuchen.",
            )
            return

        proposal = self._pending[sender]
        logger.info("Korrektur-Lauf für %s: %r", sender, correction_text[:80])
        known_names = get_known_names_context(self._repo)
        open_tasks = get_open_tasks_context(self._repo)
        try:
            revised = dedupe_result(
                run_revision(
                    original_transcript=proposal.transcript,
                    current_result=proposal.result,
                    correction=correction_text,
                    settings=self._settings,
                    known_names_context=known_names,
                    open_tasks_context=open_tasks,
                    history=proposal.history,
                    trace=self._trace,
                    run_id=run_id,
                )
            )
        except Exception as exc:
            logger.exception("Fehler beim Korrektur-Lauf für %s", sender)
            self._trace.write(
                "error",
                run_id,
                {
                    "phase": "revision",
                    "exception_type": type(exc).__name__,
                    "exception_text": str(exc),
                },
            )
            self._channel.send(
                sender,
                "⚠ Beim Überarbeiten ist ein Fehler aufgetreten. Bitte neu einsprechen.",
            )
            return

        if revised.clarification:
            logger.info("Korrektur-Lauf: Rückfrage gestellt")
            self._trace.write("clarification_sent", run_id, {"frage": revised.clarification})
            self._channel.send(sender, f"Rückfrage: {revised.clarification}")
            return

        if revised.is_empty():
            logger.info("Korrektur-Lauf: nichts erkannt")
            self._channel.send(
                sender,
                "Nach der Korrektur konnte ich nichts Konkretes erkennen. Bitte neu einsprechen.",
            )
            return

        # Diese Korrektur wird Teil der Historie für eine etwaige nächste Runde.
        new_proposal = PendingProposal(
            sender=sender,
            transcript=proposal.transcript,
            result=revised,
            history=[*proposal.history, ("Korrektur", correction_text)],
        )
        proposal_text = format_proposal(revised, self._repo)
        self._trace.write("proposal_sent", run_id, {"text": proposal_text})
        new_proposal.sent_timestamp = self._channel.send(sender, proposal_text)
        self._pending[sender] = new_proposal
        logger.info(
            "Korrektur-Lauf: %d Kontakt(e), %d Aufgabe(n), %d Projekt-Update(s), "
            "%d Erledigung(en), %d Änderung(en), %d Örtlichkeit(en)",
            len(revised.contacts),
            len(revised.tasks),
            len(revised.project_updates),
            len(revised.completed),
            len(revised.edits),
            len(revised.locations),
        )
