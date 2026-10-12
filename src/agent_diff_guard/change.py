"""The unit of input every rule sees: one file changed between base and head."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class FileStatus(StrEnum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"


@dataclass(frozen=True)
class ChangedFile:
    """A file as it was at base and as it is at head.

    ``base_src`` is ``None`` for added files and ``head_src`` is ``None`` for deleted
    files. Line numbers are 1-based and refer to base (removed) or head (added).
    ``old_path`` is set only for renamed files.
    """

    path: str
    status: FileStatus
    base_src: str | None
    head_src: str | None
    added_lines: frozenset[int] = frozenset()
    removed_lines: frozenset[int] = frozenset()
    old_path: str | None = None


def all_lines(source: str) -> frozenset[int]:
    return frozenset(range(1, len(source.splitlines()) + 1))


def parse_hunk_lines(diff: str) -> tuple[frozenset[int], frozenset[int]]:
    """Return (added, removed) line numbers from a ``git diff -U0`` patch."""
    added: set[int] = set()
    removed: set[int] = set()
    for line in diff.splitlines():
        match = _HUNK_HEADER.match(line)
        if match is None:
            continue
        old_start, old_count, new_start, new_count = match.groups()
        removed.update(_span(old_start, old_count))
        added.update(_span(new_start, new_count))
    return frozenset(added), frozenset(removed)


def _span(start: str, count: str | None) -> range:
    first = int(start)
    return range(first, first + (1 if count is None else int(count)))
