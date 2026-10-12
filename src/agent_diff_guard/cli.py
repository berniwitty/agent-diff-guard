"""Command-line entry point: ``adg check``, ``adg rules``, ``adg explain``."""

from __future__ import annotations

import sys
from collections.abc import Callable
from enum import StrEnum
from importlib import resources
from pathlib import Path
from typing import Annotated

import typer

from agent_diff_guard import hooks
from agent_diff_guard.config import ConfigError
from agent_diff_guard.coverage_report import CoverageReportError
from agent_diff_guard.engine import EXIT_USAGE, Outcome, analyze, exit_code
from agent_diff_guard.git import GitError
from agent_diff_guard.report import json, markdown, sarif, text
from agent_diff_guard.rules import registry
from agent_diff_guard.rules.base import Severity

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Flag shortcut patterns (deleted tests, stubs, suppressions) in a git diff.",
)
hook_app = typer.Typer(no_args_is_help=True, help="Run adg as a coding-agent hook.")
app.add_typer(hook_app, name="hook")


class OutputFormat(StrEnum):
    TEXT = "text"
    JSON = "json"
    SARIF = "sarif"
    MARKDOWN = "markdown"


RENDERERS: dict[OutputFormat, Callable[[Outcome], str]] = {
    OutputFormat.TEXT: text.render,
    OutputFormat.JSON: json.render,
    OutputFormat.SARIF: sarif.render,
    OutputFormat.MARKDOWN: markdown.render,
}


@app.command()
def check(
    base: Annotated[
        str | None,
        typer.Option("--base", help="Check changes since HEAD (or --head) forked from REV."),
    ] = None,
    head: Annotated[
        str | None,
        typer.Option("--head", help="Check up to this commit instead of the working tree."),
    ] = None,
    staged: Annotated[
        bool, typer.Option("--staged", help="Check staged changes against HEAD.")
    ] = False,
    output_format: Annotated[
        OutputFormat, typer.Option("--format", help="Report format.")
    ] = OutputFormat.TEXT,
    fail_on: Annotated[
        Severity | None,
        typer.Option(
            "--fail-on",
            help="Lowest severity that makes the exit code 1 [default: config fail-on, or error].",
        ),
    ] = None,
    repo: Annotated[
        Path, typer.Option("--repo", help="Path inside the git repository to check.")
    ] = Path("."),
    coverage: Annotated[
        Path | None,
        typer.Option("--coverage", help="Cobertura XML coverage report, enables ADG040."),
    ] = None,
) -> None:
    """Check a diff for shortcut patterns.

    With no options, checks uncommitted changes (staged, unstaged and untracked)
    against HEAD. Configuration is read from pyproject.toml at the base revision.
    """
    if staged and base is not None:
        raise typer.BadParameter("--base and --staged cannot be used together.")
    if staged and head is not None:
        raise typer.BadParameter("--head and --staged cannot be used together.")
    if head is not None and base is None:
        raise typer.BadParameter("--head requires --base.")
    try:
        outcome, config = analyze(
            repo, registry.all(), base=base, head=head, staged=staged, coverage=coverage
        )
    except (GitError, ConfigError, CoverageReportError) as exc:
        _emit(f"adg check: {exc}", err=True)
        raise typer.Exit(code=EXIT_USAGE) from exc
    _emit(RENDERERS[output_format](outcome))
    threshold = fail_on or config.fail_on or Severity.ERROR
    raise typer.Exit(code=exit_code(outcome.findings, threshold))


def _emit(message: str, err: bool = False) -> None:
    """Echo ``message``, escaping characters the stream's encoding cannot represent.

    Evidence is copied from user code; on a console using e.g. GBK or cp1252, an emoji in
    a string literal must not crash the report.
    """
    stream = sys.stderr if err else sys.stdout
    encoding = getattr(stream, "encoding", None) or "utf-8"
    safe = message.encode(encoding, errors="backslashreplace").decode(encoding)
    typer.echo(safe, err=err)


@app.command("rules")
def list_rules() -> None:
    """List registered rules."""
    rules = registry.all()
    if not rules:
        typer.echo("No rules registered.")
        return
    for rule in rules:
        typer.echo(f"{rule.id}  {rule.name:<24} {rule.default_severity}")


@app.command()
def explain(rule_id: Annotated[str, typer.Argument(help="Rule ID, e.g. ADG003.")]) -> None:
    """Explain what a rule detects."""
    rule = registry.get(rule_id.upper())
    if rule is None:
        typer.echo(f"Unknown rule ID: {rule_id}", err=True)
        raise typer.Exit(code=EXIT_USAGE)
    doc = rule_doc(rule.id)
    if doc is None:
        typer.echo(f"{rule.id} {rule.name} (default severity: {rule.default_severity})")
        return
    _emit(doc.rstrip("\n"))


# Rule docs ship inside the wheel; in a source checkout they are read from docs/rules/.
_PACKAGED_DOCS = "rule_docs"
_SOURCE_DOCS = Path(__file__).resolve().parents[2] / "docs" / "rules"


def rule_doc(rule_id: str) -> str | None:
    packaged = resources.files("agent_diff_guard").joinpath(_PACKAGED_DOCS, f"{rule_id}.md")
    if packaged.is_file():
        return packaged.read_text(encoding="utf-8")
    source = _SOURCE_DOCS / f"{rule_id}.md"
    if source.is_file():
        return source.read_text(encoding="utf-8")
    return None


@hook_app.command("claude-code")
def claude_code_hook(
    base: Annotated[
        str | None,
        typer.Option("--base", help="Check changes since forking from REV, not just uncommitted."),
    ] = None,
    fail_on: Annotated[
        Severity | None,
        typer.Option("--fail-on", help="Lowest severity that blocks [default: config, or error]."),
    ] = None,
    once: Annotated[
        bool,
        typer.Option("--once", help="Block only the first stop attempt (stop_hook_active)."),
    ] = False,
) -> None:
    """Claude Code Stop hook: reads the hook JSON on stdin, blocks while findings remain."""
    code, out, err = hooks.claude_code_stop(
        sys.stdin.read(), registry.all(), base=base, fail_on=fail_on, once=once
    )
    if out:
        typer.echo(out)
    if err:
        _emit(err, err=True)
    raise typer.Exit(code=code)
