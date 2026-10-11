"""Every registered rule must ship a docs page and both kinds of fixture (SPEC §7)."""

from __future__ import annotations

from pathlib import Path

from agent_diff_guard.rules.base import registry
from tests.harness import FIXTURES_ROOT, discover_cases

DOCS_ROOT = Path(__file__).parent.parent / "docs" / "rules"


def test_every_registered_rule_has_docs_and_fixtures() -> None:
    cases = discover_cases(FIXTURES_ROOT)
    missing = []
    for rule in registry.all():
        if not (DOCS_ROOT / f"{rule.id}.md").is_file():
            missing.append(f"{rule.id}: docs/rules/{rule.id}.md")
        kinds = {case.kind for case in cases if case.rule_id == rule.id}
        missing.extend(
            f"{rule.id}: {kind} fixture" for kind in ("positive", "negative") if kind not in kinds
        )
    assert missing == []


def test_every_fixture_case_has_expected_json() -> None:
    missing = [
        case.id
        for case in discover_cases(FIXTURES_ROOT)
        if not (case.root / "expected.json").is_file()
    ]
    assert missing == []
