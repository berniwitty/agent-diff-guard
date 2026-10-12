"""Read a Cobertura XML coverage report (``coverage xml``) into uncovered lines per path."""

from __future__ import annotations

import xml.etree.ElementTree as ElementTree
from pathlib import Path, PurePosixPath


class CoverageReportError(Exception):
    """The coverage report cannot be read or is not Cobertura XML."""


def load_coverage(report: Path, repo_root: Path) -> dict[str, frozenset[int]]:
    """Map repository-relative POSIX paths to measured lines with zero hits."""
    try:
        tree = ElementTree.parse(report)
    except (OSError, ElementTree.ParseError) as exc:
        raise CoverageReportError(f"cannot read coverage report {report}: {exc}") from exc
    root = tree.getroot()
    if root.tag != "coverage":
        raise CoverageReportError(f"{report} is not a Cobertura XML coverage report")
    sources = [(source.text or "").strip() for source in root.iter("source")] or [""]
    uncovered: dict[str, set[int]] = {}
    for cls in root.iter("class"):
        filename = cls.get("filename")
        if not filename:
            continue
        path = _repo_path(filename, sources, repo_root.resolve())
        if path is None:
            continue
        missed = uncovered.setdefault(path, set())
        for line in cls.iter("line"):
            number, hits = line.get("number"), line.get("hits")
            if number is not None and number.isdigit() and hits == "0":
                missed.add(int(number))
    return {path: frozenset(lines) for path, lines in uncovered.items()}


def _repo_path(filename: str, sources: list[str], repo_root: Path) -> str | None:
    """Resolve ``filename`` against the report's sources to a path inside the repo."""
    for source in sources:
        candidate = Path(source) / filename if source else Path(filename)
        if candidate.is_absolute():
            try:
                return candidate.resolve().relative_to(repo_root).as_posix()
            except ValueError:
                continue
        parts = PurePosixPath(candidate.as_posix()).parts
        if ".." not in parts:
            return PurePosixPath(*[part for part in parts if part != "."]).as_posix()
    return None
