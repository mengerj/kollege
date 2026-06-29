"""Tests für FasterWhisperTranscriber.

Strategie:
- Unit-Test (kein LLM): FasterWhisperTranscriber implementiert das Transcriber-Protocol;
  falscher Pfad löst FileNotFoundError aus; ImportError ohne Paket (gemockt).
- ``slow``-Test: echter Modelllauf mit kurzer WAV-Fixture (tiny-Modell).
  Läuft nicht im Standard-CI. Ausführen mit:
      uv sync --group transcription
      uv run pytest -m slow
"""

from __future__ import annotations

import struct
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kollege.transcription import Transcriber
from kollege.transcription.faster_whisper import FasterWhisperTranscriber

# --------------------------------------------------------------------------- #
# Helpers                                                                       #
# --------------------------------------------------------------------------- #


def _write_silence_wav(path: Path, duration_s: float = 1.0, sample_rate: int = 16_000) -> None:
    """Schreibt eine kurze Stille-WAV-Datei (mono 16-bit PCM)."""
    n_frames = int(sample_rate * duration_s)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(struct.pack(f"<{n_frames}h", *([0] * n_frames)))


# --------------------------------------------------------------------------- #
# Unit-Tests (kein echtes Modell)                                               #
# --------------------------------------------------------------------------- #


def test_faster_whisper_is_a_transcriber() -> None:
    assert isinstance(FasterWhisperTranscriber(), Transcriber)


def test_faster_whisper_raises_on_missing_file(tmp_path: Path) -> None:
    t = FasterWhisperTranscriber()
    with pytest.raises(FileNotFoundError):
        t.transcribe(tmp_path / "missing.wav")


def test_faster_whisper_raises_import_error_when_package_missing(tmp_path: Path) -> None:
    audio = tmp_path / "note.wav"
    _write_silence_wav(audio)
    t = FasterWhisperTranscriber()
    with (
        patch.dict("sys.modules", {"faster_whisper": None}),
        pytest.raises(ImportError, match="faster-whisper ist nicht installiert"),
    ):
        t.transcribe(audio)


def test_faster_whisper_calls_model_transcribe(tmp_path: Path) -> None:
    """Prüft, dass transcribe() das Modell korrekt aufruft (Mock-Modell)."""
    audio = tmp_path / "note.wav"
    _write_silence_wav(audio)

    fake_segment = MagicMock()
    fake_segment.text = "Hallo Welt"

    fake_model = MagicMock()
    fake_model.transcribe.return_value = ([fake_segment], MagicMock())

    t = FasterWhisperTranscriber(model_size="tiny")
    t._model = fake_model  # inject mock — skips actual download

    result = t.transcribe(audio)

    fake_model.transcribe.assert_called_once_with(str(audio), language="de", beam_size=5)
    assert result == "Hallo Welt"


def test_faster_whisper_joins_multiple_segments(tmp_path: Path) -> None:
    audio = tmp_path / "note.wav"
    _write_silence_wav(audio)

    def _seg(text: str) -> MagicMock:
        m = MagicMock()
        m.text = text
        return m

    fake_model = MagicMock()
    fake_model.transcribe.return_value = ([_seg(" Satz eins."), _seg(" Satz zwei.")], MagicMock())

    t = FasterWhisperTranscriber()
    t._model = fake_model

    assert t.transcribe(audio) == "Satz eins. Satz zwei."


# --------------------------------------------------------------------------- #
# Slow-Test (echter Modelllauf — braucht ``uv sync --group transcription``)    #
# --------------------------------------------------------------------------- #


@pytest.mark.slow
def test_faster_whisper_transcribes_wav_integration(tmp_path: Path) -> None:
    """Smoke-Test: echter Whisper-Lauf auf einer Stille-WAV.

    Prüft nur, dass die Pipeline fehlerfrei durchläuft und einen str zurückgibt.
    Kein Inhalt-Assert: Stille → oft leerer String, das ist korrekt.
    """
    audio = tmp_path / "stille.wav"
    _write_silence_wav(audio, duration_s=1.0)

    t = FasterWhisperTranscriber(model_size="tiny")
    result = t.transcribe(audio)

    assert isinstance(result, str)
