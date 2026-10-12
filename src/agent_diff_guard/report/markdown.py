"""Markdown summary, for a pull-request comment or a CI job summary."""

from __future__ import annotations

from agent_diff_guard.engine import Outcome
from agent_diff_guard.report.text import location


def _cell(text: str) -> str:
    """Make ``text`` safe inside a single table cell."""
    return " ".join(text.split()).replace("|", "\\|")


def render(outcome: Outcome) -> str:
    tally = ", ".join(f"{count} {severity}" for severity, count in outcome.counts().items())
    lines = [
        "## agent-diff-guard",
        "",
        f"**{tally}** in {outcome.files_checked} changed file(s), "
        f"{len(outcome.rules)} rule(s) checked.",
    ]
    if outcome.findings:
        lines += [
            "",
            "| Severity | Rule | Location | Finding | Evidence |",
            "|---|---|---|---|---|",
        ]
        lines += [
            f"| {f.severity} | {f.rule_id} | `{_cell(location(f))}` | {_cell(f.message)} "
            f"| `{_cell(f.evidence)}` |"
            for f in outcome.findings
        ]
    if outcome.suppressed:
        lines += [
            "",
            f"### Suppressed ({len(outcome.suppressed)})",
            "",
            "| Rule | Location | Finding | Reason |",
            "|---|---|---|---|",
        ]
        lines += [
            f"| {s.finding.rule_id} | `{_cell(location(s.finding))}` "
            f"| {_cell(s.finding.message)} | {_cell(s.reason)} |"
            for s in outcome.suppressed
        ]
    return "\n".join(lines) + "\n"
