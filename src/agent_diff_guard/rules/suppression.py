"""R3 suppression: ADG020 suppression-added."""

from __future__ import annotations

import re

from agent_diff_guard.astutil import comments, excess_sites, source_line
from agent_diff_guard.change import ChangedFile
from agent_diff_guard.classify import is_python_file
from agent_diff_guard.rules.base import Finding, RunContext, Severity, registry

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


registry.register(SuppressionAddedRule())
