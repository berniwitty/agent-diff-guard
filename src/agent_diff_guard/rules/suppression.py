"""R3 suppression: ADG020 suppression-added, ADG021 gate-loosened,
ADG099 suppression-without-reason."""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from agent_diff_guard.astutil import Site, comments, excess_sites, source_line
from agent_diff_guard.change import ChangedFile
from agent_diff_guard.classify import is_python_file
from agent_diff_guard.gates import (
    CONTINUE_ON_ERROR,
    INI_FILES,
    OR_TRUE,
    Gates,
    from_ini,
    from_pyproject,
    strip_yaml_comment,
    workflow_tool_counts,
)
from agent_diff_guard.rules.base import Finding, RunContext, Severity, registry
from agent_diff_guard.suppress import parse_allows

_DIRECTIVE = re.compile(
    r"""
      (?:(?:ruff|flake8):\s*)?noqa\b(?::\s*[a-z]+[0-9]*(?:\s*,\s*[a-z]+[0-9]*)*)?
    | type:\s*ignore\b(?:\[[^\]]*\])?
    | pragma:\s*no\s*cover\b
    | pylint:\s*disable(?:-next)?\s*=\s*[\w-]+(?:\s*,\s*[\w-]+)*
    """,
    re.IGNORECASE | re.VERBOSE,
)


class SuppressionAddedRule:
    id = "ADG020"
    name = "suppression-added"
    default_severity = Severity.WARN

    def check(self, change: ChangedFile, ctx: RunContext) -> list[Finding]:
        if not is_python_file(change.path) or change.head_src is None:
            return []
        head = _directives(change.head_src)
        base = _directives(change.base_src) if change.base_src is not None else []
        if head is None or base is None:
            return []
        shown = {(_key(text), line): text for line, text in head}
        new = excess_sites(
            (_key(text) for _, text in base),
            [(_key(text), line) for line, text in head],
            change.added_lines,
        )
        return [
            Finding(
                rule_id=self.id,
                severity=self.default_severity,
                path=change.path,
                line=line,
                message=f"Added a `# {shown[(key, line)]}` suppression comment.",
                evidence=source_line(change.head_src, line),
            )
            for key, line in new
        ]


def _directives(source: str) -> list[tuple[int, str]] | None:
    """(line, directive text) for each suppression directive in a real comment."""
    found = comments(source)
    if found is None:
        return None
    directives = []
    for line, comment in found:
        for segment in comment.split("#")[1:]:
            match = _DIRECTIVE.match(segment.strip())
            if match:
                directives.append((line, match.group(0)))
    return directives


def _key(text: str) -> str:
    return "".join(text.split()).lower()


class SuppressionWithoutReasonRule:
    id = "ADG099"
    name = "suppression-without-reason"
    default_severity = Severity.WARN

    def check(self, change: ChangedFile, ctx: RunContext) -> list[Finding]:
        if not is_python_file(change.path) or change.head_src is None:
            return []
        return [
            Finding(
                rule_id=self.id,
                severity=self.default_severity,
                path=change.path,
                line=allow.line,
                message=f"Suppression `{allow.text}` has no reason, so it suppresses nothing.",
                evidence=source_line(change.head_src, allow.line),
            )
            for allow in parse_allows(change.head_src)
            if allow.reason is None and allow.line in change.added_lines
        ]


class GateLoosenedRule:
    id = "ADG021"
    name = "gate-loosened"
    default_severity = Severity.ERROR

    def check(self, change: ChangedFile, ctx: RunContext) -> list[Finding]:
        path = PurePosixPath(change.path)
        if path.parts[-3:-1] == (".github", "workflows") and path.suffix in (".yml", ".yaml"):
            found = _workflow_loosening(change)
        elif path.name == "pyproject.toml" or path.name in INI_FILES:
            found = _config_loosening(change, path.name)
        else:
            return []
        return [
            Finding(self.id, self.default_severity, change.path, line, message, evidence)
            for line, message, evidence in found
        ]


