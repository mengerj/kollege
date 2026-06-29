"""Tests für die Stub-Implementierungen der Transkriptions- und Kanal-Interfaces."""

from __future__ import annotations

from pathlib import Path

import pytest

from kollege.channels import IncomingMessage, MemoryChannel
from kollege.transcription import StubTranscriber, Transcriber


def test_stub_transcriber_is_a_transcriber() -> None:
    assert isinstance(StubTranscriber(), Transcriber)


def test_stub_transcriber_returns_canned_text(tmp_path: Path) -> None:
    audio = tmp_path / "note.ogg"
    audio.write_bytes(b"fake")
    t = StubTranscriber(canned_text="Ruf Familie Müller zurück")
    assert t.transcribe(audio) == "Ruf Familie Müller zurück"


def test_stub_transcriber_raises_on_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        StubTranscriber().transcribe(tmp_path / "missing.ogg")


def test_memory_channel_roundtrip() -> None:
    ch = MemoryChannel()
    ch.inbox.append(IncomingMessage(sender="+49170", text="Hallo"))
    received = list(ch.receive())
    assert len(received) == 1
    assert received[0].text == "Hallo"
    # receive consumes the inbox
    assert list(ch.receive()) == []

    ch.send("+49170", "Bestätigt ✅")
    assert ch.sent == [("+49170", "Bestätigt ✅")]
