"""Command-line entry point: ``adg check``, ``adg rules``, ``adg explain``."""

from __future__ import annotations

import sys
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from agent_diff_guard.engine import EXIT_USAGE, build_context, exit_code, run_rules
from agent_diff_guard.git import DiffSpec, Git, GitError
from agent_diff_guard.report import text
from agent_diff_guard.rules import registry
from agent_diff_guard.rules.base import Severity

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Flag shortcut patterns (deleted tests, stubs, suppressions) in a git diff.",
)


class OutputFormat(StrEnum):
    TEXT = "text"
    JSON = "json"
    SARIF = "sarif"
    MARKDOWN = "markdown"


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
        Severity, typer.Option("--fail-on", help="Lowest severity that makes the exit code 1.")
    ] = Severity.ERROR,
    repo: Annotated[
        Path, typer.Option("--repo", help="Path inside the git repository to check.")
    ] = Path("."),
) -> None:
    """Check a diff for shortcut patterns.

    With no options, checks uncommitted changes (staged, unstaged and untracked)
    against HEAD.
    """
    if staged and base is not None:
        raise typer.BadParameter("--base and --staged cannot be used together.")
    if staged and head is not None:
        raise typer.BadParameter("--head and --staged cannot be used together.")
    if head is not None and base is None:
        raise typer.BadParameter("--head requires --base.")
    if output_format is not OutputFormat.TEXT:
        typer.echo(f"adg check: --format {output_format} is not implemented yet.", err=True)
        raise typer.Exit(code=EXIT_USAGE)
    try:
        git = Git.discover(repo)
        ctx = build_context(git, _diff_spec(git, base, head, staged))
    except GitError as exc:
        _emit(f"adg check: {exc}", err=True)
        raise typer.Exit(code=EXIT_USAGE) from exc
    rules = registry.all()
    findings = run_rules(rules, ctx)
    _emit(text.render(findings, files_checked=len(ctx.changes), rules_run=len(rules)))
    raise typer.Exit(code=exit_code(findings, fail_on))


def _emit(message: str, err: bool = False) -> None:
    """Echo ``message``, escaping characters the stream's encoding cannot represent.

    Evidence is copied from user code; on a console using e.g. GBK or cp1252, an emoji in
    a string literal must not crash the report.
    """
    stream = sys.stderr if err else sys.stdout
    encoding = getattr(stream, "encoding", None) or "utf-8"
    safe = message.encode(encoding, errors="backslashreplace").decode(encoding)
    typer.echo(safe, err=err)


def _diff_spec(git: Git, base: str | None, head: str | None, staged: bool) -> DiffSpec:
    if staged:
        return git.staged()
    if base is not None:
        return git.range_from_base(base, head)
    return git.working_tree()


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
    typer.echo(f"{rule.id} {rule.name} (default severity: {rule.default_severity})")
