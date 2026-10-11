"""Rule protocol, findings, severities and the rule registry."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from functools import cached_property
from typing import Protocol

from agent_diff_guard.astutil import (
    BodyShape,
    body_shape,
    fingerprint,
    functions,
    parse,
    test_functions,
)
from agent_diff_guard.change import ChangedFile
from agent_diff_guard.classify import DEFAULT_TEST_PATTERNS, is_python_file, is_test_file


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
    """Information shared by every rule during one run.

    ``assertion_literals`` holds, for each assertion in every test file at head (changed
    or not), the set of scalar literal keys it contains (see ``astutil.literal_keys``).
    ``uncovered_lines`` maps repository paths to lines a coverage report measured but
    never executed; it is ``None`` when no report was given.
    """

    changes: tuple[ChangedFile, ...] = ()
    test_patterns: tuple[str, ...] = DEFAULT_TEST_PATTERNS
    assertion_literals: frozenset[frozenset[str]] = frozenset()
    uncovered_lines: Mapping[str, frozenset[int]] | None = None

    def is_test_file(self, path: str) -> bool:
        return is_test_file(path, self.test_patterns)

    def is_python_test(self, path: str) -> bool:
        return is_python_file(path) and self.is_test_file(path)

    def is_python_source(self, path: str) -> bool:
        return is_python_file(path) and not self.is_test_file(path)

    @cached_property
    def new_test_shapes(self) -> tuple[BodyShape, ...]:
        """Shapes of test functions that are new anywhere in this diff."""
        shapes: list[BodyShape] = []
        for change in self.changes:
            if not self.is_python_test(change.path):
                continue
            head = parse(change.head_src)
            if head is None:
                continue
            base = parse(change.base_src)
            existing = test_functions(base) if base is not None else {}
            shapes.extend(
                body_shape(node)
                for qualname, node in test_functions(head).items()
                if qualname not in existing
            )
        return tuple(shapes)

    @cached_property
    def changed_function_names(self) -> frozenset[str]:
        """Simple names of non-test functions that are new or modified in this diff."""
        names: set[str] = set()
        for change in self.changes:
            if not self.is_python_source(change.path):
                continue
            head = parse(change.head_src)
            if head is None:
                continue
            base = parse(change.base_src)
            before = {q: fingerprint(n) for q, n in functions(base).items()} if base else {}
            names.update(
                node.name
                for qualname, node in functions(head).items()
                if before.get(qualname) != fingerprint(node)
            )
        return frozenset(names)


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
