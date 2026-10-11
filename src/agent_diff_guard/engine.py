"""Run rules over a set of changes and turn the result into an exit code."""

from __future__ import annotations

from collections.abc import Iterable

from agent_diff_guard.rules.base import Finding, Rule, RunContext, Severity

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2


def run_rules(rules: Iterable[Rule], ctx: RunContext) -> list[Finding]:
    rule_list = list(rules)
    findings = [
        finding
        for change in ctx.changes
        for rule in rule_list
        for finding in rule.check(change, ctx)
    ]
    return sorted(findings, key=lambda f: (f.path, f.line or 0, f.rule_id))


def exit_code(findings: Iterable[Finding], fail_on: Severity) -> int:
    if any(finding.severity.at_least(fail_on) for finding in findings):
        return EXIT_FINDINGS
    return EXIT_OK
