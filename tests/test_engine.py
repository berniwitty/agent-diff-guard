from __future__ import annotations

from collections.abc import Iterable

from agent_diff_guard.change import ChangedFile, FileStatus
from agent_diff_guard.engine import EXIT_FINDINGS, EXIT_OK, exit_code, run_rules
from agent_diff_guard.rules.base import Finding, RunContext, Severity


class FlagEveryFile:
    """Reports one finding per changed file, at the first added line."""

    def __init__(self, rule_id: str, severity: Severity) -> None:
        self.id = rule_id
        self.name = "flag-every-file"
        self.default_severity = severity

    def check(self, change: ChangedFile, ctx: RunContext) -> Iterable[Finding]:
        line = min(change.added_lines) if change.added_lines else None
        yield Finding(self.id, self.default_severity, change.path, line, "flagged", "")


def make_change(path: str, *added: int) -> ChangedFile:
    return ChangedFile(path, FileStatus.MODIFIED, "", "", added_lines=frozenset(added))


def test_run_rules_applies_every_rule_to_every_change_sorted() -> None:
    ctx = RunContext(changes=(make_change("b.py", 5), make_change("a.py", 9), make_change("a.py")))
    rules = [FlagEveryFile("ADG020", Severity.WARN), FlagEveryFile("ADG002", Severity.ERROR)]

    findings = run_rules(rules, ctx)

    assert [(f.path, f.line, f.rule_id) for f in findings] == [
        ("a.py", None, "ADG002"),
        ("a.py", None, "ADG020"),
        ("a.py", 9, "ADG002"),
        ("a.py", 9, "ADG020"),
        ("b.py", 5, "ADG002"),
        ("b.py", 5, "ADG020"),
    ]


def test_run_rules_with_no_changes_returns_nothing() -> None:
    assert run_rules([FlagEveryFile("ADG002", Severity.ERROR)], RunContext()) == []


def finding(severity: Severity) -> Finding:
    return Finding("ADG000", severity, "a.py", 1, "m", "e")


def test_exit_code_fails_only_at_or_above_threshold() -> None:
    warn_only = [finding(Severity.WARN), finding(Severity.INFO)]

    assert exit_code(warn_only, Severity.ERROR) == EXIT_OK
    assert exit_code(warn_only, Severity.WARN) == EXIT_FINDINGS
    assert exit_code([finding(Severity.ERROR)], Severity.ERROR) == EXIT_FINDINGS
    assert exit_code([], Severity.INFO) == EXIT_OK
