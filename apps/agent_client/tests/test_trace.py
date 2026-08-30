"""Tests für das Trace-Modul (Schritt 8.21): append-only JSONL, opt-in."""

from __future__ import annotations

import datetime
import json
from pathlib import Path

from kollege.trace import (
    JsonlTraceWriter,
    NoopTraceWriter,
    build_trace_writer,
    new_run_id,
)


def test_noop_writer_writes_nothing(tmp_path: Path) -> None:
    writer = NoopTraceWriter()
    writer.write("message_received", "abc", {"sender": "+49123"})
    assert list(tmp_path.iterdir()) == []


def test_new_run_id_is_unique() -> None:
    assert new_run_id() != new_run_id()


def test_jsonl_writer_creates_todays_file(tmp_path: Path) -> None:
    writer = JsonlTraceWriter(tmp_path)
    writer.write("message_received", "run-1", {"sender": "+49123", "kind": "Text"})

    today = datetime.datetime.now(tz=datetime.UTC).date().isoformat()
    path = tmp_path / f"{today}.jsonl"
    assert path.exists()

    line = json.loads(path.read_text(encoding="utf-8").strip())
    assert line["event"] == "message_received"
    assert line["run_id"] == "run-1"
    assert line["payload"] == {"sender": "+49123", "kind": "Text"}
    assert "ts" in line


def test_jsonl_writer_is_append_only(tmp_path: Path) -> None:
    writer = JsonlTraceWriter(tmp_path)
    writer.write("message_received", "run-1", {"n": 1})
    writer.write("routing", "run-1", {"n": 2})

    today = datetime.datetime.now(tz=datetime.UTC).date().isoformat()
    lines = (tmp_path / f"{today}.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["payload"] == {"n": 1}
    assert json.loads(lines[1])["payload"] == {"n": 2}


def test_jsonl_writer_creates_trace_dir(tmp_path: Path) -> None:
    nested = tmp_path / "traces" / "sub"
    JsonlTraceWriter(nested)
    assert nested.is_dir()


def test_build_trace_writer_disabled_returns_noop(tmp_path: Path) -> None:
    writer = build_trace_writer(enabled=False, trace_dir=str(tmp_path / "traces"))
    assert isinstance(writer, NoopTraceWriter)


def test_build_trace_writer_enabled_returns_jsonl(tmp_path: Path) -> None:
    writer = build_trace_writer(enabled=True, trace_dir=str(tmp_path / "traces"))
    assert isinstance(writer, JsonlTraceWriter)
    assert (tmp_path / "traces").is_dir()
