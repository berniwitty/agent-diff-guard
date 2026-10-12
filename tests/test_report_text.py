from __future__ import annotations

from agent_diff_guard.report.text import render
from agent_diff_guard.rules.base import Finding, Severity


def test_render_findings_with_and_without_line_and_evidence() -> None:
    findings = [
        Finding("ADG010", Severity.ERROR, "src/a.py", 3, "Stubbed.", "return 1 -> pass"),
        Finding("ADG001", Severity.ERROR, "tests/test_b.py", None, "Removed.", ""),
        Finding("ADG020", Severity.WARN, "src/c.py", 7, "Suppressed.", "first\nsecond"),
    ]

    assert render(findings, files_checked=4, rules_run=3).splitlines() == [
        "src/a.py:3: error ADG010 Stubbed.",
        "    return 1 -> pass",
        "tests/test_b.py: error ADG001 Removed.",
        "src/c.py:7: warn ADG020 Suppressed.",
        "    first",
        "    second",
        "Checked 4 changed file(s) with 3 rule(s): 2 error, 1 warn, 0 info.",
    ]


def test_render_no_findings() -> None:
    assert render([], files_checked=0, rules_run=3) == (
        "Checked 0 changed file(s) with 3 rule(s): 0 error, 0 warn, 0 info."
    )
