"""Rule protocol, findings, severities and the rule registry."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from agent_diff_guard.change import ChangedFile
from agent_diff_guard.classify import DEFAULT_TEST_PATTERNS, is_test_file


class Severity(StrEnum):
    """Finding severity, declared from least to most severe."""

    INFO = "info"
    WARN = "warn"
    ERROR = "error"

    def at_least(self, other: Severity) -> bool:
        order = list(Severity)
        return order.index(self) >= order.index(other)


@dataclass(frozen=True)
class Finding:
    rule_id: str
    severity: Severity
    path: str
    line: int | None
    message: str
    evidence: str


@dataclass(frozen=True)
class RunContext:
    """Information shared by every rule during one run."""

    changes: tuple[ChangedFile, ...] = ()
    test_patterns: tuple[str, ...] = DEFAULT_TEST_PATTERNS

    def is_test_file(self, path: str) -> bool:
        return is_test_file(path, self.test_patterns)


class Rule(Protocol):
    id: str
    name: str
    default_severity: Severity

    def check(self, change: ChangedFile, ctx: RunContext) -> Iterable[Finding]: ...


class RuleRegistry:
    def __init__(self) -> None:
        self._rules: dict[str, Rule] = {}

    def register(self, rule: Rule) -> Rule:
        if rule.id in self._rules:
            raise ValueError(f"rule {rule.id} is already registered")
        self._rules[rule.id] = rule
        return rule

    def get(self, rule_id: str) -> Rule | None:
        return self._rules.get(rule_id)

    def all(self) -> list[Rule]:
        return [self._rules[rule_id] for rule_id in sorted(self._rules)]


registry = RuleRegistry()
