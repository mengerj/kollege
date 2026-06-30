"""Orchestrator: verdrahtet Channel → Transcriber → Agent → Repo → Bestätigung.

Ablauf:
1. Nachricht empfangen (Text oder Audio).
2. Audio → Transkript (Transcriber).
3. Transkript → ExtractionResult (Agent, temporäres In-Memory-Repo — kein echter DB-Schreibzugriff).
4. Vorschlag formatieren und an Nutzer senden.
5. Bestätigung (👍 / "ja") → Persistenz im echten Repo.
   Ablehnung ("nein") → verwerfen.
   Zahlenauswahl ("1 3") → nur gewählte Einträge übernehmen.

Pending-State: pro Absender (Rufnummer) ein ``PendingProposal`` im Arbeitsspeicher.
Jeder Absender kann nur einen Vorschlag gleichzeitig offen haben.
"""

from __future__ import annotations

import contextlib
import logging
import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from kollege.agent import get_known_names_context, run_extraction, run_revision
from kollege.channels import Channel, IncomingMessage
from kollege.config import Settings
from kollege.db import Repository
from kollege.logs import open_project_log
from kollege.models import (
    ExtractedContact,
    ExtractedProjectUpdate,
    ExtractedTask,
    ExtractionResult,
    Task,
    TaskSource,
    TaskStatus,
)
from kollege.transcription import Transcriber

__all__ = [
    "Orchestrator",
    "PendingProposal",
    "dedupe_result",
    "format_proposal",
    "persist_result",
]

logger = logging.getLogger("kollege.orchestrator")

# ---------------------------------------------------------------------------
# Typalias für die drei möglichen Extraktionsobjekte
# ---------------------------------------------------------------------------

_Item = ExtractedContact | ExtractedTask | ExtractedProjectUpdate

# ---------------------------------------------------------------------------
# Regex für Nutzereingaben im Bestätigungs-Dialog
# ---------------------------------------------------------------------------

_YES = re.compile(r"^\s*(ja|yes|👍|bestätigen?|ok|okay)\s*$", re.IGNORECASE)
_NO = re.compile(r"^\s*(nein|no|abbrechen?|verwerfen?|cancel)\s*$", re.IGNORECASE)
_NUMS = re.compile(r"^[\d\s,]+$")


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


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------


def _result_items(result: ExtractionResult) -> list[tuple[str, _Item]]:
    """Alle extrahierten Elemente als (Label, Objekt)-Liste (stabile Reihenfolge)."""
    items: list[tuple[str, _Item]] = []
    for c in result.contacts:
        typ = f" ({c.type})" if c.type else ""
        items.append((f"👤 Kontakt: {c.name}{typ}", c))
    for t in result.tasks:
        # due wird IMMER angezeigt — auch "(kein Datum)" —, damit der Nutzer ein
        # fehlendes/falsches Datum schon VOR der Bestätigung erkennt.
        due = f", fällig: {t.due}" if t.due else ", fällig: (kein Datum)"
        proj = f" [{t.project}]" if t.project else ""
        items.append((f"📋 Aufgabe: {t.title}{proj}{due}", t))
    for pu in result.project_updates:
        status_str = f" → {pu.status}" if pu.status else ""
        items.append((f"📁 Projekt: {pu.project}{status_str}", pu))
    return items


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

    return ExtractionResult(
        contacts=contacts,
        tasks=tasks,
        project_updates=updates,
        clarification=result.clarification,
    )


def format_proposal(result: ExtractionResult) -> str:
    """Bestätigungstext aus ExtractionResult erzeugen."""
    items = _result_items(result)
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
    return "\n".join(lines)


