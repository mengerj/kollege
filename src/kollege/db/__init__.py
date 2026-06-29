"""Persistenz-Layer (SQLite).

Öffentliche API: ``Repository`` und ``open_repository``.
"""

from __future__ import annotations

import sqlite3

from kollege.db.repository import Repository

__all__ = ["Repository", "open_repository"]


def open_repository(db_path: str) -> Repository:
    """Datenbankverbindung öffnen und Repository zurückgeben.

    Erstellt die Datei und das Schema falls nicht vorhanden.
    check_same_thread=False: Pydantic-AI führt synchrone Tools in einem
    ThreadPoolExecutor aus — die Connection muss cross-thread nutzbar sein.
    """
    conn = sqlite3.connect(db_path, check_same_thread=False)
    return Repository(conn)
