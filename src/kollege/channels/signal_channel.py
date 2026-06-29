"""Signal-Kanal-Adapter via signal-cli-rest-api.

Verbindet den Orchestrator mit Signal über eine laufende signal-cli-rest-api-
Instanz (Docker). Empfang via WebSocket, Senden via HTTP POST, Anhänge
(Sprachnachrichten) werden lokal gespeichert.

Installation (optionale Dependency-Gruppe):
    uv sync --group signal

Setup:
    Siehe docs/signal-setup.md für die Linking-Anleitung.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from kollege.channels import IncomingMessage


class SignalChannel:
    """Channel-Adapter für signal-cli-rest-api (Docker).

    Empfängt Nachrichten via WebSocket, sendet via HTTP POST.
    Sprachnachrichten (OGG/Opus) werden lokal im ``download_dir`` gespeichert.
    """

    def __init__(
        self,
        base_url: str,
        account: str,
        download_dir: Path | None = None,
        receive_timeout: float = 0.5,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._account = account
        self._download_dir = download_dir or Path(tempfile.mkdtemp(prefix="kollege-signal-"))
        self._receive_timeout = receive_timeout

    # ---------------------------------------------------------------------- #
    # Channel Protocol                                                         #
    # ---------------------------------------------------------------------- #

    def receive(self) -> Iterable[IncomingMessage]:
        """Empfängt ausstehende Nachrichten via WebSocket (Batch-Mode).

        Verbindet sich, liest bis kein Paket mehr innerhalb von
        ``receive_timeout`` Sekunden eintrifft, und trennt dann.
        Für einen Dauerprozess: Schritt 7 (async-Orchestrator).
        """
        yield from self._ws_receive_batch()

    def send(self, recipient: str, text: str) -> None:
        """Sendet eine Textnachricht an ``recipient`` via HTTP POST."""
        self._http_send(recipient, text)

    # ---------------------------------------------------------------------- #
    # Internal: WebSocket receive                                              #
    # ---------------------------------------------------------------------- #

    def _ws_receive_batch(self) -> Iterator[IncomingMessage]:
        try:
            from websockets.sync.client import connect as ws_connect
        except ImportError as exc:
            raise ImportError(
                "websockets ist nicht installiert.\n"
                "Installiere die Signal-Dependency-Gruppe:\n"
                "    uv sync --group signal"
            ) from exc

        ws_url = (
            self._base_url.replace("http://", "ws://").replace("https://", "wss://")
            + f"/v1/receive/{self._account}"
        )

        with ws_connect(ws_url) as connection:
            while True:
                try:
                    raw = connection.recv(timeout=self._receive_timeout)
                except TimeoutError:
                    break
                data: dict[str, Any] = json.loads(raw)
                msg = self._parse_envelope(data)
                if msg is not None:
                    yield msg

    def _parse_envelope(self, data: dict[str, Any]) -> IncomingMessage | None:
        """Parst ein WebSocket-Paket in eine IncomingMessage.

        Gibt None zurück bei Empfangsbestätigungen, Sync-Nachrichten und
        Datenpaketen ohne Text und ohne Audio-Anhang.
        """
        envelope: dict[str, Any] = data.get("envelope") or {}
        sender = str(envelope.get("sourceNumber") or envelope.get("source") or "")
        timestamp = int(envelope.get("timestamp") or 0)
        message_id = f"{sender}:{timestamp}"

        data_msg: dict[str, Any] | None = envelope.get("dataMessage")
        if data_msg is None:
            return None

        text: str | None = data_msg.get("message") or None
        audio_path: Path | None = None

        for att in data_msg.get("attachments") or []:
            content_type = str(att.get("contentType") or "")
            if "audio" in content_type:
                att_id = str(att.get("id") or "")
                audio_path = self._download_attachment(att_id, content_type)
                break

        if text is None and audio_path is None:
            return None

        return IncomingMessage(
            sender=sender,
            text=text,
            audio_path=audio_path,
            message_id=message_id,
        )

    # ---------------------------------------------------------------------- #
    # Internal: HTTP send & attachment download                                #
    # ---------------------------------------------------------------------- #

    def _http_send(self, recipient: str, text: str) -> None:
        try:
            import httpx
        except ImportError as exc:
            raise ImportError(
                "httpx ist nicht installiert.\n"
                "Installiere die Signal-Dependency-Gruppe:\n"
                "    uv sync --group signal"
            ) from exc

        payload: dict[str, object] = {
            "message": text,
            "number": self._account,
            "recipients": [recipient],
        }
        response = httpx.post(f"{self._base_url}/v2/send", json=payload, timeout=10.0)
        response.raise_for_status()

    def _download_attachment(self, att_id: str, content_type: str) -> Path:
        try:
            import httpx
        except ImportError as exc:
            raise ImportError(
                "httpx ist nicht installiert.\n"
                "Installiere die Signal-Dependency-Gruppe:\n"
                "    uv sync --group signal"
            ) from exc

        ext = ".ogg" if "ogg" in content_type else ".bin"
        dest = self._download_dir / f"att-{att_id}{ext}"
        if not dest.exists():
            response = httpx.get(f"{self._base_url}/v1/attachments/{att_id}", timeout=30.0)
            response.raise_for_status()
            dest.write_bytes(response.content)
        return dest
