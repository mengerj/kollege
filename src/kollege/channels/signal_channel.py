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

import contextlib
import json
import tempfile
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from kollege.channels import IncomingMessage

# Signal-Sprachnachrichten kommen je nach App-Version in unterschiedlichen
# Formaten (neuere iOS-Clients: AAC, ältere: OGG/Opus). Die Dateiendung ist für
# faster-whisper zwar unkritisch (ffmpeg erkennt das Format am Inhalt), aber eine
# korrekte Endung hilft beim Debuggen und bei Tools, die nach Endung gehen.
_AUDIO_EXT_BY_KEYWORD: tuple[tuple[str, str], ...] = (
    ("ogg", ".ogg"),
    ("aac", ".aac"),
    ("m4a", ".m4a"),
    ("mp4", ".m4a"),
    ("mpeg", ".mp3"),
    ("mp3", ".mp3"),
    ("wav", ".wav"),
)


def _audio_ext(content_type: str) -> str:
    """Dateiendung aus dem MIME-contentType ableiten (Fallback ``.bin``)."""
    ct = content_type.lower()
    for keyword, ext in _AUDIO_EXT_BY_KEYWORD:
        if keyword in ct:
            return ext
    return ".bin"


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
        self._connection: Any = None

    # ---------------------------------------------------------------------- #
    # Channel Protocol                                                         #
    # ---------------------------------------------------------------------- #

    def receive(self) -> Iterable[IncomingMessage]:
        """Liest seit dem letzten Aufruf eingetroffene Nachrichten.

        Die WebSocket-Verbindung wird **dauerhaft offen gehalten** und zwischen
        den Aufrufen wiederverwendet. Grund: Im ``json-rpc``-Modus streamt
        signal-cli Nachrichten in Echtzeit und spielt sie *nicht* erneut ab.
        Eine pro Aufruf neu auf- und abgebaute Verbindung verlöre daher jede
        Nachricht, die in einer Verbindungslücke eintrifft. Jeder Aufruf liest
        alle gepufferten Pakete, bis kurzzeitig (``receive_timeout``) keines
        mehr eintrifft, und kehrt dann zurück — die Verbindung bleibt offen.
        """
        yield from self._ws_drain()

    def send(self, recipient: str, text: str) -> None:
        """Sendet eine Textnachricht an ``recipient`` via HTTP POST."""
        self._http_send(recipient, text)

    def close(self) -> None:
        """Schließt die offene WebSocket-Verbindung (idempotent)."""
        if self._connection is not None:
            with contextlib.suppress(Exception):
                self._connection.close()
            self._connection = None

    # ---------------------------------------------------------------------- #
    # Internal: WebSocket receive                                              #
    # ---------------------------------------------------------------------- #

    def _ensure_connection(self) -> Any:
        """Liefert die offene Verbindung; baut sie bei Bedarf (neu) auf."""
        if self._connection is not None:
            return self._connection

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
        self._connection = ws_connect(ws_url)
        return self._connection

    def _ws_drain(self) -> Iterator[IncomingMessage]:
        connection = self._ensure_connection()
        while True:
            try:
                raw = connection.recv(timeout=self._receive_timeout)
            except TimeoutError:
                break  # nichts mehr gepuffert — Verbindung bleibt offen
            except Exception:
                # Verbindung verloren/fehlerhaft: schließen, nächster Aufruf baut neu auf.
                self.close()
                break
            data: dict[str, Any] = json.loads(raw)
            msg = self._parse_envelope(data)
            if msg is not None:
                yield msg

    def _parse_envelope(self, data: dict[str, Any]) -> IncomingMessage | None:
        """Parst ein WebSocket-Paket in eine IncomingMessage.

        Verarbeitet **ausschließlich Note-to-Self**: Nachrichten, die der Nutzer
        in seinem eigenen „Notiz an mich"-Chat schreibt. Auf dem verknüpften
        Gerät kommen diese als ``syncMessage.sentMessage`` mit
        ``destination == eigene Nummer`` an.

        Bewusst **ignoriert** werden:
        - ``dataMessage`` (eingehende Nachrichten *anderer* Personen) — der Bot
          soll nicht jede empfangene Signal-Nachricht verarbeiten.
        - ``sentMessage`` an *andere* Empfänger (normale Chats des Nutzers).
        - Empfangs-/Lesebestätigungen und sonstige Sync-Typen.

        Eigene Bot-Antworten lösen keine Schleife aus: signal-cli stellt einem
        Gerät die selbst gesendeten Nachrichten nicht erneut zu (empirisch
        geprüft, siehe docs/signal-setup.md).
        """
        envelope: dict[str, Any] = data.get("envelope") or {}
        sender = str(envelope.get("sourceNumber") or envelope.get("source") or "")
        timestamp = int(envelope.get("timestamp") or 0)
        message_id = f"{sender}:{timestamp}"

        sync_msg: dict[str, Any] = envelope.get("syncMessage") or {}
        sent_msg: dict[str, Any] | None = sync_msg.get("sentMessage")
        if sent_msg is None:
            return None

        destination = str(sent_msg.get("destinationNumber") or sent_msg.get("destination") or "")
        if destination != self._account:
            return None  # an einen Kontakt gesendet, kein Note-to-Self

        # Tapback-Reaktion (👍 etc.) auf eine eigene Notiz: kommt als eigenes
        # ``reaction``-Feld (kein ``message``-Text). Wir reichen das Emoji als Text
        # mit ``is_reaction=True`` weiter; der Orchestrator wertet 👍 als „ja".
        # ``isRemove`` = das Entfernen einer Reaktion → ignorieren.
        reaction: dict[str, Any] | None = sent_msg.get("reaction")
        if reaction and not reaction.get("isRemove"):
            emoji = str(reaction.get("emoji") or "").strip()
            if emoji:
                return IncomingMessage(
                    sender=sender,
                    text=emoji,
                    is_reaction=True,
                    message_id=message_id,
                )
            return None

        text: str | None = sent_msg.get("message") or None
        audio_path: Path | None = None

        for att in sent_msg.get("attachments") or []:
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

        dest = self._download_dir / f"att-{att_id}{_audio_ext(content_type)}"
        if not dest.exists():
            response = httpx.get(f"{self._base_url}/v1/attachments/{att_id}", timeout=30.0)
            response.raise_for_status()
            dest.write_bytes(response.content)
        return dest