def persist_result(
    result: ExtractionResult,
    indices: list[int] | None,
    repo: Repository,
    log_dir: Path,
) -> int:
    """ExtractionResult in das echte Repository schreiben.

    indices: ``None`` → alle Einträge übernehmen; sonst 0-basierte Indizes
             der vom Nutzer ausgewählten Elemente.
    Gibt Anzahl persistierter Elemente zurück.
    """
    items = _result_items(result)
    selected: set[int] = set(range(len(items))) if indices is None else set(indices)

    contacts_to_save: list[ExtractedContact] = []
    tasks_to_save: list[ExtractedTask] = []
    updates_to_save: list[ExtractedProjectUpdate] = []

    for i, (_, obj) in enumerate(items):
        if i not in selected:
            continue
        if isinstance(obj, ExtractedContact):
            contacts_to_save.append(obj)
        elif isinstance(obj, ExtractedTask):
            tasks_to_save.append(obj)
        elif isinstance(obj, ExtractedProjectUpdate):
            updates_to_save.append(obj)

    count = 0

    # 1. Kontakte zuerst — Tasks/Projekte benötigen ggf. contact_id
    for ec in contacts_to_save:
        repo.upsert_contact(ec)
        count += 1

    # 2. Projektaktualisierungen
    for pu in updates_to_save:
        project = repo.get_or_create_project(pu.project)
        if pu.status is not None:
            project.status = pu.status
        if pu.phase_note is not None:
            project.phase_note = pu.phase_note
        if pu.next_action is not None:
            project.next_action = pu.next_action
        if pu.waiting_on is not None:
            project.waiting_on = pu.waiting_on
        open_project_log(project, log_dir)
        repo.update_project(project)
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
            p = repo.get_or_create_project(et.project, contact_id=contact_id)
            if p.markdown_log_path is None:
                open_project_log(p, log_dir)
                repo.update_project(p)
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

    return count


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
    ) -> None:
        self._channel = channel
        self._repo = repo
        self._transcriber = transcriber
        self._settings = settings
        self._log_dir = log_dir
        self._pending: dict[str, PendingProposal] = {}

    # ---------------------------------------------------------------------- #
    # Öffentliche API                                                          #
    # ---------------------------------------------------------------------- #

    def handle_message(self, msg: IncomingMessage) -> None:
        """Eine eingehende Nachricht verarbeiten (synchron, blockierend)."""
        kind = "Reaktion" if msg.is_reaction else ("Audio" if msg.audio_path else "Text")
        logger.info(
            "Eingang von %s (%s, pending=%s)",
            msg.sender,
            kind,
            msg.sender in self._pending,
        )

        # Tapback-Reaktion (👍) auf einen Vorschlag = Bestätigung. Andere
        # Reaktionen oder Reaktionen ohne offenen Vorschlag werden ignoriert
        # (sie sind keine Sprachnotiz und sollen nicht extrahiert werden).
        if msg.is_reaction:
            if msg.sender in self._pending and msg.text and _YES.match(msg.text.strip()):
                self._confirm(msg.sender, indices=None)
            else:
                logger.info("Reaktion ignoriert (kein 👍 auf offenen Vorschlag)")
            return

        # Ist dies eine Antwort auf einen ausstehenden Vorschlag?
        if msg.sender in self._pending and msg.text:
            text = msg.text.strip()
            if _YES.match(text):
                self._confirm(msg.sender, indices=None)
                return
            if _NO.match(text):
                self._reject(msg.sender)
                return
            if _NUMS.match(text):
                sel = _parse_selection(text)
                if sel:
                    self._confirm(msg.sender, indices=sel)
                    return

        # Quote-Reply auf offenen Vorschlag = Korrektur (Stufe A, Schritt 8.6).
        # Minimal-Variante: jede Zitat-Antwort bei offenem Vorschlag ist eindeutig
        # eine Korrektur — pro Absender ist maximal ein Vorschlag offen.
        if msg.quote_target_timestamp is not None and msg.sender in self._pending:
            self._revise(msg.sender, msg)
            return

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

        result = dedupe_result(self._extract(transcript))

        if result.clarification:
            logger.info("Extraktion: Rückfrage gestellt")
            self._channel.send(msg.sender, f"Rückfrage: {result.clarification}")
            return

        if result.is_empty():
            logger.info("Extraktion: nichts Konkretes erkannt")
            self._channel.send(msg.sender, "Ich konnte nichts Konkretes erkennen.")
            return

        logger.info(
            "Extraktion: %d Kontakt(e), %d Aufgabe(n), %d Projekt-Update(s)",
            len(result.contacts),
            len(result.tasks),
            len(result.project_updates),
        )

        proposal = PendingProposal(
            sender=msg.sender,
            transcript=transcript,
            result=result,
        )
        proposal.sent_timestamp = self._channel.send(msg.sender, format_proposal(result))
        self._pending[msg.sender] = proposal

    def run_once(self) -> None:
        """Alle aktuell verfügbaren Nachrichten einmalig verarbeiten.

        Ein Fehler bei *einer* Nachricht (z. B. Ollama-Timeout, Netzfehler)
        beendet weder die Schleife noch den Prozess: er wird geloggt, dem
        Absender wird eine knappe Meldung geschickt, danach geht es weiter.
        """
        for msg in self._channel.receive():
            try:
                self.handle_message(msg)
            except Exception:
                logger.exception("Fehler bei der Verarbeitung einer Nachricht von %s", msg.sender)
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

    def _get_transcript(self, msg: IncomingMessage) -> str | None:
        """Text aus Nachricht holen: direkt oder via Transcriber (für Audio)."""
        if msg.audio_path is not None and self._transcriber is not None:
            return self._transcriber.transcribe(msg.audio_path)
        return msg.text

    def _extract(self, transcript: str) -> ExtractionResult:
        """Agent gegen temporäres In-Memory-Repo — kein echter DB-Schreibzugriff.

        Bekannte Kontakt-/Projektnamen aus dem echten Repository werden dem
        Transkript vorangestellt, damit das LLM Whisper-Verhörer normalisieren kann.
        """
        tmp_repo = Repository(sqlite3.connect(":memory:", check_same_thread=False))
        known_names = get_known_names_context(self._repo)
        return run_extraction(transcript, tmp_repo, self._settings, known_names_context=known_names)

    def _confirm(self, sender: str, indices: list[int] | None) -> None:
        proposal = self._pending.pop(sender)
        count = persist_result(proposal.result, indices, self._repo, self._log_dir)
        logger.info("Persistiert: %d Eintrag/Einträge für %s", count, sender)
        self._channel.send(sender, f"✅ {count} Eintrag/Einträge gespeichert.")

    def _reject(self, sender: str) -> None:
        self._pending.pop(sender)
        self._channel.send(sender, "Verworfen. Keine Änderungen gespeichert.")

    def _revise(self, sender: str, msg: IncomingMessage) -> None:
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
        try:
            revised = dedupe_result(
                run_revision(
                    original_transcript=proposal.transcript,
                    current_result=proposal.result,
                    correction=correction_text,
                    settings=self._settings,
                    known_names_context=known_names,
                )
            )
        except Exception:
            logger.exception("Fehler beim Korrektur-Lauf für %s", sender)
            self._channel.send(
                sender,
                "⚠ Beim Überarbeiten ist ein Fehler aufgetreten. Bitte neu einsprechen.",
            )
            return

        if revised.clarification:
            logger.info("Korrektur-Lauf: Rückfrage gestellt")
            self._channel.send(sender, f"Rückfrage: {revised.clarification}")
            return

        if revised.is_empty():
            logger.info("Korrektur-Lauf: nichts erkannt")
            self._channel.send(
                sender,
                "Nach der Korrektur konnte ich nichts Konkretes erkennen. Bitte neu einsprechen.",
            )
            return

        new_proposal = PendingProposal(
            sender=sender,
            transcript=proposal.transcript,
            result=revised,
        )
        new_proposal.sent_timestamp = self._channel.send(sender, format_proposal(revised))
        self._pending[sender] = new_proposal
        logger.info(
            "Korrektur-Lauf: %d Kontakt(e), %d Aufgabe(n), %d Projekt-Update(s)",
            len(revised.contacts),
            len(revised.tasks),
            len(revised.project_updates),
        )
