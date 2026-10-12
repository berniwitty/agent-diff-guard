"""Run each rule against its fixture cases through a real git repository."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_diff_guard.engine import build_context, run_rules
from agent_diff_guard.git import Git
from agent_diff_guard.rules import registry
from tests.harness import FixtureCase, build_repo, discover_cases

CASES = discover_cases()


@pytest.mark.parametrize("case", CASES, ids=[case.id for case in CASES])
def test_fixture_case(case: FixtureCase, tmp_path: Path) -> None:
    rule = registry.get(case.rule_id)
    assert rule is not None, f"{case.rule_id} has fixtures but no registered rule"
    repo = build_repo(case.root, tmp_path / "repo")
    git = Git.discover(repo.path)
    ctx = build_context(git, git.range_from_base(repo.base, repo.head))

    findings = run_rules([rule], ctx)

    actual = sorted((f.rule_id, f.path, f.line) for f in findings)
    expected = sorted((e.rule_id, e.path, e.line) for e in case.expected())
    assert actual == expected
    for finding in findings:
        assert finding.severity == rule.default_severity
        assert finding.message.endswith(".")
        assert "\n" not in finding.message
        assert finding.evidence


def test_fixture_cases_exist() -> None:
    assert {case.kind for case in CASES} == {"positive", "negative"}
