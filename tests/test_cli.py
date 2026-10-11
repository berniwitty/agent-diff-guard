from __future__ import annotations

import io
import sys
from collections.abc import Iterable
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agent_diff_guard import cli
from agent_diff_guard.change import ChangedFile
from agent_diff_guard.rules.base import Finding, RuleRegistry, RunContext, Severity
from tests.harness import git, make_repo

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


CALC = "def add(a, b):\n    return a + b\n"
STUBBED = "def add(a, b):\n    pass\n"
NOQA = "import os  # noqa: F401\n"


@pytest.mark.usefixtures("empty_registry")
def test_check_with_no_rules_reports_zero_rules(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, {"src/calc.py": CALC}, {"src/calc.py": STUBBED})
    result = runner.invoke(cli.app, ["check", "--repo", str(repo.path), "--base", repo.base])
    assert result.exit_code == 0
    assert result.output.strip() == (
        "Checked 1 changed file(s) with 0 rule(s): 0 error, 0 warn, 0 info."
    )


def test_check_reports_error_finding_and_exits_1(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, {"src/calc.py": CALC}, {"src/calc.py": STUBBED})
    result = runner.invoke(
        cli.app, ["check", "--repo", str(repo.path), "--base", repo.base, "--head", repo.head]
    )
    assert result.exit_code == 1
    assert result.output.splitlines() == [
        "src/calc.py:1: error ADG010 Function `add` had real logic and now has a stub body.",
        "    return a + b -> pass",
        "Checked 1 changed file(s) with 3 rule(s): 1 error, 0 warn, 0 info.",
    ]


def test_check_fail_on_controls_exit_code(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, {"src/a.py": "x = 1\n"}, {"src/a.py": "x = 1\n", "src/b.py": NOQA})
    args = ["check", "--repo", str(repo.path), "--base", repo.base]
    assert runner.invoke(cli.app, args).exit_code == 0
    warn = runner.invoke(cli.app, [*args, "--fail-on", "warn"])
    assert warn.exit_code == 1
    assert "src/b.py:1: warn ADG020" in warn.output


def test_check_default_reads_uncommitted_changes(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, {}, {"src/calc.py": CALC})
    (repo.path / "src" / "calc.py").write_text(STUBBED, encoding="utf-8")
    result = runner.invoke(cli.app, ["check", "--repo", str(repo.path)])
    assert result.exit_code == 1
    assert "src/calc.py:1: error ADG010" in result.output


def test_check_staged_ignores_unstaged_changes(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, {}, {"src/calc.py": CALC, "src/other.py": CALC})
    (repo.path / "src" / "calc.py").write_text(STUBBED, encoding="utf-8")
    (repo.path / "src" / "other.py").write_text(STUBBED, encoding="utf-8")
    git(repo.path, "add", "src/calc.py")
    result = runner.invoke(cli.app, ["check", "--repo", str(repo.path), "--staged"])
    assert result.exit_code == 1
    assert "src/calc.py:1: error ADG010" in result.output
    assert "src/other.py" not in result.output


def test_check_outside_a_repository_is_usage_error(tmp_path: Path) -> None:
    result = runner.invoke(cli.app, ["check", "--repo", str(tmp_path)])
    assert result.exit_code == 2
    assert result.output.startswith("adg check: git rev-parse failed")


def test_check_unknown_base_is_usage_error(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, {}, {"a.py": "x = 1\n"})
    result = runner.invoke(cli.app, ["check", "--repo", str(repo.path), "--base", "nope"])
    assert result.exit_code == 2
    assert "'nope' is not a commit" in result.output


def test_check_head_requires_base() -> None:
    result = runner.invoke(cli.app, ["check", "--head", "HEAD"])
    assert result.exit_code == 2
    assert "--head requires --base" in result.output


def test_check_rejects_head_with_staged() -> None:
    result = runner.invoke(cli.app, ["check", "--head", "HEAD", "--staged"])
    assert result.exit_code == 2
    assert "cannot be used together" in result.output


def test_check_unimplemented_format_is_usage_error() -> None:
    result = runner.invoke(cli.app, ["check", "--format", "json"])
    assert result.exit_code == 2
    assert "--format json is not implemented yet" in result.output


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


@pytest.mark.parametrize("err", [False, True])
def test_emit_escapes_characters_the_stream_cannot_encode(
    monkeypatch: pytest.MonkeyPatch, err: bool
) -> None:
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="gbk", newline="\n")
    monkeypatch.setattr(sys, "stderr" if err else "stdout", stream)

    cli._emit("return '\U0001f44b héllo'", err=err)

    stream.flush()
    # GBK has no emoji, so it is escaped; "é" exists in GBK and is kept as is.
    assert raw.getvalue().decode("gbk") == "return '\\U0001f44b héllo'\n"
