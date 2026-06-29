"""Transkriptions-Interface.

Das echte Backend (faster-whisper / whisper.cpp) wird erst in der Audio-Phase
gewählt. Bis dahin entkoppelt das Protocol den Rest des Systems vom Backend;
``StubTranscriber`` erlaubt Tests ohne echtes Audio/Modell.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class Transcriber(Protocol):
    """Wandelt eine Audiodatei in Text um. Läuft lokal (kein Audio in die Cloud)."""

    def transcribe(self, audio_path: Path) -> str: ...


class StubTranscriber:
    """Deterministischer Platzhalter für Tests und den frühen Trockenlauf.

    Gibt einen vorkonfigurierten Text zurück, unabhängig vom Audioinhalt.
    """

    def __init__(self, canned_text: str = "") -> None:
        self._canned_text = canned_text

    def transcribe(self, audio_path: Path) -> str:
        if not audio_path.exists():
            raise FileNotFoundError(audio_path)
        return self._canned_text
