"""Command-line entry point: ``adg check``, ``adg rules``, ``adg explain``."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

import typer

from agent_diff_guard.engine import EXIT_USAGE
from agent_diff_guard.rules.base import Severity, registry

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
        str | None, typer.Option("--base", help="Compare HEAD against this revision.")
    ] = None,
    staged: Annotated[bool, typer.Option("--staged", help="Check staged changes.")] = False,
    output_format: Annotated[
        OutputFormat, typer.Option("--format", help="Report format.")
    ] = OutputFormat.TEXT,
    fail_on: Annotated[
        Severity, typer.Option("--fail-on", help="Lowest severity that makes the exit code 1.")
    ] = Severity.ERROR,
) -> None:
    """Check a diff for shortcut patterns."""
    if base is not None and staged:
        raise typer.BadParameter("--base and --staged cannot be used together.")
    if registry.all():
        typer.echo("adg check: reading changes from git is not implemented yet.", err=True)
        raise typer.Exit(code=EXIT_USAGE)
    typer.echo("adg check: no rules are registered; nothing was checked.")


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
