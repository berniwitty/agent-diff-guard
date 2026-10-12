"""Plain-text report: one line per finding, evidence indented, suppressions, a summary."""

from __future__ import annotations

from agent_diff_guard.engine import Outcome
from agent_diff_guard.rules.base import Finding


def location(finding: Finding) -> str:
    return finding.path if finding.line is None else f"{finding.path}:{finding.line}"


def render(outcome: Outcome) -> str:
    lines = []
    for finding in outcome.findings:
        lines.append(f"{location(finding)}: {finding.severity} {finding.rule_id} {finding.message}")
        lines.extend(f"    {line}" for line in finding.evidence.splitlines())
    if outcome.suppressed:
        lines.append(f"Suppressed ({len(outcome.suppressed)}):")
        for item in outcome.suppressed:
            finding = item.finding
            lines.append(f"  {location(finding)}: {finding.rule_id} {finding.message}")
            lines.append(f'    reason: "{item.reason}"')
    tally = ", ".join(f"{count} {severity}" for severity, count in outcome.counts().items())
    lines.append(
        f"Checked {outcome.files_checked} changed file(s) "
        f"with {len(outcome.rules)} rule(s): {tally}."
    )
    return "\n".join(lines)
