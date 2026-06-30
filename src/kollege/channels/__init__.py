"""Kanal-Interface (Ein-/Ausgabe).

Entkoppelt den Orchestrator vom konkreten Kanal (Signal in Phase 1). Eine
eingehende Nachricht ist Text und/oder Audio plus Absender; ausgehend sendet
der Assistent Text (Bestätigungsfragen, Briefings).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(slots=True)
class IncomingMessage:
    sender: str
    text: str | None = None
    audio_path: Path | None = None
    message_id: str | None = None
    is_reaction: bool = False
    """True, wenn ``text`` aus einer Signal-Tapback-Reaktion (Emoji) stammt.

    Reaktionen werden nicht extrahiert, sondern nur im Bestätigungs-Dialog als
    👍 = „ja" gewertet (siehe Orchestrator)."""
    quote_target_timestamp: int | None = None
    """Wenn die Nachricht eine Signal-Zitat-Antwort (Quote-Reply) ist: Sende-Timestamp
    der zitierten Nachricht (= ``quote.id`` im Signal-Envelope). ``None`` sonst.

    Wird vom Orchestrator genutzt, um Quote-Replies auf offene Vorschläge als
    Korrektur-Läufe zu erkennen (Schritt 8.6)."""


@runtime_checkable
class Channel(Protocol):
    """Empfängt und sendet Nachrichten über einen Kanal."""

    def receive(self) -> Iterable[IncomingMessage]: ...

    def send(self, recipient: str, text: str) -> int | None:
        """Sendet eine Nachricht und gibt ggf. den Sende-Timestamp zurück.

        Der Timestamp (Millisekunden seit Epoch) wird von signal-cli bei ``/v2/send``
        mitgeliefert. Er wird in ``PendingProposal.sent_timestamp`` gespeichert, damit
        eingehende Quote-Replies (``quote.id``) auf den richtigen Vorschlag gematch
        werden können. ``None``, wenn der Kanal keinen Timestamp liefert.
        """
        ...


@dataclass(slots=True)
class MemoryChannel:
    """In-Memory-Kanal für Tests und den Trockenlauf ohne echtes Signal."""

    inbox: list[IncomingMessage] = field(default_factory=list)
    sent: list[tuple[str, str]] = field(default_factory=list)

    def receive(self) -> Iterable[IncomingMessage]:
        while self.inbox:
            yield self.inbox.pop(0)

    def send(self, recipient: str, text: str) -> int | None:
        self.sent.append((recipient, text))
        return None
