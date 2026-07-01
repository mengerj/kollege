"""Schritt-8.11-Benchmark: mehrere Modelle auf Extraktions-/Revisions-Qualität vergleichen.

Nutzt exakt den Produktions-Pfad (``run_extraction`` / ``run_revision``) —
misst also, was live passiert, inklusive Primär-→Fallback-Verhalten. Läuft
``N``-mal pro Fixture (Standard 5), damit Flakiness sichtbar wird statt in
einem einzelnen Glückstreffer zu verschwinden.

Aufruf:
    uv run python scripts/benchmark_models.py \\
        --models ornith:9b,qwen2.5:7b-instruct \\
        --runs 5 \\
        --suite extraction,revision

Modell-Syntax: "modell" (Standard-Provider ollama) oder "provider:modell"
(``ollama`` | ``anthropic`` | ``openai`` | ``openrouter``), z. B.
``openrouter:mistralai/mistral-large``. Details + Beispiele: docs/benchmark.md.

Für netzwerkgebundene Cloud-Provider (z. B. openrouter) kann ``--concurrency N``
die Wiederholungen pro Fixture parallelisieren (Standard: 1 = seriell). Bei
``ollama`` wird das ignoriert — ein lokaler GPU-Server verarbeitet ohnehin nur
eine Anfrage gleichzeitig.

Ergebnisse landen als kompakte Markdown-Zusammenfassung in
``benchmarks/results/<datum>_<modell>.md`` (eingecheckt, für Regressions-/
Fortschritts-Tracking über Modell-Versionen hinweg).
"""

from __future__ import annotations

import argparse
import datetime
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from kollege.agent import build_known_names_context, run_extraction, run_revision
from kollege.config import LLMProvider, Settings
from kollege.db import Repository
from kollege.eval import (
    DEFAULT_THRESHOLD,
    ExtractionFixture,
    FixtureAggregate,
    FixtureScore,
    RevisionFixture,
    load_extraction_fixtures,
    load_revision_fixtures,
    run_fixture_n_times,
    score_result,
)

_REPO_ROOT = Path(__file__).parent.parent
_EXTRACTION_DIR = _REPO_ROOT / "tests" / "fixtures" / "eval"
_REVISION_DIR = _REPO_ROOT / "tests" / "fixtures" / "eval_revision"
_DEFAULT_RESULTS_DIR = _REPO_ROOT / "benchmarks" / "results"

_KNOWN_PROVIDERS = {p.value for p in LLMProvider}


def _parse_model_spec(spec: str) -> tuple[LLMProvider, str]:
    """ "modell" → (ollama, modell); "provider:modell" → (provider, modell)."""
    provider_str, sep, rest = spec.partition(":")
    if sep and provider_str in _KNOWN_PROVIDERS:
        return LLMProvider(provider_str), rest
    return LLMProvider.OLLAMA, spec


def _settings_for(spec: str) -> Settings:
    provider, model = _parse_model_spec(spec)
    return Settings(llm_provider=provider, llm_model=model)


def _make_repo() -> Repository:
    return Repository(sqlite3.connect(":memory:", check_same_thread=False))


def _bench_extraction(
    fixture: ExtractionFixture,
    settings: Settings,
    runs: int,
    threshold: float,
    max_workers: int,
) -> FixtureAggregate:
    def run_once() -> FixtureScore:
        result = run_extraction(fixture.transcript, _make_repo(), settings)
        return score_result(result, fixture.expected)

    return run_fixture_n_times(
        fixture.id, run_once, n=runs, threshold=threshold, max_workers=max_workers
    )


def _bench_revision(
    fixture: RevisionFixture,
    settings: Settings,
    runs: int,
    threshold: float,
    max_workers: int,
) -> FixtureAggregate:
    known_context = (
        build_known_names_context(fixture.known_names, []) if fixture.known_names else None
    )

    def run_once() -> FixtureScore:
        result = run_revision(
            fixture.original_transcript,
            fixture.current_result,
            fixture.correction,
            settings,
            known_names_context=known_context,
        )
        return score_result(result, fixture.expected)

    return run_fixture_n_times(
        fixture.id, run_once, n=runs, threshold=threshold, max_workers=max_workers
    )


def _overall(aggregates: list[FixtureAggregate]) -> dict[str, float]:
    if not aggregates:
        return {
            "pass_rate": 0.0,
            "mean_score": 0.0,
            "empty_rate": 0.0,
            "over_extraction_rate": 0.0,
        }
    n = len(aggregates)
    return {
        "pass_rate": sum(a.pass_rate for a in aggregates) / n,
        "mean_score": sum(a.mean_score for a in aggregates) / n,
        "empty_rate": sum(a.empty_rate for a in aggregates) / n,
        "over_extraction_rate": sum(a.over_extraction_rate for a in aggregates) / n,
    }


_TABLE_HEADER = (
    f"{'Fixture':<32} {'pass':>6} {'score':>6} {'empty':>6} {'over':>6} {'err':>6} {'lat(s)':>7}"
)


