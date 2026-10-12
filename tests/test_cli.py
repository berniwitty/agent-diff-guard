from __future__ import annotations

from collections.abc import Iterable

import pytest
from typer.testing import CliRunner

from agent_diff_guard import cli
from agent_diff_guard.change import ChangedFile
from agent_diff_guard.rules.base import Finding, RuleRegistry, RunContext, Severity

runner = CliRunner()


class DummyRule:
    id = "ADG002"
    name = "test-skipped"
    default_severity = Severity.ERROR

    def check(self, change: ChangedFile, ctx: RunContext) -> Iterable[Finding]:
        return ()


@pytest.fixture
def empty_registry(monkeypatch: pytest.MonkeyPatch) -> RuleRegistry:
    reg = RuleRegistry()
    monkeypatch.setattr(cli, "registry", reg)
    return reg


@pytest.fixture
def one_rule_registry(empty_registry: RuleRegistry) -> RuleRegistry:
    empty_registry.register(DummyRule())
    return empty_registry


def test_no_args_shows_help() -> None:
    result = runner.invoke(cli.app, [])
    assert "check" in result.output
    assert "explain" in result.output


@pytest.mark.usefixtures("empty_registry")
def test_check_without_rules_says_nothing_was_checked() -> None:
    result = runner.invoke(cli.app, ["check", "--base", "origin/main"])
    assert result.exit_code == 0
    assert "no rules are registered; nothing was checked" in result.output


@pytest.mark.usefixtures("one_rule_registry")
def test_check_with_rules_reports_missing_git_support() -> None:
    result = runner.invoke(cli.app, ["check", "--base", "origin/main"])
    assert result.exit_code == 2
    assert "not implemented yet" in result.output


def test_check_rejects_base_with_staged() -> None:
    result = runner.invoke(cli.app, ["check", "--base", "origin/main", "--staged"])
    assert result.exit_code == 2
    assert "cannot be used together" in result.output


def test_check_rejects_unknown_format() -> None:
    result = runner.invoke(cli.app, ["check", "--format", "xml"])
    assert result.exit_code == 2


@pytest.mark.usefixtures("empty_registry")
def test_rules_with_empty_registry() -> None:
    result = runner.invoke(cli.app, ["rules"])
    assert result.exit_code == 0
    assert result.output.strip() == "No rules registered."


@pytest.mark.usefixtures("one_rule_registry")
def test_rules_lists_id_name_and_severity() -> None:
    result = runner.invoke(cli.app, ["rules"])
    assert result.exit_code == 0
    assert result.output.split() == ["ADG002", "test-skipped", "error"]


@pytest.mark.usefixtures("one_rule_registry")
def test_explain_known_rule_is_case_insensitive() -> None:
    result = runner.invoke(cli.app, ["explain", "adg002"])
    assert result.exit_code == 0
    assert result.output.strip() == "ADG002 test-skipped (default severity: error)"


@pytest.mark.usefixtures("empty_registry")
def test_explain_unknown_rule_is_usage_error() -> None:
    result = runner.invoke(cli.app, ["explain", "ADG999"])
    assert result.exit_code == 2
    assert "Unknown rule ID: ADG999" in result.output
