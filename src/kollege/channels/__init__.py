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


@runtime_checkable
class Channel(Protocol):
    """Empfängt und sendet Nachrichten über einen Kanal."""

    def receive(self) -> Iterable[IncomingMessage]: ...

    def send(self, recipient: str, text: str) -> None: ...


@dataclass(slots=True)
class MemoryChannel:
    """In-Memory-Kanal für Tests und den Trockenlauf ohne echtes Signal."""

    inbox: list[IncomingMessage] = field(default_factory=list)
    sent: list[tuple[str, str]] = field(default_factory=list)

    def receive(self) -> Iterable[IncomingMessage]:
        while self.inbox:
            yield self.inbox.pop(0)

    def send(self, recipient: str, text: str) -> None:
        self.sent.append((recipient, text))
