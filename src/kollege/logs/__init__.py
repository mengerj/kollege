"""Markdown-Verlaufslogs pro Projekt.

Eine Markdown-Datei pro Projekt, append-only, menschenlesbar.
Pfad wird in ``Project.markdown_log_path`` abgelegt; der Aufrufer ist
verantwortlich, das Projekt via Repository zu persistieren.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from kollege.models import Project

__all__ = ["ProjectLog", "open_project_log"]


def _slugify(text: str) -> str:
    """Projekttitel in einen dateisystem-sicheren Slug umwandeln."""
    slug = text.lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = slug.strip("-")
    return slug or "projekt"


def _log_filename(project: Project) -> str:
    slug = _slugify(project.title)
    if project.id is not None:
        return f"{slug}-{project.id}.md"
    return f"{slug}.md"


class ProjectLog:
    """Append-only Markdown-Verlaufslog für ein Projekt."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def append_entry(self, text: str, source: str | None = None) -> None:
        """Eintrag mit UTC-Zeitstempel anhängen."""
        now = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M UTC")
        lines: list[str] = [f"\n## {now}"]
        if source is not None:
            lines.append(f"*Quelle: {source}*\n")
        lines.append(text.rstrip())
        lines.append("\n---")
        entry = "\n".join(lines) + "\n"
        with self._path.open("a", encoding="utf-8") as f:
            f.write(entry)

    def read_recent(self, n: int = 5) -> str:
        """Die letzten *n* Einträge als String zurückgeben (für Agenten-Kontext)."""
        content = self._path.read_text(encoding="utf-8")
        # Einträge trennen: jede Zeitstempel-Überschrift beginnt mit "## YYYY-"
        sections = re.split(r"\n(?=## \d{4}-\d{2}-\d{2})", content)
        # Erster Abschnitt ist der Datei-Header, Rest sind Einträge
        entries = sections[1:] if len(sections) > 1 else []
        return "\n".join(entries[-n:])


def open_project_log(project: Project, log_dir: Path) -> ProjectLog:
    """Verlaufslog für ein Projekt öffnen oder anlegen.

    - Legt ``log_dir`` an falls nicht vorhanden.
    - Erstellt die Markdown-Datei mit Header beim ersten Aufruf.
    - Setzt ``project.markdown_log_path`` auf den Pfad der Log-Datei.

    Der Aufrufer muss das Projekt via ``Repository.update_project`` persistieren.
    """
    log_dir.mkdir(parents=True, exist_ok=True)

    if project.markdown_log_path is not None:
        path = Path(project.markdown_log_path)
    else:
        path = log_dir / _log_filename(project)

    if not path.exists():
        header = f"# Verlaufslog: {project.title}\n\n---\n"
        path.write_text(header, encoding="utf-8")

    project.markdown_log_path = str(path)
    return ProjectLog(path)
