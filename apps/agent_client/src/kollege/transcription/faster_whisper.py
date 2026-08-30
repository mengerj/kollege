"""Whisper-basiertes Transkriptions-Backend via faster-whisper.

Läuft vollständig lokal — kein Audio verlässt das Gerät.
Auf Apple-Silicon-Macs nutzt ctranslate2 automatisch Metal-Beschleunigung.

Installation (optionale Dependency-Gruppe):
    uv sync --group transcription

Empfohlenes Modell für Eigen-/Ortsnamen: ``medium``.
Für schnelle Tests oder CI genügt ``tiny``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class FasterWhisperTranscriber:
    """Implements :class:`~kollege.transcription.Transcriber` via faster-whisper."""

    def __init__(
        self,
        model_size: str = "medium",
        device: str = "auto",
        compute_type: str = "auto",
        language: str = "de",
    ) -> None:
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._language = language
        self._model: Any = None

    # ---------------------------------------------------------------------- #
    # Internal                                                                 #
    # ---------------------------------------------------------------------- #

    def _load_model(self) -> Any:
        """Lazy-load model — avoids download at import time."""
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise ImportError(
                    "faster-whisper ist nicht installiert. "
                    "Installiere die optionale Dependency-Gruppe:\n"
                    "    uv sync --group transcription"
                ) from exc
            self._model = WhisperModel(
                self._model_size,
                device=self._device,
                compute_type=self._compute_type,
            )
        return self._model

    # ---------------------------------------------------------------------- #
    # Transcriber protocol                                                     #
    # ---------------------------------------------------------------------- #

    def transcribe(self, audio_path: Path) -> str:
        """Transkribiert die Audiodatei und gibt den deutschen Text zurück.

        Unterstützte Formate: WAV, FLAC, OGG/Opus (erfordert ffmpeg für Opus).
        """
        if not audio_path.exists():
            raise FileNotFoundError(audio_path)
        model = self._load_model()
        segments, _ = model.transcribe(
            str(audio_path),
            language=self._language,
            beam_size=5,
        )
        return " ".join(seg.text.strip() for seg in segments).strip()
