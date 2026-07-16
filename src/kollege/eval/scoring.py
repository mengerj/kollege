"""Deklarativer Scorer: ``expected``-Block → ``FixtureScore``.

Neue Prüfung = ein optionaler Key in ``ExtractionExpectation`` + ein Zweig hier —
kein Umbau von Fixtures oder Aufrufern nötig.
"""

from __future__ import annotations

from dataclasses import dataclass

from kollege.eval.fixtures import ExtractionExpectation
from kollege.models import ExtractionResult


@dataclass(frozen=True)
class FixtureScore:
    """Ergebnis eines einzelnen Scoring-Laufs gegen ein Fixture.

    ``hits``/``total``: Trefferquote über Mindestanzahlen + Schlüsselwörter
    (bestehendes Verhalten aus 8.10, unverändert). Die drei Flags kodieren die
    real beobachteten Fehlerklassen aus 8.11 zusätzlich zur Trefferquote:
    ``empty`` („nichts erkannt"), ``over_extraction`` (mehr als erwartet),
    ``forbidden_hit`` (eine konkret verbotene Ausgabe, z. B. ein Whisper-Verhörer).
    """

    hits: int
    total: int
    empty: bool
    over_extraction: bool
    forbidden_hit: bool

    @property
    def score(self) -> float:
        return self.hits / self.total if self.total > 0 else 1.0

    def passed(self, threshold: float) -> bool:
        """Bestanden = Trefferquote über Schwellenwert **und** keine Fehlerklasse getroffen."""
        failed_class = self.empty or self.over_extraction or self.forbidden_hit
        return self.score >= threshold and not failed_class


def score_result(result: ExtractionResult, expected: ExtractionExpectation) -> FixtureScore:
    hits = 0
    total = 0

    total += 1
    if len(result.contacts) >= expected.min_contacts:
        hits += 1
    for name_kw in expected.contact_names:
        total += 1
        if any(name_kw.lower() in c.name.lower() for c in result.contacts):
            hits += 1

    total += 1
    if len(result.tasks) >= expected.min_tasks:
        hits += 1
    for kw in expected.task_keywords:
        total += 1
        if any(kw.lower() in t.title.lower() for t in result.tasks):
            hits += 1

    total += 1
    if len(result.project_updates) >= expected.min_project_updates:
        hits += 1
    for proj_kw in expected.project_names:
        total += 1
        if any(proj_kw.lower() in pu.project.lower() for pu in result.project_updates):
            hits += 1

    total += 1
    if len(result.completed) >= expected.min_completed:
        hits += 1
    for task_id in expected.must_contain_task_ids:
        total += 1
        if any(comp.task_id == task_id for comp in result.completed):
            hits += 1

    total += 1
    if len(result.locations) >= expected.min_locations:
        hits += 1
    for loc_kw in expected.location_names:
        total += 1
        if any(loc_kw.lower() in loc.name.lower() for loc in result.locations):
            hits += 1

    over_extraction = (
        (expected.max_contacts is not None and len(result.contacts) > expected.max_contacts)
        or (expected.max_tasks is not None and len(result.tasks) > expected.max_tasks)
        or (
            expected.max_project_updates is not None
            and len(result.project_updates) > expected.max_project_updates
        )
        or (expected.max_locations is not None and len(result.locations) > expected.max_locations)
    )

    haystack = " ".join(
        [c.name for c in result.contacts]
        + [t.title for t in result.tasks]
        + [pu.project for pu in result.project_updates]
        + [loc.name for loc in result.locations]
        + ([result.clarification] if result.clarification else [])
    ).lower()
    forbidden_hit = any(kw.lower() in haystack for kw in expected.forbidden_keywords)

    empty = expected.must_not_be_empty and result.is_empty()

    return FixtureScore(
        hits=hits,
        total=total,
        empty=empty,
        over_extraction=over_extraction,
        forbidden_hit=forbidden_hit,
    )
