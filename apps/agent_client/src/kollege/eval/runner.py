"""N-Wiederholungen pro Fixture + Aggregation — macht Flakiness sichtbar.

Ein einzelner Lauf (wie im ursprünglichen Eval-Set 8.10) kann eine nicht-
deterministisch scheiternde Extraktion nicht von einer zuverlässigen
unterscheiden. Der Runner selbst kennt keine LLM-Details — ``run_once``
kapselt den kompletten Aufruf (Extraktion **oder** Revision) für einen Durchlauf.
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from kollege.eval.scoring import FixtureScore

DEFAULT_THRESHOLD = 0.5


@dataclass(frozen=True)
class RunResult:
    """Ergebnis eines einzelnen Durchlaufs (``score`` ist None bei einer Exception)."""

    score: FixtureScore | None
    latency_seconds: float
    error: str | None = None


@dataclass
class FixtureAggregate:
    """Aggregation über ``N`` Wiederholungen eines Fixtures."""

    fixture_id: str
    runs: list[RunResult] = field(default_factory=list)
    threshold: float = DEFAULT_THRESHOLD

    @property
    def pass_rate(self) -> float:
        return self._rate(lambda r: r.score is not None and r.score.passed(self.threshold))

    @property
    def mean_score(self) -> float:
        scored = [r.score.score for r in self.runs if r.score is not None]
        return statistics.mean(scored) if scored else 0.0

    @property
    def empty_rate(self) -> float:
        return self._rate(lambda r: r.score is not None and r.score.empty)

    @property
    def over_extraction_rate(self) -> float:
        return self._rate(lambda r: r.score is not None and r.score.over_extraction)

    @property
    def forbidden_hit_rate(self) -> float:
        return self._rate(lambda r: r.score is not None and r.score.forbidden_hit)

    @property
    def error_rate(self) -> float:
        return self._rate(lambda r: r.error is not None)

    @property
    def median_latency_seconds(self) -> float:
        latencies = [r.latency_seconds for r in self.runs]
        return statistics.median(latencies) if latencies else 0.0

    def _rate(self, predicate: Callable[[RunResult], bool]) -> float:
        if not self.runs:
            return 0.0
        return sum(1 for r in self.runs if predicate(r)) / len(self.runs)


def _timed_run(run_once: Callable[[], FixtureScore]) -> RunResult:
    start = time.monotonic()
    try:
        score = run_once()
        return RunResult(score=score, latency_seconds=time.monotonic() - start)
    except Exception as exc:  # Modell-/Netzfehler sollen den Lauf nicht abbrechen
        return RunResult(score=None, latency_seconds=time.monotonic() - start, error=str(exc))


def run_fixture_n_times(
    fixture_id: str,
    run_once: Callable[[], FixtureScore],
    n: int,
    threshold: float = DEFAULT_THRESHOLD,
    max_workers: int = 1,
) -> FixtureAggregate:
    """Führt ``run_once`` ``n``-mal aus und misst Latenz.

    Ein transienter Fehler (Modell/Netz) bricht den Gesamtlauf nicht ab — er
    zählt als gescheiterter Durchlauf (sichtbar über ``error_rate``), damit ein
    einzelner Ausreißer nicht den kompletten Benchmark stoppt.

    ``max_workers`` > 1 parallelisiert die Wiederholungen über Threads — sinnvoll
    nur für netzwerkgebundene Cloud-Provider. Ein lokaler Ollama-Server mit einer
    GPU verarbeitet ohnehin nur eine Anfrage gleichzeitig; parallele Anfragen
    würden dort nur um dieselbe Ressource konkurrieren, ohne Zeit zu sparen
    (siehe ``scripts/benchmark_models.py``, das ``max_workers`` deshalb nur für
    Nicht-Ollama-Provider setzt).
    """
    if max_workers <= 1:
        runs = [_timed_run(run_once) for _ in range(n)]
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(_timed_run, run_once) for _ in range(n)]
            runs = [f.result() for f in futures]
    return FixtureAggregate(fixture_id=fixture_id, runs=runs, threshold=threshold)
