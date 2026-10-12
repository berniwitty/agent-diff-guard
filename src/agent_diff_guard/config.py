"""``[tool.agent-diff-guard]`` in pyproject.toml.

Example::

    [tool.agent-diff-guard]
    test-patterns = ["tests/", "test_*.py", "*_test.py", "conftest.py"]
    exclude = ["tests/fixtures/", "vendor/*.py"]
    disable = ["ADG004"]
    severity = { ADG020 = "error" }
    fail-on = "warn"

The CLI reads this from the **base** revision, so a change cannot loosen its own checks.
"""

from __future__ import annotations

import dataclasses
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from fnmatch import fnmatchcase

from agent_diff_guard.classify import DEFAULT_TEST_PATTERNS
from agent_diff_guard.rules.base import Finding, Severity

_KEYS = frozenset({"test-patterns", "exclude", "disable", "severity", "fail-on"})


class ConfigError(Exception):
    """The configuration table is malformed."""


@dataclass(frozen=True)
class Config:
    test_patterns: tuple[str, ...] = DEFAULT_TEST_PATTERNS
    exclude: tuple[str, ...] = ()
    disable: frozenset[str] = frozenset()
    severity: Mapping[str, Severity] = field(default_factory=dict)
    fail_on: Severity | None = None

    def is_excluded(self, path: str) -> bool:
        """``dir/`` patterns match everything under ``dir``; others are globs on the path."""
        return any(
            path.startswith(pattern) if pattern.endswith("/") else fnmatchcase(path, pattern)
            for pattern in self.exclude
        )

    def apply(self, findings: Iterable[Finding]) -> list[Finding]:
        """Drop findings on excluded paths and apply severity overrides."""
        return [
            dataclasses.replace(
                finding, severity=self.severity.get(finding.rule_id, finding.severity)
            )
            for finding in findings
            if not self.is_excluded(finding.path)
        ]


def parse_config(text: str, known_rules: Iterable[str], origin: str) -> Config:
    """Parse pyproject.toml text; ``origin`` names it in error messages."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{origin}: invalid TOML: {exc}") from exc
    table = data.get("tool", {}).get("agent-diff-guard", {})
    if not isinstance(table, dict):
        raise ConfigError(f"{origin}: [tool.agent-diff-guard] must be a table")
    unknown = sorted(set(table) - _KEYS)
    if unknown:
        raise ConfigError(f"{origin}: unknown [tool.agent-diff-guard] key(s): {', '.join(unknown)}")
    rules = frozenset(known_rules)
    config = Config()
    if "test-patterns" in table:
        config = dataclasses.replace(
            config, test_patterns=_strings(table["test-patterns"], "test-patterns", origin)
        )
    if "exclude" in table:
        config = dataclasses.replace(config, exclude=_strings(table["exclude"], "exclude", origin))
    if "disable" in table:
        disable = _strings(table["disable"], "disable", origin)
        _check_rule_ids(disable, rules, "disable", origin)
        config = dataclasses.replace(config, disable=frozenset(disable))
    if "severity" in table:
        overrides = table["severity"]
        if not isinstance(overrides, dict):
            raise ConfigError(f"{origin}: severity must be a table of RULE = level")
        _check_rule_ids(overrides, rules, "severity", origin)
        severity = {
            rule: _severity(level, f"severity.{rule}", origin) for rule, level in overrides.items()
        }
        config = dataclasses.replace(config, severity=severity)
    if "fail-on" in table:
        config = dataclasses.replace(config, fail_on=_severity(table["fail-on"], "fail-on", origin))
    return config


def _strings(value: object, key: str, origin: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f"{origin}: {key} must be a list of strings")
    return tuple(value)


def _check_rule_ids(ids: Iterable[str], known: frozenset[str], key: str, origin: str) -> None:
    unknown = sorted(set(ids) - known)
    if unknown:
        raise ConfigError(f"{origin}: {key} names unknown rule(s): {', '.join(unknown)}")


def _severity(value: object, key: str, origin: str) -> Severity:
    levels = [str(level) for level in Severity]
    if value not in levels:
        raise ConfigError(f"{origin}: {key} must be one of {', '.join(levels)}, got {value!r}")
    return Severity(value)
