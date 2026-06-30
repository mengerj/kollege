"""Tests für den SignalChannel-Adapter.

Strategie: Adapter-Logik gegen gemockte HTTP/WebSocket-Antworten.
Echter Container nur bei manuellem Integration-Test (nicht im Standard-CI).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kollege.channels import Channel
from kollege.channels.signal_channel import SignalChannel

BASE_URL = "http://localhost:8080"
ACCOUNT = "+49123456789"


# --------------------------------------------------------------------------- #
# Envelope-Fixtures                                                             #
# --------------------------------------------------------------------------- #


def _note_to_self_text(text: str, ts: int = 1_718_000_000_000) -> dict[str, object]:
    """Note-to-Self-Textnachricht (verknüpftes Gerät empfängt syncMessage.sentMessage)."""
    return {
        "envelope": {
            "source": ACCOUNT,
            "sourceNumber": ACCOUNT,
            "sourceDevice": 1,
            "timestamp": ts,
            "syncMessage": {
                "sentMessage": {
                    "destination": ACCOUNT,
                    "destinationNumber": ACCOUNT,
                    "timestamp": ts,
                    "message": text,
                    "attachments": [],
                }
            },
        }
    }


def _note_to_self_audio(att_id: str, ts: int = 1_718_000_000_001) -> dict[str, object]:
    """Note-to-Self-Sprachnachricht mit Audio-Anhang."""
    return {
        "envelope": {
            "source": ACCOUNT,
            "sourceNumber": ACCOUNT,
            "sourceDevice": 1,
            "timestamp": ts,
            "syncMessage": {
                "sentMessage": {
                    "destination": ACCOUNT,
                    "destinationNumber": ACCOUNT,
                    "timestamp": ts,
                    "message": None,
                    "attachments": [
                        {
                            "contentType": "audio/ogg; codecs=opus",
                            "id": att_id,
                            "size": 1234,
                        }
                    ],
                }
            },
        }
    }


def _note_to_self_reaction(
    emoji: str, is_remove: bool = False, ts: int = 1_718_000_000_005
) -> dict[str, object]:
    """Tapback-Reaktion auf eine eigene Notiz (Note-to-Self)."""
    return {
        "envelope": {
            "source": ACCOUNT,
            "sourceNumber": ACCOUNT,
            "sourceDevice": 1,
            "timestamp": ts,
            "syncMessage": {
                "sentMessage": {
                    "destination": ACCOUNT,
                    "destinationNumber": ACCOUNT,
                    "timestamp": ts,
                    "message": None,
                    "attachments": [],
                    "reaction": {
                        "emoji": emoji,
                        "targetAuthorNumber": ACCOUNT,
                        "targetSentTimestamp": ts - 1000,
                        "isRemove": is_remove,
                    },
                }
            },
        }
    }


def _sent_to_other(other: str, text: str, ts: int = 1_718_000_000_003) -> dict[str, object]:
    """Nutzer schreibt an einen Kontakt — KEIN Note-to-Self, muss ignoriert werden."""
    return {
        "envelope": {
            "source": ACCOUNT,
            "sourceNumber": ACCOUNT,
            "sourceDevice": 1,
            "timestamp": ts,
            "syncMessage": {
                "sentMessage": {
                    "destination": other,
                    "destinationNumber": other,
                    "timestamp": ts,
                    "message": text,
                    "attachments": [],
                }
            },
        }
    }


def _incoming_from_other(sender: str, text: str, ts: int = 1_718_000_000_004) -> dict[str, object]:
    """Eingehende Nachricht einer anderen Person (dataMessage) — muss ignoriert werden."""
    return {
        "envelope": {
            "source": sender,
            "sourceNumber": sender,
            "timestamp": ts,
            "dataMessage": {
                "timestamp": ts,
                "message": text,
                "attachments": [],
            },
        }
    }


def _receipt_envelope(sender: str, ts: int = 1_718_000_000_002) -> dict[str, object]:
    return {
        "envelope": {
            "source": sender,
            "sourceNumber": sender,
            "timestamp": ts,
            "receiptMessage": {"when": ts, "isDelivery": True},
        }
    }


def _mock_ws_connection(payloads: list[dict[str, object]]) -> MagicMock:
    """Erstellt einen Mock-WebSocket-Connection der ``payloads`` liefert, dann TimeoutError."""
    side_effects: list[str | TimeoutError] = [json.dumps(p) for p in payloads]
    side_effects.append(TimeoutError())
    conn = MagicMock()
    conn.recv.side_effect = side_effects
    return conn


# --------------------------------------------------------------------------- #
# Protocol-Konformität                                                          #
# --------------------------------------------------------------------------- #


def test_signal_channel_is_a_channel() -> None:
    ch = SignalChannel(base_url=BASE_URL, account=ACCOUNT)
    assert isinstance(ch, Channel)


# --------------------------------------------------------------------------- #
# _parse_envelope — isoliert, ohne WS-Mock                                     #
# --------------------------------------------------------------------------- #


def test_parse_envelope_note_to_self_text() -> None:
    ch = SignalChannel(base_url=BASE_URL, account=ACCOUNT)
    data = _note_to_self_text("Hallo!")
    msg = ch._parse_envelope(data)
    assert msg is not None
    assert msg.sender == ACCOUNT
    assert msg.text == "Hallo!"
    assert msg.audio_path is None
    assert msg.message_id == f"{ACCOUNT}:1718000000000"


def test_parse_envelope_receipt_returns_none() -> None:
    ch = SignalChannel(base_url=BASE_URL, account=ACCOUNT)
    data = _receipt_envelope("+49170")
    assert ch._parse_envelope(data) is None


def test_parse_envelope_empty_sent_message_returns_none() -> None:
    ch = SignalChannel(base_url=BASE_URL, account=ACCOUNT)
    data = _note_to_self_text(None)  # type: ignore[arg-type]
    assert ch._parse_envelope(data) is None


def test_parse_envelope_incoming_from_other_ignored() -> None:
    """Nachrichten anderer Personen (dataMessage) werden bewusst nicht verarbeitet."""
    ch = SignalChannel(base_url=BASE_URL, account=ACCOUNT)
    data = _incoming_from_other("+49170999", "Hallo, bist du da?")
    assert ch._parse_envelope(data) is None


def test_parse_envelope_sent_to_other_ignored() -> None:
    """Vom Nutzer an einen Kontakt gesendete Nachrichten sind kein Note-to-Self."""
    ch = SignalChannel(base_url=BASE_URL, account=ACCOUNT)
    data = _sent_to_other("+49170999", "Bis morgen!")
    assert ch._parse_envelope(data) is None


def test_parse_envelope_reaction_becomes_reaction_message() -> None:
    """Eine 👍-Tapback-Reaktion wird als is_reaction-IncomingMessage geparst."""
    ch = SignalChannel(base_url=BASE_URL, account=ACCOUNT)
    msg = ch._parse_envelope(_note_to_self_reaction("👍"))
    assert msg is not None
    assert msg.is_reaction is True
    assert msg.text == "👍"
    assert msg.sender == ACCOUNT


def test_parse_envelope_reaction_remove_ignored() -> None:
    """Das Entfernen einer Reaktion (isRemove) wird ignoriert."""
    ch = SignalChannel(base_url=BASE_URL, account=ACCOUNT)
    assert ch._parse_envelope(_note_to_self_reaction("👍", is_remove=True)) is None


# --------------------------------------------------------------------------- #
# receive() — via gemocktem WebSocket                                           #
# --------------------------------------------------------------------------- #


def test_receive_text_message(tmp_path: Path) -> None:
    envelope = _note_to_self_text("Hallo!")
    conn = _mock_ws_connection([envelope])

    ch = SignalChannel(base_url=BASE_URL, account=ACCOUNT, download_dir=tmp_path)

    with patch("websockets.sync.client.connect") as mock_connect:
        mock_connect.return_value = conn
        messages = list(ch.receive())

    assert len(messages) == 1
    assert messages[0].sender == ACCOUNT
    assert messages[0].text == "Hallo!"
    assert messages[0].audio_path is None


def test_receive_audio_message(tmp_path: Path) -> None:
    """Sprachnachricht: Anhang wird heruntergeladen, Pfad in IncomingMessage gesetzt."""
    att_id = "abc123"
    envelope = _note_to_self_audio(att_id)
    conn = _mock_ws_connection([envelope])

    fake_audio = b"OGG_FAKE_AUDIO"

    ch = SignalChannel(base_url=BASE_URL, account=ACCOUNT, download_dir=tmp_path)

    with (
        patch("websockets.sync.client.connect") as mock_connect,
        patch("httpx.get") as mock_get,
    ):
        mock_connect.return_value = conn
        mock_get.return_value.content = fake_audio
        mock_get.return_value.raise_for_status = MagicMock()

        messages = list(ch.receive())

    assert len(messages) == 1
    msg = messages[0]
    assert msg.text is None
    assert msg.audio_path is not None
    assert msg.audio_path.suffix == ".ogg"
    assert msg.audio_path.read_bytes() == fake_audio

    mock_get.assert_called_once_with(
        f"{BASE_URL}/v1/attachments/{att_id}",
        timeout=30.0,
    )


def test_receive_multiple_messages(tmp_path: Path) -> None:
    envelopes = [
        _note_to_self_text("Eins", ts=1_718_000_000_010),
        _note_to_self_text("Zwei", ts=1_718_000_000_011),
    ]
    conn = _mock_ws_connection(envelopes)

    ch = SignalChannel(base_url=BASE_URL, account=ACCOUNT, download_dir=tmp_path)

    with patch("websockets.sync.client.connect") as mock_connect:
        mock_connect.return_value = conn
        messages = list(ch.receive())

    assert len(messages) == 2
    assert [m.text for m in messages] == ["Eins", "Zwei"]


def test_receive_skips_receipt_messages(tmp_path: Path) -> None:
    envelopes = [
        _receipt_envelope("+49170"),
        _note_to_self_text("echte Nachricht"),
    ]
    conn = _mock_ws_connection(envelopes)

    ch = SignalChannel(base_url=BASE_URL, account=ACCOUNT, download_dir=tmp_path)

    with patch("websockets.sync.client.connect") as mock_connect:
        mock_connect.return_value = conn
        messages = list(ch.receive())

    assert len(messages) == 1
    assert messages[0].text == "echte Nachricht"


def test_receive_ignores_messages_from_other_people(tmp_path: Path) -> None:
    """Nur Note-to-Self wird verarbeitet; fremde dataMessages werden übersprungen."""
    envelopes = [
        _incoming_from_other("+49170999", "Spam von Fremden"),
        _sent_to_other("+49170888", "Nachricht an Kontakt"),
        _note_to_self_text("meine Notiz"),
    ]
    conn = _mock_ws_connection(envelopes)

    ch = SignalChannel(base_url=BASE_URL, account=ACCOUNT, download_dir=tmp_path)

    with patch("websockets.sync.client.connect") as mock_connect:
        mock_connect.return_value = conn
        messages = list(ch.receive())

    assert len(messages) == 1
    assert messages[0].text == "meine Notiz"
    assert messages[0].sender == ACCOUNT


def test_receive_ws_url_is_constructed_correctly(tmp_path: Path) -> None:
    conn = _mock_ws_connection([])
    ch = SignalChannel(base_url="http://myhost:8080", account="+49123", download_dir=tmp_path)

    with patch("websockets.sync.client.connect") as mock_connect:
        mock_connect.return_value = conn
        list(ch.receive())

    mock_connect.assert_called_once_with("ws://myhost:8080/v1/receive/+49123")


def test_receive_reuses_one_persistent_connection(tmp_path: Path) -> None:
    """Regression: Verbindung bleibt offen, sonst gehen Nachrichten in den Lücken verloren.

    Im json-rpc-Modus werden Nachrichten nicht erneut abgespielt. Mehrere
    ``receive()``-Aufrufe dürfen daher nur EINE WebSocket-Verbindung öffnen.
    """
    conn = MagicMock()
    # 1. Aufruf: eine Nachricht, dann Timeout; 2. Aufruf: direkt Timeout.
    conn.recv.side_effect = [
        json.dumps(_note_to_self_text("erste")),
        TimeoutError(),
        TimeoutError(),
    ]
    ch = SignalChannel(base_url=BASE_URL, account=ACCOUNT, download_dir=tmp_path)

    with patch("websockets.sync.client.connect") as mock_connect:
        mock_connect.return_value = conn
        first = list(ch.receive())
        second = list(ch.receive())

    assert [m.text for m in first] == ["erste"]
    assert second == []
    mock_connect.assert_called_once()  # Verbindung wurde wiederverwendet, nicht neu geöffnet


def test_receive_reconnects_after_connection_error(tmp_path: Path) -> None:
    """Nach einem Verbindungsfehler wird beim nächsten Aufruf neu verbunden."""
    broken = MagicMock()
    broken.recv.side_effect = OSError("connection lost")
    healthy = _mock_ws_connection([_note_to_self_text("nach reconnect")])

    ch = SignalChannel(base_url=BASE_URL, account=ACCOUNT, download_dir=tmp_path)

    with patch("websockets.sync.client.connect") as mock_connect:
        mock_connect.side_effect = [broken, healthy]
        first = list(ch.receive())  # Fehler → Verbindung wird geschlossen
        second = list(ch.receive())  # baut neu auf

    assert first == []
    assert [m.text for m in second] == ["nach reconnect"]
    assert mock_connect.call_count == 2


# --------------------------------------------------------------------------- #
# send()                                                                        #
# --------------------------------------------------------------------------- #


def test_send_posts_to_correct_endpoint(tmp_path: Path) -> None:
    ch = SignalChannel(base_url=BASE_URL, account=ACCOUNT, download_dir=tmp_path)

    with patch("httpx.post") as mock_post:
        mock_post.return_value.raise_for_status = MagicMock()
        ch.send("+49170123456", "Bestätigt! ✅")

    mock_post.assert_called_once_with(
        f"{BASE_URL}/v2/send",
        json={
            "message": "Bestätigt! ✅",
            "number": ACCOUNT,
            "recipients": ["+49170123456"],
        },
        timeout=10.0,
    )


# --------------------------------------------------------------------------- #
# Anhang-Cache                                                                  #
# --------------------------------------------------------------------------- #


def test_download_attachment_caches_file(tmp_path: Path) -> None:
    """Anhang wird nicht ein zweites Mal heruntergeladen wenn die Datei bereits existiert."""
    att_id = "xyz789"
    dest = tmp_path / f"att-{att_id}.ogg"
    dest.write_bytes(b"CACHED")

    ch = SignalChannel(base_url=BASE_URL, account=ACCOUNT, download_dir=tmp_path)

    with patch("httpx.get") as mock_get:
        result = ch._download_attachment(att_id, "audio/ogg; codecs=opus")

    mock_get.assert_not_called()
    assert result == dest


def test_download_attachment_uses_bin_extension_for_unknown_type(tmp_path: Path) -> None:
    att_id = "unkn0wn"
    ch = SignalChannel(base_url=BASE_URL, account=ACCOUNT, download_dir=tmp_path)

    with patch("httpx.get") as mock_get:
        mock_get.return_value.content = b"RAW"
        mock_get.return_value.raise_for_status = MagicMock()
        result = ch._download_attachment(att_id, "application/octet-stream")

    assert result.suffix == ".bin"


# --------------------------------------------------------------------------- #
# Import-Fehler (optionale Dependencies fehlen)                                 #
# --------------------------------------------------------------------------- #


def test_receive_raises_import_error_when_websockets_missing(tmp_path: Path) -> None:
    ch = SignalChannel(base_url=BASE_URL, account=ACCOUNT, download_dir=tmp_path)
    with (
        patch.dict(
            "sys.modules",
            {
                "websockets": None,
                "websockets.sync": None,
                "websockets.sync.client": None,
            },
        ),
        pytest.raises(ImportError, match="websockets"),
    ):
        list(ch.receive())


def test_send_raises_import_error_when_httpx_missing(tmp_path: Path) -> None:
    ch = SignalChannel(base_url=BASE_URL, account=ACCOUNT, download_dir=tmp_path)
    with (
        patch.dict("sys.modules", {"httpx": None}),
        pytest.raises(ImportError, match="httpx"),
    ):
        ch.send("+49170", "test")
