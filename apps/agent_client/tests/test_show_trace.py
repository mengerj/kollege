"""Tests für den Trace-Viewer (Schritt 8.21): reine Parse-/Format-Funktionen.

Kein LLM, kein echter Prozessaufruf — importiert das Skript als Modul (analog
zu ``scripts/benchmark_models.py``, das denselben ``sys.path``-Trick nutzt).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).parent.parent / "scripts" / "show_trace.py"


def _load_module() -> object:
    spec = importlib.util.spec_from_file_location("show_trace", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


show_trace = _load_module()


def test_load_events_reads_specific_date(tmp_path: Path) -> None:
    (tmp_path / "2026-07-02.jsonl").write_text(
        '{"ts": "t1", "event": "message_received", "run_id": "r1", "payload": {}}\n',
        encoding="utf-8",
    )
    (tmp_path / "2026-07-03.jsonl").write_text(
        '{"ts": "t2", "event": "message_received", "run_id": "r2", "payload": {}}\n',
        encoding="utf-8",
    )
    events = show_trace.load_events(tmp_path, "2026-07-02")  # type: ignore[attr-defined]
    assert len(events) == 1
    assert events[0]["run_id"] == "r1"


def test_load_events_without_date_reads_all_files_sorted(tmp_path: Path) -> None:
    (tmp_path / "2026-07-03.jsonl").write_text(
        '{"ts": "t2", "event": "e", "run_id": "r2", "payload": {}}\n', encoding="utf-8"
    )
    (tmp_path / "2026-07-02.jsonl").write_text(
        '{"ts": "t1", "event": "e", "run_id": "r1", "payload": {}}\n', encoding="utf-8"
    )
    events = show_trace.load_events(tmp_path, None)  # type: ignore[attr-defined]
    assert [e["run_id"] for e in events] == ["r1", "r2"]  # alphabetisch = chronologisch


def test_load_events_missing_file_returns_empty(tmp_path: Path) -> None:
    events = show_trace.load_events(tmp_path, "2026-01-01")  # type: ignore[attr-defined]
    assert events == []


def test_filter_by_run(tmp_path: Path) -> None:
    events = [
        {"run_id": "a", "event": "x"},
        {"run_id": "b", "event": "y"},
        {"run_id": "a", "event": "z"},
    ]
    filtered = show_trace.filter_by_run(events, "a")  # type: ignore[attr-defined]
    assert [e["event"] for e in filtered] == ["x", "z"]


def test_filter_last_n_runs_keeps_most_recent_run_ids() -> None:
    events = [
        {"run_id": "a", "event": "1"},
        {"run_id": "a", "event": "2"},
        {"run_id": "b", "event": "3"},
        {"run_id": "c", "event": "4"},
    ]
    filtered = show_trace.filter_last_n_runs(events, 1)  # type: ignore[attr-defined]
    assert {e["run_id"] for e in filtered} == {"c"}

    filtered_two = show_trace.filter_last_n_runs(events, 2)  # type: ignore[attr-defined]
    assert {e["run_id"] for e in filtered_two} == {"b", "c"}


def test_truncate_short_text_unchanged() -> None:
    assert show_trace._truncate("kurz", full=False) == "kurz"  # type: ignore[attr-defined]


def test_truncate_long_text_is_shortened() -> None:
    text = "x" * 500
    truncated = show_trace._truncate(text, full=False)  # type: ignore[attr-defined]
    assert len(truncated) < len(text)
    assert "--full" in truncated


def test_truncate_full_flag_keeps_everything() -> None:
    text = "x" * 500
    assert show_trace._truncate(text, full=True) == text  # type: ignore[attr-defined]


def test_format_event_message_received() -> None:
    event = {
        "ts": "2026-07-02T10:00:00",
        "event": "message_received",
        "run_id": "r1",
        "payload": {"sender": "+49123", "kind": "Text", "text": "Hallo"},
    }
    out = show_trace.format_event(event, full=True)  # type: ignore[attr-defined]
    assert "message_received" in out
    assert "+49123" in out
    assert "Hallo" in out


def test_format_event_llm_run_result_shows_tokens_and_output() -> None:
    event = {
        "ts": "t",
        "event": "llm_run_result",
        "run_id": "r1",
        "payload": {
            "kind": "extraktion",
            "path": "primär",
            "latency_s": 1.23,
            "usage": {"input_tokens": 10, "output_tokens": 5, "requests": 1},
            "output": {"tasks": [{"title": "Testaufgabe"}]},
            "messages": [],
        },
    }
    out = show_trace.format_event(event, full=True)  # type: ignore[attr-defined]
    assert "primär" in out
    assert "input=10" in out
    assert "Testaufgabe" in out


def test_format_event_llm_run_error_shows_exception() -> None:
    event = {
        "ts": "t",
        "event": "llm_run_error",
        "run_id": "r1",
        "payload": {
            "kind": "extraktion",
            "path": "primär",
            "latency_s": 0.5,
            "exception_type": "UnexpectedModelBehavior",
            "exception_text": "kaputt",
            "messages": [],
        },
    }
    out = show_trace.format_event(event, full=True)  # type: ignore[attr-defined]
    assert "UnexpectedModelBehavior" in out
    assert "kaputt" in out


def test_format_event_llm_run_result_renders_tool_calls() -> None:
    event = {
        "ts": "t",
        "event": "llm_run_result",
        "run_id": "r1",
        "payload": {
            "kind": "extraktion",
            "path": "primär",
            "latency_s": 0.1,
            "usage": {"input_tokens": 1, "output_tokens": 1, "requests": 1},
            "output": {},
            "messages": [
                {
                    "kind": "response",
                    "parts": [
                        {
                            "part_kind": "tool-call",
                            "tool_name": "create_task",
                            "args": '{"title": "X"}',
                        }
                    ],
                },
                {
                    "kind": "request",
                    "parts": [
                        {
                            "part_kind": "tool-return",
                            "tool_name": "create_task",
                            "content": "Aufgabe angelegt",
                        }
                    ],
                },
            ],
        },
    }
    out = show_trace.format_event(event, full=True)  # type: ignore[attr-defined]
    assert "Tool-Call create_task" in out
    assert "Tool-Return create_task" in out
    assert "Aufgabe angelegt" in out


def test_format_event_persisted_and_rejected() -> None:
    persisted_event = {
        "ts": "t",
        "event": "persisted",
        "run_id": "r1",
        "payload": {"count": 2, "labels": ["a", "b"]},
    }
    persisted = show_trace.format_event(persisted_event, full=True)  # type: ignore[attr-defined]
    assert "2 Eintrag" in persisted

    rejected = show_trace.format_event(  # type: ignore[attr-defined]
        {"ts": "t", "event": "rejected", "run_id": "r1", "payload": {}}, full=True
    )
    assert "Verworfen" in rejected


def test_main_reports_missing_trace_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from kollege.config import Settings

    monkeypatch.setattr(
        show_trace,
        "load_settings",
        lambda: Settings.model_construct(trace_dir=str(tmp_path / "does-not-exist")),
    )
    code = show_trace.main([])  # type: ignore[attr-defined]
    assert code == 1


def test_main_run_filter_reports_when_nothing_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kollege.config import Settings

    trace_dir = tmp_path / "traces"
    trace_dir.mkdir()
    monkeypatch.setattr(
        show_trace, "load_settings", lambda: Settings.model_construct(trace_dir=str(trace_dir))
    )
    code = show_trace.main(["--run", "does-not-exist"])  # type: ignore[attr-defined]
    assert code == 1
