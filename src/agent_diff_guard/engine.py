"""Build the run context, run rules over it, and turn the result into an exit code."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from agent_diff_guard.astutil import assertion_literal_sets, parse
from agent_diff_guard.classify import DEFAULT_TEST_PATTERNS, is_python_file, is_test_file
from agent_diff_guard.config import Config, parse_config
from agent_diff_guard.coverage_report import load_coverage
from agent_diff_guard.git import DiffSpec, Git
from agent_diff_guard.rules.base import Finding, Rule, RunContext, Severity
from agent_diff_guard.suppress import Suppressed, apply_suppressions

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2

CONFIG_FILE = "pyproject.toml"


@dataclass(frozen=True)
class Outcome:
    """Everything a report needs: what was found, what was suppressed, what was run."""

    findings: tuple[Finding, ...]
    suppressed: tuple[Suppressed, ...]
    files_checked: int
    rules: tuple[Rule, ...]

    def counts(self) -> dict[Severity, int]:
        counter = Counter(finding.severity for finding in self.findings)
        return {severity: counter[severity] for severity in reversed(Severity)}


def load_config(git: Git, spec: DiffSpec, known_rules: Iterable[str]) -> Config:
    """Configuration as of the base revision, so a change cannot loosen its own checks."""
    text = git.read_at(spec.base, CONFIG_FILE)
    if text is None:
        return Config()
    return parse_config(text, known_rules, f"{CONFIG_FILE} at {spec.base[:12]}")


def build_context(
    git: Git,
    spec: DiffSpec,
    test_patterns: tuple[str, ...] = DEFAULT_TEST_PATTERNS,
    uncovered: Mapping[str, frozenset[int]] | None = None,
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
        uncovered_lines=uncovered,
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


def evaluate(rules: Iterable[Rule], ctx: RunContext, config: Config) -> Outcome:
    """Run enabled rules, then apply exclusions, severity overrides and inline allows."""
    active = tuple(rule for rule in rules if rule.id not in config.disable)
    findings = config.apply(run_rules(active, ctx))
    sources = {change.path: change.head_src for change in ctx.changes if change.head_src}
    kept, suppressed = apply_suppressions(findings, sources)
    return Outcome(tuple(kept), tuple(suppressed), len(ctx.changes), active)


def analyze(
    repo: Path,
    rules: Sequence[Rule],
    *,
    base: str | None = None,
    head: str | None = None,
    staged: bool = False,
    coverage: Path | None = None,
) -> tuple[Outcome, Config]:
    """The whole pipeline for one repository and diff selection.

    Raises ``GitError``, ``ConfigError`` or ``CoverageReportError`` for bad input.
    """
    git = Git.discover(repo)
    if staged:
        spec = git.staged()
    elif base is not None:
        spec = git.range_from_base(base, head)
    else:
        spec = git.working_tree()
    config = load_config(git, spec, (rule.id for rule in rules))
    uncovered = load_coverage(coverage, git.root) if coverage is not None else None
    ctx = build_context(git, spec, config.test_patterns, uncovered)
    return evaluate(rules, ctx, config), config


def exit_code(findings: Iterable[Finding], fail_on: Severity) -> int:
    if any(finding.severity.at_least(fail_on) for finding in findings):
        return EXIT_FINDINGS
    return EXIT_OK
