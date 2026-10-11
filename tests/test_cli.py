from __future__ import annotations

import io
import json
import re
import sys
from collections.abc import Iterable
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from agent_diff_guard import cli
from agent_diff_guard.change import ChangedFile
from agent_diff_guard.rules import registry
from agent_diff_guard.rules.base import Finding, RuleRegistry, RunContext, Severity
from tests.harness import git, make_repo

runner = CliRunner()
# Typer renders usage errors with rich; on CI (GITHUB_ACTIONS) that output is colourised.
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


def plain(result: Result) -> str:
    return ANSI_ESCAPE.sub("", result.output)


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
    assert "check" in plain(result)
    assert "explain" in plain(result)


CALC = "def add(a, b):\n    return a + b\n"
STUBBED = "def add(a, b):\n    pass\n"
NOQA = "import os  # noqa: F401\n"


@pytest.mark.usefixtures("empty_registry")
def test_check_with_no_rules_reports_zero_rules(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, {"src/calc.py": CALC}, {"src/calc.py": STUBBED})
    result = runner.invoke(cli.app, ["check", "--repo", str(repo.path), "--base", repo.base])
    assert result.exit_code == 0
    assert plain(result).strip() == (
        "Checked 1 changed file(s) with 0 rule(s): 0 error, 0 warn, 0 info."
    )


def test_check_reports_error_finding_and_exits_1(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, {"src/calc.py": CALC}, {"src/calc.py": STUBBED})
    result = runner.invoke(
        cli.app, ["check", "--repo", str(repo.path), "--base", repo.base, "--head", repo.head]
    )
    assert result.exit_code == 1
    assert plain(result).splitlines() == [
        "src/calc.py:1: error ADG010 Function `add` had real logic and now has a stub body.",
        "    return a + b -> pass",
        f"Checked 1 changed file(s) with {len(registry.all())} rule(s): 1 error, 0 warn, 0 info.",
    ]


def test_check_fail_on_controls_exit_code(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, {"src/a.py": "x = 1\n"}, {"src/a.py": "x = 1\n", "src/b.py": NOQA})
    args = ["check", "--repo", str(repo.path), "--base", repo.base]
    assert runner.invoke(cli.app, args).exit_code == 0
    warn = runner.invoke(cli.app, [*args, "--fail-on", "warn"])
    assert warn.exit_code == 1
    assert "src/b.py:1: warn ADG020" in plain(warn)


def test_check_default_reads_uncommitted_changes(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, {}, {"src/calc.py": CALC})
    (repo.path / "src" / "calc.py").write_text(STUBBED, encoding="utf-8")
    result = runner.invoke(cli.app, ["check", "--repo", str(repo.path)])
    assert result.exit_code == 1
    assert "src/calc.py:1: error ADG010" in plain(result)


def test_check_staged_ignores_unstaged_changes(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, {}, {"src/calc.py": CALC, "src/other.py": CALC})
    (repo.path / "src" / "calc.py").write_text(STUBBED, encoding="utf-8")
    (repo.path / "src" / "other.py").write_text(STUBBED, encoding="utf-8")
    git(repo.path, "add", "src/calc.py")
    result = runner.invoke(cli.app, ["check", "--repo", str(repo.path), "--staged"])
    assert result.exit_code == 1
    assert "src/calc.py:1: error ADG010" in plain(result)
    assert "src/other.py" not in plain(result)


def test_check_outside_a_repository_is_usage_error(tmp_path: Path) -> None:
    result = runner.invoke(cli.app, ["check", "--repo", str(tmp_path)])
    assert result.exit_code == 2
    assert plain(result).startswith("adg check: git rev-parse failed")


def test_check_unknown_base_is_usage_error(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, {}, {"a.py": "x = 1\n"})
    result = runner.invoke(cli.app, ["check", "--repo", str(repo.path), "--base", "nope"])
    assert result.exit_code == 2
    assert "'nope' is not a commit" in plain(result)


def test_check_head_requires_base() -> None:
    result = runner.invoke(cli.app, ["check", "--head", "HEAD"])
    assert result.exit_code == 2
    assert "--head requires --base" in plain(result)


