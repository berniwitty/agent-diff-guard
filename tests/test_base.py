from __future__ import annotations

import dataclasses
from collections.abc import Iterable

import pytest

from agent_diff_guard.change import ChangedFile
from agent_diff_guard.rules.base import Finding, RuleRegistry, RunContext, Severity


class DummyRule:
    def __init__(self, rule_id: str, name: str = "dummy") -> None:
        self.id = rule_id
        self.name = name
        self.default_severity = Severity.WARN

    def check(self, change: ChangedFile, ctx: RunContext) -> Iterable[Finding]:
        return ()


@pytest.mark.parametrize(
    ("severity", "threshold", "expected"),
    [
        (Severity.ERROR, Severity.ERROR, True),
        (Severity.ERROR, Severity.INFO, True),
        (Severity.WARN, Severity.ERROR, False),
        (Severity.WARN, Severity.WARN, True),
        (Severity.INFO, Severity.WARN, False),
    ],
)
def test_severity_at_least(severity: Severity, threshold: Severity, expected: bool) -> None:
    assert severity.at_least(threshold) is expected


def test_finding_is_frozen() -> None:
    finding = Finding("ADG002", Severity.ERROR, "tests/test_a.py", 3, "msg", "evidence")
    with pytest.raises(dataclasses.FrozenInstanceError):
        finding.line = 4


def test_registry_returns_rules_sorted_by_id() -> None:
    reg = RuleRegistry()
    second = reg.register(DummyRule("ADG010"))
    first = reg.register(DummyRule("ADG002"))

    assert reg.all() == [first, second]
    assert reg.get("ADG010") is second
    assert reg.get("ADG999") is None


def test_registry_rejects_duplicate_id() -> None:
    reg = RuleRegistry()
    reg.register(DummyRule("ADG002"))
    with pytest.raises(ValueError, match="ADG002 is already registered"):
        reg.register(DummyRule("ADG002", name="other"))
