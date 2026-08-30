"""Diagnose: rohe Signal-Envelopes für kurze Zeit mitschneiden.

Verbindet sich mit der signal-cli-rest-api-WebSocket und gibt jedes empfangene
Paket roh aus. Dient nur zum Verstehen, in welcher Form Nachrichten ankommen
(dataMessage vs. syncMessage). KEIN Produktionscode.

Aufruf:
    uv run python scripts/signal_debug_receive.py [sekunden]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from kollege.config import load_settings


def main() -> None:
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0
    settings = load_settings()
    base = settings.signal_api_url.rstrip("/")
    ws_url = base.replace("http://", "ws://").replace("https://", "wss://")
    ws_url += f"/v1/receive/{settings.signal_number}"

    from websockets.sync.client import connect as ws_connect

    print(f"Lausche {seconds:.0f}s auf rohe Envelopes … sende jetzt eine Testnachricht.\n")
    deadline = time.monotonic() + seconds
    count = 0
    with ws_connect(ws_url) as conn:
        while time.monotonic() < deadline:
            remaining = max(0.1, deadline - time.monotonic())
            try:
                raw = conn.recv(timeout=remaining)
            except TimeoutError:
                break
            count += 1
            data = json.loads(raw)
            env = data.get("envelope", {})
            known = ("dataMessage", "syncMessage", "receiptMessage", "typingMessage")
            keys = [k for k in known if k in env]
            print(f"--- Paket {count} | envelope-keys: {keys or list(env.keys())} ---")
            print(json.dumps(data, indent=2, ensure_ascii=False))
            print()
    print(f"Fertig. {count} Paket(e) empfangen.")


if __name__ == "__main__":
    main()
