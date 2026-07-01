"""Eval-Paket (Schritt 8.11): Single Source of Truth für Fixture-Scoring.

Ohne LLM testbar, von ``tests/test_eval.py`` **und** ``scripts/benchmark_models.py``
gemeinsam genutzt (kein Logik-Duplikat):

- ``fixtures``: Laden + Schema-Validierung der JSON-Fixtures (Extraktion + Revision).
- ``scoring``: deklarativer Scorer (``expected``-Block → ``FixtureScore``).
- ``runner``: N-Wiederholungen pro Fixture + Aggregation über mehrere Läufe.
"""

from __future__ import annotations

from kollege.eval.fixtures import (
    ExtractionExpectation,
    ExtractionFixture,
    RevisionFixture,
    load_extraction_fixtures,
    load_revision_fixtures,
)
from kollege.eval.runner import DEFAULT_THRESHOLD, FixtureAggregate, RunResult, run_fixture_n_times
from kollege.eval.scoring import FixtureScore, score_result

__all__ = [
    "DEFAULT_THRESHOLD",
    "ExtractionExpectation",
    "ExtractionFixture",
    "FixtureAggregate",
    "FixtureScore",
    "RevisionFixture",
    "RunResult",
    "load_extraction_fixtures",
    "load_revision_fixtures",
    "run_fixture_n_times",
    "score_result",
]
