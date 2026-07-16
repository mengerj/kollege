"""Laden + Schema-Validierung der Eval-Fixtures (beide Familien).

Fixtures sind **Daten, nicht Code**: ein neues Szenario ist eine neue JSON-Datei
in ``tests/fixtures/eval/`` (Extraktion) oder ``tests/fixtures/eval_revision/``
(Revision) — kein Code-Diff. Alle neuen ``expected``-Keys sind optional, damit
bestehende Fixtures ohne Änderung gültig bleiben.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from kollege.models import ExtractionResult


class ExtractionExpectation(BaseModel):
    """Was ein Fixture von einem ``ExtractionResult`` erwartet.

    Mindestanzahlen (``min_*``) allein belohnen Über-Extraktion (mehr ist immer
    besser). ``max_*`` fängt das Gegenstück ab. ``forbidden_keywords`` markiert
    konkrete Fehlerklassen (z. B. ein falsch verhörter Name), die auch bei
    ausreichender Trefferquote als Fehlschlag zählen sollen.
    """

    min_contacts: int = 0
    max_contacts: int | None = None
    contact_names: list[str] = Field(default_factory=list)

    min_tasks: int = 0
    max_tasks: int | None = None
    task_keywords: list[str] = Field(default_factory=list)

    min_project_updates: int = 0
    max_project_updates: int | None = None
    project_names: list[str] = Field(default_factory=list)

    # Erledigungen (Schritt 8.20): ``min_completed`` fordert eine Mindestzahl
    # geschlossener Aufgaben, ``must_contain_task_ids`` prüft, dass konkrete
    # Aufgaben-IDs im ``completed``-Feld erhalten bleiben — deckt den Fall ab, dass
    # ein Korrektur-Lauf zuvor erkannte Erledigungen verliert.
    min_completed: int = 0
    must_contain_task_ids: list[int] = Field(default_factory=list)

    # Örtlichkeiten (Schritt 8.26).
    min_locations: int = 0
    max_locations: int | None = None
    location_names: list[str] = Field(default_factory=list)

    forbidden_keywords: list[str] = Field(default_factory=list)
    must_not_be_empty: bool = False


class ExtractionFixture(BaseModel):
    """Ein Fixture für die Erstextraktion (``tests/fixtures/eval/*.json``)."""

    id: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    transcript: str
    expected: ExtractionExpectation


class RevisionFixture(BaseModel):
    """Ein Fixture für die Korrektur-/Revisions-Schleife (``tests/fixtures/eval_revision/*.json``).

    Bildet Schritt 8.6 (Quote-Reply-Revision) nach: Ursprungstranskript + bereits
    vorgeschlagenes ``ExtractionResult`` + Korrekturtext → erwartetes revidiertes
    Ergebnis. ``known_names`` simuliert den Kontext aus Schritt 8.7.
    """

    id: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    original_transcript: str
    current_result: ExtractionResult
    correction: str
    known_names: list[str] = Field(default_factory=list)
    expected: ExtractionExpectation


def _load_json_dir(directory: Path) -> list[dict[str, Any]]:
    """Alle ``*.json``-Dateien eines Verzeichnisses laden, nach ``id`` sortiert."""
    raw = [json.loads(p.read_text()) for p in directory.glob("*.json")]
    return sorted(raw, key=lambda d: str(d["id"]))


def load_extraction_fixtures(directory: Path) -> list[ExtractionFixture]:
    """Extraktions-Fixtures aus ``directory`` laden und validieren."""
    return [ExtractionFixture.model_validate(d) for d in _load_json_dir(directory)]


def load_revision_fixtures(directory: Path) -> list[RevisionFixture]:
    """Revisions-Fixtures aus ``directory`` laden und validieren."""
    return [RevisionFixture.model_validate(d) for d in _load_json_dir(directory)]
