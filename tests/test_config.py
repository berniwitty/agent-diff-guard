from __future__ import annotations

import pytest

from agent_diff_guard.config import Config, ConfigError, parse_config
from agent_diff_guard.rules.base import Finding, Severity

RULES = ["ADG002", "ADG010", "ADG020"]


def parse(text: str) -> Config:
    return parse_config(text, RULES, "pyproject.toml")


def test_missing_table_gives_defaults() -> None:
    assert parse("[project]\nname = 'x'\n") == Config()
    assert parse("") == Config()


def test_full_table() -> None:
    config = parse(
        """
        [tool.agent-diff-guard]
        test-patterns = ["spec/"]
        exclude = ["tests/fixtures/", "*.pyi"]
        disable = ["ADG002"]
        severity = { ADG020 = "error", ADG010 = "info" }
        fail-on = "warn"
        """
    )

    assert config == Config(
        test_patterns=("spec/",),
        exclude=("tests/fixtures/", "*.pyi"),
        disable=frozenset({"ADG002"}),
        severity={"ADG020": Severity.ERROR, "ADG010": Severity.INFO},
        fail_on=Severity.WARN,
    )


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("[tool.agent-diff-guard\n", "invalid TOML"),
        ("[tool]\nagent-diff-guard = 3\n", "must be a table"),
        (
            "[tool.agent-diff-guard]\nignore = []\n",
            r"unknown \[tool.agent-diff-guard\] key\(s\): ignore",
        ),
        ("[tool.agent-diff-guard]\nexclude = 'tests/'\n", "exclude must be a list of strings"),
        ("[tool.agent-diff-guard]\ntest-patterns = [1]\n", "test-patterns must be a list"),
        (
            "[tool.agent-diff-guard]\ndisable = ['ADG999']\n",
            r"disable names unknown rule\(s\): ADG999",
        ),
        ("[tool.agent-diff-guard]\nseverity = ['ADG010']\n", "severity must be a table"),
        ("[tool.agent-diff-guard]\nseverity = { ADG999 = 'warn' }\n", r"unknown rule\(s\): ADG999"),
        (
            "[tool.agent-diff-guard]\nseverity = { ADG010 = 'fatal' }\n",
            "severity.ADG010 must be one of",
        ),
        (
            "[tool.agent-diff-guard]\nfail-on = 'warning'\n",
            "fail-on must be one of info, warn, error",
        ),
    ],
)
def test_invalid_config(text: str, message: str) -> None:
    with pytest.raises(ConfigError, match=f"^pyproject.toml: .*{message}"):
        parse(text)


@pytest.mark.parametrize(
    ("path", "excluded"),
    [
        ("tests/fixtures/a/b.py", True),
        ("tests/fixtures.py", False),
        ("src/a.pyi", True),
        ("src/pkg/a.pyi", True),
        ("src/a.py", False),
    ],
)
def test_is_excluded(path: str, excluded: bool) -> None:
    config = Config(exclude=("tests/fixtures/", "*.pyi"))
    assert config.is_excluded(path) is excluded


def test_apply_drops_excluded_and_overrides_severity() -> None:
    config = Config(exclude=("vendor/",), severity={"ADG020": Severity.ERROR})
    findings = [
        Finding("ADG020", Severity.WARN, "src/a.py", 1, "m", "e"),
        Finding("ADG010", Severity.ERROR, "src/a.py", 2, "m", "e"),
        Finding("ADG020", Severity.WARN, "vendor/b.py", 1, "m", "e"),
    ]

    assert config.apply(findings) == [
        Finding("ADG020", Severity.ERROR, "src/a.py", 1, "m", "e"),
        Finding("ADG010", Severity.ERROR, "src/a.py", 2, "m", "e"),
    ]
