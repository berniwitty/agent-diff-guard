from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agent_diff_guard import cli, hooks
from agent_diff_guard.rules import registry
from agent_diff_guard.rules.base import Severity
from tests.harness import make_repo

CALC = "def add(a, b):\n    return a + b\n"
STUBBED = "def add(a, b):\n    pass\n"
NOQA = "import os  # noqa: F401\n"


def stop(
    payload: object,
    *,
    base: str | None = None,
    fail_on: Severity | None = None,
    once: bool = False,
) -> tuple[int, str, str]:
    return hooks.claude_code_stop(
        json.dumps(payload), registry.all(), base=base, fail_on=fail_on, once=once
    )


def repo_with_uncommitted(tmp_path: Path, committed: str, working: str) -> Path:
    repo = make_repo(tmp_path, {}, {"src/calc.py": committed})
    (repo.path / "src" / "calc.py").write_bytes(working.encode())
    return repo.path


def test_blocks_with_report_when_findings_remain(tmp_path: Path) -> None:
    repo = repo_with_uncommitted(tmp_path, CALC, STUBBED)

    code, out, err = stop({"cwd": str(repo), "stop_hook_active": True})

    assert (code, err) == (0, "")
    decision = json.loads(out)
    assert decision["decision"] == "block"
    assert decision["reason"].startswith(hooks.INSTRUCTIONS)
    assert "src/calc.py:1: error ADG010" in decision["reason"]


def test_allows_stop_when_clean(tmp_path: Path) -> None:
    repo = repo_with_uncommitted(tmp_path, CALC, CALC.replace("a + b", "b + a"))
    assert stop({"cwd": str(repo)}) == (0, "", "")


def test_fail_on_controls_blocking(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, {}, {"src/calc.py": CALC})
    (repo.path / "src" / "extra.py").write_bytes(NOQA.encode())

    assert stop({"cwd": str(repo.path)}) == (0, "", "")
    code, out, _ = stop({"cwd": str(repo.path)}, fail_on=Severity.WARN)
    assert code == 0
    assert "ADG020" in json.loads(out)["reason"]


def test_once_only_blocks_the_first_stop(tmp_path: Path) -> None:
    repo = repo_with_uncommitted(tmp_path, CALC, STUBBED)

    assert stop({"cwd": str(repo), "stop_hook_active": True}, once=True) == (0, "", "")
    code, out, _ = stop({"cwd": str(repo), "stop_hook_active": False}, once=True)
    assert code == 0
    assert json.loads(out)["decision"] == "block"


def test_base_checks_committed_changes_too(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, {"src/calc.py": CALC}, {"src/calc.py": STUBBED})

    assert stop({"cwd": str(repo.path)}) == (0, "", "")
    _, out, _ = stop({"cwd": str(repo.path)}, base=repo.base)
    assert json.loads(out)["decision"] == "block"


def test_errors_are_non_blocking(tmp_path: Path) -> None:
    code, out, err = stop({"cwd": str(tmp_path)})
    assert (code, out) == (1, "")
    assert err.startswith("agent-diff-guard: git rev-parse failed")

    code, out, err = hooks.claude_code_stop("{not json", registry.all())
    assert (code, out) == (1, "")
    assert err.startswith("agent-diff-guard: hook input is not JSON")


def test_missing_or_odd_input_falls_back_to_current_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = repo_with_uncommitted(tmp_path, CALC, STUBBED)
    monkeypatch.chdir(repo)
    for stdin in ("", "[]", '{"cwd": 3}'):
        code, out, _ = hooks.claude_code_stop(stdin, registry.all())
        assert code == 0
        assert json.loads(out)["decision"] == "block"


def test_cli_hook_command(tmp_path: Path) -> None:
    repo = repo_with_uncommitted(tmp_path, CALC, STUBBED)
    runner = CliRunner()

    blocked = runner.invoke(cli.app, ["hook", "claude-code"], input=json.dumps({"cwd": str(repo)}))
    failed = runner.invoke(
        cli.app, ["hook", "claude-code"], input=json.dumps({"cwd": str(tmp_path / "x")})
    )

    assert blocked.exit_code == 0
    assert json.loads(blocked.stdout)["decision"] == "block"
    assert failed.exit_code == 1
    assert "agent-diff-guard:" in failed.output