def test_check_rejects_head_with_staged() -> None:
    result = runner.invoke(cli.app, ["check", "--head", "HEAD", "--staged"])
    assert result.exit_code == 2
    assert "cannot be used together" in plain(result)


# test_check_unimplemented_format_is_usage_error asserted the pre-M3 placeholder
# ("--format json is not implemented yet"). The formats exist now; these tests replace it.
# adg: allow ADG001 reason="placeholder test for unimplemented --format replaced by format tests"


@pytest.mark.parametrize("output_format", ["json", "sarif"])
def test_check_machine_formats_are_valid_json(tmp_path: Path, output_format: str) -> None:
    repo = make_repo(tmp_path, {"src/calc.py": CALC}, {"src/calc.py": STUBBED})
    result = runner.invoke(
        cli.app,
        ["check", "--repo", str(repo.path), "--base", repo.base, "--format", output_format],
    )
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert "ADG010" in json.dumps(data)


def test_check_markdown_format(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, {"src/calc.py": CALC}, {"src/calc.py": STUBBED})
    result = runner.invoke(
        cli.app, ["check", "--repo", str(repo.path), "--base", repo.base, "--format", "markdown"]
    )
    assert result.exit_code == 1
    assert result.output.startswith("## agent-diff-guard\n")
    assert "| error | ADG010 | `src/calc.py:1` |" in result.output


ALLOWED = 'def add(a, b):  # adg: allow ADG010 reason="kept for API v1"\n    pass\n'


def test_check_inline_allow_with_reason_suppresses(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, {"src/calc.py": CALC}, {"src/calc.py": ALLOWED})
    result = runner.invoke(cli.app, ["check", "--repo", str(repo.path), "--base", repo.base])
    assert result.exit_code == 0
    assert plain(result).splitlines()[:3] == [
        "Suppressed (1):",
        "  src/calc.py:1: ADG010 Function `add` had real logic and now has a stub body.",
        '    reason: "kept for API v1"',
    ]


def test_check_inline_allow_without_reason_suppresses_nothing(tmp_path: Path) -> None:
    no_reason = "def add(a, b):  # adg: allow ADG010\n    pass\n"
    repo = make_repo(tmp_path, {"src/calc.py": CALC}, {"src/calc.py": no_reason})
    result = runner.invoke(cli.app, ["check", "--repo", str(repo.path), "--base", repo.base])
    assert result.exit_code == 1
    assert "src/calc.py:1: error ADG010" in plain(result)
    assert "src/calc.py:1: warn ADG099" in plain(result)


CONFIG = """\
[tool.agent-diff-guard]
exclude = ["vendor/"]
disable = ["ADG020"]
severity = { ADG010 = "warn" }
fail-on = "warn"
"""


def test_check_reads_config_from_base_revision(tmp_path: Path) -> None:
    before = {"pyproject.toml": CONFIG, "src/calc.py": CALC, "vendor/lib.py": CALC}
    after = {
        "pyproject.toml": "[tool.agent-diff-guard]\ndisable = ['ADG010']\n",
        "src/calc.py": STUBBED,
        "src/extra.py": NOQA,
        "vendor/lib.py": STUBBED,
    }
    repo = make_repo(tmp_path, before, after)
    result = runner.invoke(cli.app, ["check", "--repo", str(repo.path), "--base", repo.base])
    lines = plain(result).splitlines()
    # Base config applies: ADG010 downgraded to warn (head's attempt to disable it is
    # ignored), ADG020 disabled, vendor/ excluded, and fail-on=warn makes this exit 1.
    assert result.exit_code == 1
    assert lines[0] == (
        "src/calc.py:1: warn ADG010 Function `add` had real logic and now has a stub body."
    )
    assert not any("ADG020" in line or "vendor/" in line for line in lines)
    enabled = len(registry.all()) - 1  # ADG020 is disabled by the base config
    assert (
        lines[-1] == f"Checked 4 changed file(s) with {enabled} rule(s): 0 error, 1 warn, 0 info."
    )
    explicit = runner.invoke(
        cli.app, ["check", "--repo", str(repo.path), "--base", repo.base, "--fail-on", "error"]
    )
    assert explicit.exit_code == 0


