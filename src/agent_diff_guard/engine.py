"""Build the run context, run rules over it, and turn the result into an exit code."""

from __future__ import annotations

from collections.abc import Iterable

from agent_diff_guard.astutil import assertion_literal_sets, parse
from agent_diff_guard.classify import DEFAULT_TEST_PATTERNS, is_python_file, is_test_file
from agent_diff_guard.git import DiffSpec, Git
from agent_diff_guard.rules.base import Finding, Rule, RunContext, Severity

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2


def build_context(
    git: Git, spec: DiffSpec, test_patterns: tuple[str, ...] = DEFAULT_TEST_PATTERNS
) -> RunContext:
    """Read everything the rules need from git; rules themselves never touch git."""
    changes = git.changed_files(spec)
    test_sources = git.head_sources(
        spec, lambda path: is_python_file(path) and is_test_file(path, test_patterns)
    )
    literal_sets: set[frozenset[str]] = set()
    for source in test_sources.values():
        module = parse(source)
        if module is not None:
            literal_sets |= assertion_literal_sets(module)
    return RunContext(
        changes=tuple(changes),
        test_patterns=test_patterns,
        assertion_literals=frozenset(literal_sets),
    )


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