def _print_suite_table(suite_name: str, aggregates: list[FixtureAggregate]) -> None:
    print(f"\n--- {suite_name} ---")
    print(_TABLE_HEADER)
    print("-" * len(_TABLE_HEADER))
    for agg in aggregates:
        print(
            f"{agg.fixture_id:<32} {agg.pass_rate:>6.0%} {agg.mean_score:>6.0%} "
            f"{agg.empty_rate:>6.0%} {agg.over_extraction_rate:>6.0%} {agg.error_rate:>6.0%} "
            f"{agg.median_latency_seconds:>7.1f}"
        )
    overall = _overall(aggregates)
    print("-" * len(_TABLE_HEADER))
    print(
        f"{'GESAMT':<32} {overall['pass_rate']:>6.0%} {overall['mean_score']:>6.0%} "
        f"{overall['empty_rate']:>6.0%} {overall['over_extraction_rate']:>6.0%}"
    )


def _write_markdown(
    model_spec: str,
    runs: int,
    today: str,
    results: dict[str, list[FixtureAggregate]],
    results_dir: Path,
) -> Path:
    results_dir.mkdir(parents=True, exist_ok=True)
    safe_name = model_spec.replace("/", "-").replace(":", "-")
    path = results_dir / f"{today}_{safe_name}.md"

    lines = [f"# Benchmark: {model_spec}", "", f"Datum: {today}", f"Runs pro Fixture: {runs}", ""]
    for suite_name, aggregates in results.items():
        lines.append(f"## {suite_name.capitalize()}")
        lines.append("")
        lines.append(
            "| Fixture | pass_rate | mean_score | empty_rate "
            "| over_extraction_rate | error_rate | median_latency_s |"
        )
        lines.append("|---|---|---|---|---|---|---|")
        for agg in aggregates:
            lines.append(
                f"| {agg.fixture_id} | {agg.pass_rate:.0%} | {agg.mean_score:.0%} | "
                f"{agg.empty_rate:.0%} | {agg.over_extraction_rate:.0%} | {agg.error_rate:.0%} | "
                f"{agg.median_latency_seconds:.1f} |"
            )
        overall = _overall(aggregates)
        lines.append(
            f"| **GESAMT** | **{overall['pass_rate']:.0%}** | **{overall['mean_score']:.0%}** | "
            f"**{overall['empty_rate']:.0%}** | **{overall['over_extraction_rate']:.0%}** | | |"
        )
        lines.append("")

    path.write_text("\n".join(lines))
    return path


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--models",
        required=True,
        help="Kommagetrennte Modell-Liste, z. B. 'ornith:9b,qwen2.5:7b-instruct' "
        "oder 'provider:modell' (siehe Modulkommentar).",
    )
    parser.add_argument(
        "--runs", type=int, default=5, help="Wiederholungen pro Fixture (Standard: 5)."
    )
    parser.add_argument(
        "--suite",
        default="extraction,revision",
        help="Kommagetrennt: 'extraction', 'revision' oder beides (Standard).",
    )
    parser.add_argument(
        "--out", default=str(_DEFAULT_RESULTS_DIR), help="Ausgabeverzeichnis für die Historie."
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=f"Trefferquoten-Schwellenwert für pass_rate (Standard: {DEFAULT_THRESHOLD}).",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Parallele Wiederholungen pro Fixture (Standard: 1 = seriell). Nur für "
        "netzwerkgebundene Cloud-Provider (z. B. openrouter) sinnvoll — für ollama "
        "wird immer seriell gefahren (ein lokaler GPU-Server profitiert nicht von "
        "parallelen Anfragen, siehe docs/benchmark.md).",
    )
    args = parser.parse_args()

    results_dir = Path(args.out)
    model_specs = [m.strip() for m in args.models.split(",") if m.strip()]
    suites = [s.strip() for s in args.suite.split(",") if s.strip()]

    extraction_fixtures = (
        load_extraction_fixtures(_EXTRACTION_DIR) if "extraction" in suites else []
    )
    revision_fixtures = load_revision_fixtures(_REVISION_DIR) if "revision" in suites else []

    today = datetime.date.today().isoformat()
    matrix: dict[str, dict[str, float]] = {}

    for spec in model_specs:
        provider, _ = _parse_model_spec(spec)
        settings = _settings_for(spec)
        max_workers = args.concurrency if provider != LLMProvider.OLLAMA else 1
        print(f"\n=== Modell: {spec} ===")
        if args.concurrency > 1 and provider == LLMProvider.OLLAMA:
            print(f"  (--concurrency {args.concurrency} ignoriert: ollama läuft seriell)")

        results: dict[str, list[FixtureAggregate]] = {}
        if extraction_fixtures:
            results["extraction"] = [
                _bench_extraction(f, settings, args.runs, args.threshold, max_workers)
                for f in extraction_fixtures
            ]
        if revision_fixtures:
            results["revision"] = [
                _bench_revision(f, settings, args.runs, args.threshold, max_workers)
                for f in revision_fixtures
            ]

        for suite_name, aggregates in results.items():
            _print_suite_table(suite_name, aggregates)
            matrix.setdefault(spec, {})[suite_name] = _overall(aggregates)["pass_rate"]

        path = _write_markdown(spec, args.runs, today, results, results_dir)
        print(f"\n→ Historie geschrieben: {path}")

    print("\n=== Vergleichs-Matrix (pass_rate) ===")
    suite_names = sorted({s for per_model in matrix.values() for s in per_model})
    header = f"{'Modell':<32}" + "".join(f"{s:>14}" for s in suite_names)
    print(header)
    print("-" * len(header))
    for spec, per_model in matrix.items():
        row = f"{spec:<32}" + "".join(f"{per_model.get(s, 0.0):>14.0%}" for s in suite_names)
        print(row)


if __name__ == "__main__":
    main()
