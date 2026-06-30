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


def _text_envelope(sender: str, text: str, ts: int = 1_718_000_000_000) -> dict[str, object]:
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


def _audio_envelope(sender: str, att_id: str, ts: int = 1_718_000_000_001) -> dict[str, object]:
    return {
        "envelope": {
            "source": sender,
            "sourceNumber": sender,
            "timestamp": ts,
            "dataMessage": {
                "timestamp": ts,
                "message": None,
                "attachments": [
                    {
                        "contentType": "audio/ogg; codecs=opus",
                        "id": att_id,
                        "size": 1234,
                    }
                ],
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


def test_parse_envelope_text_message() -> None:
    ch = SignalChannel(base_url=BASE_URL, account=ACCOUNT)
    data = _text_envelope("+49170", "Hallo!")
    msg = ch._parse_envelope(data)
    assert msg is not None
    assert msg.sender == "+49170"
    assert msg.text == "Hallo!"
    assert msg.audio_path is None
    assert msg.message_id == "+49170:1718000000000"


def test_parse_envelope_receipt_returns_none() -> None:
    ch = SignalChannel(base_url=BASE_URL, account=ACCOUNT)
    data = _receipt_envelope("+49170")
    assert ch._parse_envelope(data) is None


def test_parse_envelope_empty_data_message_returns_none() -> None:
    ch = SignalChannel(base_url=BASE_URL, account=ACCOUNT)
    data: dict[str, object] = {
        "envelope": {
            "sourceNumber": "+49170",
            "timestamp": 1718000000,
            "dataMessage": {"message": None, "attachments": []},
        }
    }
    assert ch._parse_envelope(data) is None


# --------------------------------------------------------------------------- #
# receive() — via gemocktem WebSocket                                           #
# --------------------------------------------------------------------------- #


def test_receive_text_message(tmp_path: Path) -> None:
    envelope = _text_envelope("+49170123456", "Hallo!")
    conn = _mock_ws_connection([envelope])

    ch = SignalChannel(base_url=BASE_URL, account=ACCOUNT, download_dir=tmp_path)

    with patch("websockets.sync.client.connect") as mock_connect:
        mock_connect.return_value.__enter__.return_value = conn
        messages = list(ch.receive())

    assert len(messages) == 1
    assert messages[0].sender == "+49170123456"
    assert messages[0].text == "Hallo!"
    assert messages[0].audio_path is None


def test_receive_audio_message(tmp_path: Path) -> None:
    """Sprachnachricht: Anhang wird heruntergeladen, Pfad in IncomingMessage gesetzt."""
    att_id = "abc123"
    envelope = _audio_envelope("+49170123456", att_id)
    conn = _mock_ws_connection([envelope])

    fake_audio = b"OGG_FAKE_AUDIO"

    ch = SignalChannel(base_url=BASE_URL, account=ACCOUNT, download_dir=tmp_path)

    with (
        patch("websockets.sync.client.connect") as mock_connect,
        patch("httpx.get") as mock_get,
    ):
        mock_connect.return_value.__enter__.return_value = conn
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
        _text_envelope("+49170", "Eins"),
        _text_envelope("+49171", "Zwei"),
    ]
    conn = _mock_ws_connection(envelopes)

    ch = SignalChannel(base_url=BASE_URL, account=ACCOUNT, download_dir=tmp_path)

    with patch("websockets.sync.client.connect") as mock_connect:
        mock_connect.return_value.__enter__.return_value = conn
        messages = list(ch.receive())

    assert len(messages) == 2
    assert [m.text for m in messages] == ["Eins", "Zwei"]


def test_receive_skips_receipt_messages(tmp_path: Path) -> None:
    envelopes = [
        _receipt_envelope("+49170"),
        _text_envelope("+49170", "echte Nachricht"),
    ]
    conn = _mock_ws_connection(envelopes)

    ch = SignalChannel(base_url=BASE_URL, account=ACCOUNT, download_dir=tmp_path)

    with patch("websockets.sync.client.connect") as mock_connect:
        mock_connect.return_value.__enter__.return_value = conn
        messages = list(ch.receive())

    assert len(messages) == 1
    assert messages[0].text == "echte Nachricht"


def test_receive_ws_url_is_constructed_correctly(tmp_path: Path) -> None:
    conn = _mock_ws_connection([])
    ch = SignalChannel(base_url="http://myhost:8080", account="+49123", download_dir=tmp_path)

    with patch("websockets.sync.client.connect") as mock_connect:
        mock_connect.return_value.__enter__.return_value = conn
        list(ch.receive())

    mock_connect.assert_called_once_with("ws://myhost:8080/v1/receive/+49123")


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
