"""Deterministische Unit-Tests für ``kollege.eval`` (kein LLM, kein Netz).

Testet den deklarativen Scorer (``scoring.py``) und die Aggregation über
mehrere Wiederholungen (``runner.py``) direkt — die Bausteine, die
``tests/test_eval.py`` und ``scripts/benchmark_models.py`` gemeinsam nutzen.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

import pytest

from kollege.eval.fixtures import ExtractionExpectation
from kollege.eval.runner import DEFAULT_THRESHOLD, run_fixture_n_times
from kollege.eval.scoring import FixtureScore, score_result
from kollege.models import ExtractedContact, ExtractedTask, ExtractionResult

# --------------------------------------------------------------------------- #
# score_result                                                                 #
# --------------------------------------------------------------------------- #


def test_score_result_perfect_match_scores_full_hits() -> None:
    expected = ExtractionExpectation(min_contacts=1, contact_names=["Wagner"], min_tasks=1)
    result = ExtractionResult(
        contacts=[ExtractedContact(name="Frau Wagner")],
        tasks=[ExtractedTask(title="Pflanzplan erstellen")],
    )
    score = score_result(result, expected)
    assert score.hits == score.total
    assert score.score == 1.0
    assert not score.empty
    assert not score.over_extraction
    assert not score.forbidden_hit


def test_score_result_missing_keyword_reduces_score() -> None:
    expected = ExtractionExpectation(contact_names=["Wagner"])
    result = ExtractionResult(contacts=[ExtractedContact(name="Müller")])
    score = score_result(result, expected)
    assert score.hits < score.total
    assert score.score < 1.0


def test_over_extraction_flag_set_when_max_exceeded() -> None:
    expected = ExtractionExpectation(min_tasks=1, max_tasks=1)
    result = ExtractionResult(
        tasks=[ExtractedTask(title="Aufgabe A"), ExtractedTask(title="Aufgabe B")]
    )
    score = score_result(result, expected)
    assert score.over_extraction


def test_over_extraction_flag_not_set_within_bounds() -> None:
    expected = ExtractionExpectation(min_tasks=1, max_tasks=2)
    result = ExtractionResult(tasks=[ExtractedTask(title="Aufgabe A")])
    score = score_result(result, expected)
    assert not score.over_extraction


def test_must_not_be_empty_flags_empty_result() -> None:
    expected = ExtractionExpectation(must_not_be_empty=True)
    result = ExtractionResult()
    score = score_result(result, expected)
    assert score.empty


def test_must_not_be_empty_false_by_default_allows_empty_result() -> None:
    expected = ExtractionExpectation()
    result = ExtractionResult()
    score = score_result(result, expected)
    assert not score.empty


def test_forbidden_keyword_detected_in_task_title() -> None:
    expected = ExtractionExpectation(forbidden_keywords=["Eibling"])
    result = ExtractionResult(tasks=[ExtractedTask(title="Kunde in Eibling anrufen")])
    score = score_result(result, expected)
    assert score.forbidden_hit


def test_forbidden_keyword_detected_in_clarification() -> None:
    expected = ExtractionExpectation(forbidden_keywords=["Eibling"])
    result = ExtractionResult(clarification="War das jetzt Eibling oder Aibling?")
    score = score_result(result, expected)
    assert score.forbidden_hit


def test_forbidden_keyword_absent_does_not_flag() -> None:
    expected = ExtractionExpectation(forbidden_keywords=["Eibling"])
    result = ExtractionResult(tasks=[ExtractedTask(title="Kunde in Aibling anrufen")])
    score = score_result(result, expected)
    assert not score.forbidden_hit


# --------------------------------------------------------------------------- #
# FixtureScore.passed                                                          #
# --------------------------------------------------------------------------- #


def test_passed_true_when_score_above_threshold_and_no_flags() -> None:
    score = FixtureScore(hits=1, total=1, empty=False, over_extraction=False, forbidden_hit=False)
    assert score.passed(DEFAULT_THRESHOLD)


@pytest.mark.parametrize("flag", ["empty", "over_extraction", "forbidden_hit"])
def test_passed_false_when_any_flag_set_even_with_perfect_score(flag: str) -> None:
    flags = {"empty": False, "over_extraction": False, "forbidden_hit": False}
    flags[flag] = True
    score = FixtureScore(hits=1, total=1, **flags)
    assert not score.passed(DEFAULT_THRESHOLD)


def test_passed_false_when_score_below_threshold() -> None:
    score = FixtureScore(hits=0, total=2, empty=False, over_extraction=False, forbidden_hit=False)
    assert not score.passed(DEFAULT_THRESHOLD)


def test_score_property_treats_zero_total_as_full_score() -> None:
    score = FixtureScore(hits=0, total=0, empty=False, over_extraction=False, forbidden_hit=False)
    assert score.score == 1.0


# --------------------------------------------------------------------------- #
# run_fixture_n_times                                                          #
# --------------------------------------------------------------------------- #

_PASSING_SCORE = FixtureScore(
    hits=1, total=1, empty=False, over_extraction=False, forbidden_hit=False
)
_FAILING_SCORE = FixtureScore(
    hits=0, total=1, empty=True, over_extraction=False, forbidden_hit=False
)


def test_run_fixture_n_times_runs_exactly_n_times() -> None:
    calls = []

    def run_once() -> FixtureScore:
        calls.append(1)
        return _PASSING_SCORE

    aggregate = run_fixture_n_times("fixture-a", run_once, n=5)
    assert len(calls) == 5
    assert len(aggregate.runs) == 5


def test_run_fixture_n_times_all_pass_gives_full_pass_rate() -> None:
    aggregate = run_fixture_n_times("fixture-a", lambda: _PASSING_SCORE, n=4)
    assert aggregate.pass_rate == 1.0
    assert aggregate.mean_score == 1.0
    assert aggregate.empty_rate == 0.0


def test_run_fixture_n_times_captures_flakiness() -> None:
    """Alternierend passend/scheiternd — genau das Szenario, das ein Einzel-Lauf verdeckt."""
    results = [_PASSING_SCORE, _FAILING_SCORE, _PASSING_SCORE, _FAILING_SCORE]
    it = iter(results)

    aggregate = run_fixture_n_times("fixture-a", lambda: next(it), n=4)
    assert aggregate.pass_rate == 0.5
    assert aggregate.empty_rate == 0.5


def test_run_fixture_n_times_exception_counts_as_error_not_crash() -> None:
    def run_once() -> FixtureScore:
        raise RuntimeError("Modell nicht erreichbar")

    aggregate = run_fixture_n_times("fixture-a", run_once, n=3)
    assert len(aggregate.runs) == 3
    assert aggregate.error_rate == 1.0
    assert aggregate.pass_rate == 0.0
    assert all(r.error is not None for r in aggregate.runs)


def test_run_fixture_n_times_median_latency_is_nonnegative() -> None:
    aggregate = run_fixture_n_times("fixture-a", lambda: _PASSING_SCORE, n=3)
    assert aggregate.median_latency_seconds >= 0.0


def test_run_fixture_n_times_max_workers_runs_concurrently() -> None:
    """max_workers > 1 (nur für Cloud-Provider gedacht) parallelisiert tatsächlich."""
    concurrent_count = 0
    max_concurrent = 0
    lock = threading.Lock()

    def run_once() -> FixtureScore:
        nonlocal concurrent_count, max_concurrent
        with lock:
            concurrent_count += 1
            max_concurrent = max(max_concurrent, concurrent_count)
        time.sleep(0.05)
        with lock:
            concurrent_count -= 1
        return _PASSING_SCORE

    aggregate = run_fixture_n_times("fixture-a", run_once, n=4, max_workers=4)
    assert len(aggregate.runs) == 4
    assert aggregate.pass_rate == 1.0
    assert max_concurrent > 1


def test_run_fixture_n_times_max_workers_default_stays_sequential() -> None:
    """Ohne max_workers bleibt das Verhalten unverändert (max_workers=1, seriell)."""
    order: list[int] = []

    def make_run_once(i: int) -> Callable[[], FixtureScore]:
        def run_once() -> FixtureScore:
            order.append(i)
            return _PASSING_SCORE

        return run_once

    calls = [make_run_once(i) for i in range(3)]
    it = iter(calls)
    aggregate = run_fixture_n_times("fixture-a", lambda: next(it)(), n=3)
    assert order == [0, 1, 2]
    assert len(aggregate.runs) == 3
