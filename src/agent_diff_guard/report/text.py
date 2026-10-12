"""Plain-text report: one line per finding, evidence indented, then a summary."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from agent_diff_guard.rules.base import Finding, Severity


def render(findings: Sequence[Finding], files_checked: int, rules_run: int) -> str:
    lines = []
    for finding in findings:
        where = finding.path if finding.line is None else f"{finding.path}:{finding.line}"
        lines.append(f"{where}: {finding.severity} {finding.rule_id} {finding.message}")
        lines.extend(f"    {line}" for line in finding.evidence.splitlines())
    counts = Counter(finding.severity for finding in findings)
    tally = ", ".join(f"{counts[severity]} {severity}" for severity in reversed(Severity))
    lines.append(f"Checked {files_checked} changed file(s) with {rules_run} rule(s): {tally}.")
    return "\n".join(lines)