_Loosening = tuple[int | None, str, str]


def _config_loosening(change: ChangedFile, filename: str) -> list[_Loosening]:
    def gates(text: str | None) -> Gates | None:
        if text is None:
            return Gates()
        return from_pyproject(text) if filename == "pyproject.toml" else from_ini(text, filename)

    before, after = gates(change.base_src), gates(change.head_src)
    if before is None or after is None:
        return []
    head = change.head_src or ""
    found: list[_Loosening] = []

    def report(needle: str, message: str, present: bool = True) -> None:
        line = _line_with(head, needle, change.added_lines) if present else None
        evidence = source_line(head, line) if line else f"{needle} (removed)"
        found.append((line, message, evidence))

    if before.fail_under is not None:
        if after.fail_under is None:
            report("fail_under", f"Coverage fail_under ({before.fail_under:g}) was removed.", False)
        elif after.fail_under < before.fail_under:
            report(
                "fail_under",
                f"Coverage fail_under lowered from {before.fail_under:g} to {after.fail_under:g}.",
            )
    for entry in sorted(after.ruff_ignores - before.ruff_ignores):
        pattern, _, code = entry.rpartition(":")
        if pattern:
            report(pattern, f"Added ruff per-file ignore `{code}` for `{pattern}`.")
        else:
            report(code, f"Added ruff ignore `{code}`.")
    if before.mypy_strict and not after.mypy_strict:
        report("strict", "Turned off mypy strict mode.", "strict" in head)
    for entry in sorted(after.mypy_disabled_codes - before.mypy_disabled_codes):
        module, _, code = entry.partition(":")
        scope = "" if module == "*" else f" for `{module}`"
        report(code, f"Disabled mypy error code `{code}`{scope}.")
    for module in sorted(after.mypy_ignore_errors - before.mypy_ignore_errors):
        scope = "everywhere" if module == "*" else f"for `{module}`"
        report("ignore_errors", f"Set mypy `ignore_errors` {scope}.")
    return found


def _workflow_loosening(change: ChangedFile) -> list[_Loosening]:
    base, head = change.base_src or "", change.head_src or ""
    found: list[_Loosening] = []
    before, after = workflow_tool_counts(base), workflow_tool_counts(head)
    for tool in sorted(before):
        if after[tool] < before[tool]:
            message = (
                f"Workflow no longer runs `{tool}`."
                if after[tool] == 0
                else f"Workflow runs `{tool}` fewer times ({before[tool]} -> {after[tool]})."
            )
            evidence = next(
                (line.strip() for line in base.splitlines() if tool in strip_yaml_comment(line)),
                tool,
            )
            found.append((None, message, f"removed: {evidence}"))
    for pattern, message in (
        (CONTINUE_ON_ERROR, "Added `continue-on-error: true` to a workflow step."),
        (OR_TRUE, "A workflow command now ignores its exit status with `|| true`."),
    ):
        for _, line in excess_sites(
            (key for key, _ in _pattern_sites(pattern, base)),
            _pattern_sites(pattern, head),
            change.added_lines,
        ):
            found.append((line, message, source_line(head, line)))
    return found


def _pattern_sites(pattern: re.Pattern[str], text: str) -> list[Site]:
    return [
        (pattern.pattern, number)
        for number, line in enumerate(text.splitlines(), 1)
        if pattern.search(strip_yaml_comment(line))
    ]


def _line_with(source: str, needle: str, added: frozenset[int]) -> int | None:
    """First line containing ``needle``, preferring added lines."""
    lines = [n for n, text in enumerate(source.splitlines(), 1) if needle in text]
    preferred = [n for n in lines if n in added]
    candidates = preferred or lines
    return candidates[0] if candidates else None


registry.register(SuppressionAddedRule())
registry.register(SuppressionWithoutReasonRule())
registry.register(GateLoosenedRule())
