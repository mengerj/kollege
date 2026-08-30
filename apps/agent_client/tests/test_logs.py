"""Tests für das Markdown-Verlaugslog-Modul (Schritt 3).

Alle Tests laufen gegen ``tmp_path`` — kein echtes Dateisystem nötig.
"""

from __future__ import annotations

from pathlib import Path

from kollege.logs import open_project_log
from kollege.models import Project

# --------------------------------------------------------------------------- #
# Hilfsmittel                                                                   #
# --------------------------------------------------------------------------- #


def _project(title: str = "Musterpark", project_id: int | None = None) -> Project:
    return Project(id=project_id, title=title)


# --------------------------------------------------------------------------- #
# open_project_log                                                              #
# --------------------------------------------------------------------------- #


def test_open_creates_file(tmp_path: Path) -> None:
    log = open_project_log(_project(), tmp_path)
    assert log.path.exists()


def test_open_writes_markdown_header(tmp_path: Path) -> None:
    log = open_project_log(_project("Musterpark"), tmp_path)
    content = log.path.read_text()
    assert "# Verlaufslog: Musterpark" in content


def test_open_sets_markdown_log_path(tmp_path: Path) -> None:
    project = _project()
    open_project_log(project, tmp_path)
    assert project.markdown_log_path is not None
    assert Path(project.markdown_log_path).exists()


def test_open_creates_log_dir_if_missing(tmp_path: Path) -> None:
    nested = tmp_path / "sub" / "logs"
    project = _project()
    log = open_project_log(project, nested)
    assert log.path.exists()


def test_open_uses_existing_path(tmp_path: Path) -> None:
    """Wenn markdown_log_path schon gesetzt ist, dieselbe Datei nutzen."""
    project = _project()
    log1 = open_project_log(project, tmp_path)
    original_path = log1.path

    # Zweiter Aufruf mit demselben Projekt-Objekt (Pfad schon gesetzt)
    log2 = open_project_log(project, tmp_path)
    assert log2.path == original_path


def test_open_idempotent_no_duplicate_header(tmp_path: Path) -> None:
    """Zweimal öffnen darf den Header nicht verdoppeln."""
    project = _project()
    open_project_log(project, tmp_path)
    open_project_log(project, tmp_path)
    content = project.markdown_log_path and Path(project.markdown_log_path).read_text()
    assert content is not None
    assert content.count("# Verlaufslog:") == 1


def test_open_filename_includes_id(tmp_path: Path) -> None:
    project = _project("Dorfplatz Beispiel", project_id=42)
    log = open_project_log(project, tmp_path)
    assert "-42" in log.path.name
    assert log.path.suffix == ".md"


def test_open_filename_without_id(tmp_path: Path) -> None:
    project = _project("Neues Projekt")
    log = open_project_log(project, tmp_path)
    assert log.path.suffix == ".md"
    # Kein ID-Suffix, aber Slug vorhanden
    assert "neues" in log.path.name


def test_open_slugify_special_chars(tmp_path: Path) -> None:
    project = _project("Ärger im Ölbad & Co.")
    log = open_project_log(project, tmp_path)
    # Dateiname soll keine Sonderzeichen wie & enthalten
    assert "&" not in log.path.name
    assert log.path.exists()


# --------------------------------------------------------------------------- #
# append_entry                                                                  #
# --------------------------------------------------------------------------- #


def test_append_entry_adds_content(tmp_path: Path) -> None:
    log = open_project_log(_project(), tmp_path)
    log.append_entry("Besprechung mit Frau Müller vereinbart.")
    content = log.path.read_text()
    assert "Besprechung mit Frau Müller vereinbart." in content


def test_append_entry_includes_timestamp_heading(tmp_path: Path) -> None:
    log = open_project_log(_project(), tmp_path)
    log.append_entry("Test-Eintrag")
    content = log.path.read_text()
    # Zeitstempel-Überschrift im Format ## YYYY-MM-DD HH:MM UTC
    assert "## 20" in content


def test_append_entry_with_source(tmp_path: Path) -> None:
    log = open_project_log(_project(), tmp_path)
    log.append_entry("Sprachnotiz eingegangen.", source="sprachnotiz")
    content = log.path.read_text()
    assert "sprachnotiz" in content


def test_append_multiple_entries_all_present(tmp_path: Path) -> None:
    log = open_project_log(_project(), tmp_path)
    log.append_entry("Erster Eintrag")
    log.append_entry("Zweiter Eintrag")
    log.append_entry("Dritter Eintrag")
    content = log.path.read_text()
    assert "Erster Eintrag" in content
    assert "Zweiter Eintrag" in content
    assert "Dritter Eintrag" in content


def test_append_entry_is_append_only(tmp_path: Path) -> None:
    """Früherer Inhalt darf beim Anhängen nicht verloren gehen."""
    log = open_project_log(_project(), tmp_path)
    log.append_entry("Früher Eintrag")
    original_size = log.path.stat().st_size
    log.append_entry("Später Eintrag")
    assert log.path.stat().st_size > original_size


# --------------------------------------------------------------------------- #
# read_recent                                                                   #
# --------------------------------------------------------------------------- #


def test_read_recent_empty_log(tmp_path: Path) -> None:
    log = open_project_log(_project(), tmp_path)
    result = log.read_recent(n=3)
    assert result == ""


def test_read_recent_returns_last_n(tmp_path: Path) -> None:
    log = open_project_log(_project(), tmp_path)
    for i in range(5):
        log.append_entry(f"Eintrag {i}")
    recent = log.read_recent(n=2)
    assert "Eintrag 3" in recent
    assert "Eintrag 4" in recent
    assert "Eintrag 0" not in recent


def test_read_recent_n_larger_than_entries(tmp_path: Path) -> None:
    log = open_project_log(_project(), tmp_path)
    log.append_entry("Nur ein Eintrag")
    result = log.read_recent(n=10)
    assert "Nur ein Eintrag" in result


def test_read_recent_default_five(tmp_path: Path) -> None:
    log = open_project_log(_project(), tmp_path)
    for i in range(7):
        log.append_entry(f"Eintrag {i}")
    recent = log.read_recent()
    # Standard n=5: Einträge 2–6 vorhanden, 0 und 1 nicht
    assert "Eintrag 6" in recent
    assert "Eintrag 2" in recent
    # Einträge 0 und 1 sollen fehlen
    # (Überprüfung über einzelne Zeilen, nicht über Index-Matching)
    lines = recent.splitlines()
    entry_texts = [line for line in lines if line.startswith("Eintrag ")]
    numbers = [int(line.split()[-1]) for line in entry_texts]
    assert 0 not in numbers
    assert 1 not in numbers
