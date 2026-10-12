"""R5 coverage: ADG040 uncovered-change (needs ``--coverage``)."""

from __future__ import annotations

from agent_diff_guard.astutil import source_line
from agent_diff_guard.change import ChangedFile
from agent_diff_guard.rules.base import Finding, RunContext, Severity, registry


class UncoveredChangeRule:
    id = "ADG040"
    name = "uncovered-change"
    default_severity = Severity.INFO

    def check(self, change: ChangedFile, ctx: RunContext) -> list[Finding]:
        if ctx.uncovered_lines is None or change.head_src is None:
            return []
        if not ctx.is_python_source(change.path):
            return []
        lines = sorted(change.added_lines & ctx.uncovered_lines.get(change.path, frozenset()))
        findings = []
        for first, last in _runs(lines):
            what = f"line {first} is" if first == last else f"lines {first}-{last} are"
            findings.append(
                Finding(
                    rule_id=self.id,
                    severity=self.default_severity,
                    path=change.path,
                    line=first,
                    message=f"Added {what} not executed by the test suite.",
                    evidence=source_line(change.head_src, first),
                )
            )
        return findings


def _runs(lines: list[int]) -> list[tuple[int, int]]:
    """Group sorted line numbers into (first, last) runs of consecutive lines."""
    runs: list[tuple[int, int]] = []
    for line in lines:
        if runs and line == runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], line)
        else:
            runs.append((line, line))
    return runs


registry.register(UncoveredChangeRule())
