"""Inline suppressions: ``# adg: allow ADG003 reason="..."`` on the flagged line."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agent_diff_guard.astutil import comments

if TYPE_CHECKING:
    # Annotation-only: rules/suppression.py imports this module while rules/ initialises.
    from agent_diff_guard.rules.base import Finding

_ALLOW = re.compile(
    r"""\#\s*adg:\s*allow\s+
        (?P<ids>ADG\d{3}(?:\s*,\s*ADG\d{3})*)
        (?:\s+reason=(?P<quote>["'])(?P<reason>.*?)(?P=quote))?""",
    re.IGNORECASE | re.VERBOSE,
)


@dataclass(frozen=True)
class Allow:
    line: int
    rule_ids: frozenset[str]
    reason: str | None  # None when missing or blank: such an allow suppresses nothing
    text: str


@dataclass(frozen=True)
class Suppressed:
    finding: Finding
    reason: str


def parse_allows(source: str) -> list[Allow]:
    """Every ``adg: allow`` directive in a real comment (not a string) of ``source``."""
    allows = []
    for line, comment in comments(source) or []:
        for match in _ALLOW.finditer(comment):
            ids = frozenset(part.strip().upper() for part in match.group("ids").split(","))
            reason = (match.group("reason") or "").strip() or None
            allows.append(Allow(line, ids, reason, match.group(0).lstrip("#").strip()))
    return allows


def apply_suppressions(
    findings: Iterable[Finding], sources: Mapping[str, str]
) -> tuple[list[Finding], list[Suppressed]]:
    """Split findings into (kept, suppressed) using allows in each file's head source.

    A finding with a line is suppressed by an allow on that line. A finding without one
    (such as a removed test, which no longer has a line) is suppressed by an allow for
    its rule anywhere in the file.
    """
    allows_by_path: dict[str, list[Allow]] = {}
    kept: list[Finding] = []
    suppressed: list[Suppressed] = []
    for finding in findings:
        source = sources.get(finding.path)
        if source is None:
            kept.append(finding)
            continue
        if finding.path not in allows_by_path:
            allows_by_path[finding.path] = parse_allows(source)
        reason = next(
            (
                allow.reason
                for allow in allows_by_path[finding.path]
                if finding.line in (None, allow.line)
                and finding.rule_id in allow.rule_ids
                and allow.reason is not None
            ),
            None,
        )
        if reason is None:
            kept.append(finding)
        else:
            suppressed.append(Suppressed(finding, reason))
    return kept, suppressed
