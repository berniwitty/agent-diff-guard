from __future__ import annotations

from pathlib import Path

import pytest

from agent_diff_guard.coverage_report import CoverageReportError, load_coverage


def report(tmp_path: Path, sources: list[str], classes: str) -> Path:
    source_xml = "".join(f"<source>{source}</source>" for source in sources)
    path = tmp_path / "coverage.xml"
    path.write_text(
        f'<?xml version="1.0" ?><coverage><sources>{source_xml}</sources>'
        f"<packages><package><classes>{classes}</classes></package></packages></coverage>",
        encoding="utf-8",
    )
    return path


LINES = (
    '<lines><line number="1" hits="3"/><line number="2" hits="0"/>'
    '<line number="4" hits="0"/></lines>'
)


def test_absolute_source_under_repo(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    xml = report(tmp_path, [str(repo / "src")], f'<class filename="pkg/mod.py">{LINES}</class>')

    assert load_coverage(xml, repo) == {"src/pkg/mod.py": frozenset({2, 4})}


def test_relative_source_and_fallback_order(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "elsewhere"
    xml = report(
        tmp_path,
        [str(outside), "."],
        f'<class filename="src/a.py">{LINES}</class>'
        f'<class filename="../b.py">{LINES}</class>'
        f"<class>{LINES}</class>",
    )

    assert load_coverage(xml, repo) == {"src/a.py": frozenset({2, 4})}


def test_no_sources_uses_filename_and_ignores_bad_lines(tmp_path: Path) -> None:
    path = tmp_path / "coverage.xml"
    path.write_text(
        '<coverage><class filename="./x.py"><lines>'
        '<line number="5" hits="0"/><line number="abc" hits="0"/><line hits="0"/>'
        '<line number="6" hits="1"/></lines></class></coverage>',
        encoding="utf-8",
    )

    assert load_coverage(path, tmp_path) == {"x.py": frozenset({5})}


def test_unreadable_reports(tmp_path: Path) -> None:
    with pytest.raises(CoverageReportError, match="cannot read coverage report"):
        load_coverage(tmp_path / "missing.xml", tmp_path)
    broken = tmp_path / "broken.xml"
    broken.write_text("<coverage>", encoding="utf-8")
    with pytest.raises(CoverageReportError, match="cannot read coverage report"):
        load_coverage(broken, tmp_path)
    other = tmp_path / "other.xml"
    other.write_text("<testsuite/>", encoding="utf-8")
    with pytest.raises(CoverageReportError, match="is not a Cobertura XML coverage report"):
        load_coverage(other, tmp_path)