def test_check_invalid_config_is_usage_error(tmp_path: Path) -> None:
    bad = "[tool.agent-diff-guard]\ndisable = ['ADG999']\n"
    repo = make_repo(tmp_path, {"pyproject.toml": bad}, {"pyproject.toml": bad, "a.py": CALC})
    result = runner.invoke(cli.app, ["check", "--repo", str(repo.path), "--base", repo.base])
    assert result.exit_code == 2
    assert "disable names unknown rule(s): ADG999" in plain(result)


def test_check_rejects_base_with_staged() -> None:
    result = runner.invoke(cli.app, ["check", "--base", "origin/main", "--staged"])
    assert result.exit_code == 2
    assert "cannot be used together" in plain(result)


def test_check_rejects_unknown_format() -> None:
    result = runner.invoke(cli.app, ["check", "--format", "xml"])
    assert result.exit_code == 2


@pytest.mark.usefixtures("empty_registry")
def test_rules_with_empty_registry() -> None:
    result = runner.invoke(cli.app, ["rules"])
    assert result.exit_code == 0
    assert plain(result).strip() == "No rules registered."


@pytest.mark.usefixtures("one_rule_registry")
def test_rules_lists_id_name_and_severity() -> None:
    result = runner.invoke(cli.app, ["rules"])
    assert result.exit_code == 0
    assert plain(result).split() == ["ADG002", "test-skipped", "error"]


@pytest.mark.usefixtures("one_rule_registry")
def test_explain_known_rule_is_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    # Without a docs page, explain falls back to the rule's header line.
    monkeypatch.setattr(cli, "rule_doc", lambda rule_id: None)
    result = runner.invoke(cli.app, ["explain", "adg002"])
    assert result.exit_code == 0
    assert plain(result).strip() == "ADG002 test-skipped (default severity: error)"


def test_explain_prints_the_rule_docs_page() -> None:
    result = runner.invoke(cli.app, ["explain", "ADG010"])
    assert result.exit_code == 0
    assert plain(result).startswith("# ADG010 — stub-body\n")
    assert "## Example — flagged" in plain(result)


def test_rule_doc_prefers_packaged_docs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "rule_docs").mkdir()
    (tmp_path / "rule_docs" / "ADG010.md").write_text("packaged", encoding="utf-8")
    monkeypatch.setattr(cli.resources, "files", lambda package: tmp_path)
    assert cli.rule_doc("ADG010") == "packaged"
    assert cli.rule_doc("ADG999") is None


@pytest.mark.usefixtures("empty_registry")
def test_explain_unknown_rule_is_usage_error() -> None:
    result = runner.invoke(cli.app, ["explain", "ADG999"])
    assert result.exit_code == 2
    assert "Unknown rule ID: ADG999" in plain(result)


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


def test_check_with_coverage_report(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, {"src/calc.py": CALC}, {"src/calc.py": CALC + "LIMIT = 10\n"})
    report = tmp_path / "coverage.xml"
    report.write_text(
        "<coverage><sources><source>.</source></sources><packages><package><classes>"
        '<class filename="src/calc.py"><lines><line number="3" hits="0"/></lines></class>'
        "</classes></package></packages></coverage>",
        encoding="utf-8",
    )
    args = ["check", "--repo", str(repo.path), "--base", repo.base]

    with_report = runner.invoke(cli.app, [*args, "--coverage", str(report)])
    without = runner.invoke(cli.app, args)
    broken = runner.invoke(cli.app, [*args, "--coverage", str(tmp_path / "missing.xml")])

    assert with_report.exit_code == 0
    assert "src/calc.py:3: info ADG040 Added line 3 is not executed" in plain(with_report)
    assert "ADG040" not in plain(without)
    assert broken.exit_code == 2
    assert "cannot read coverage report" in plain(broken)
