"""The unit of input every rule sees: one file changed between base and head."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


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
    """

    path: str
    status: FileStatus
    base_src: str | None
    head_src: str | None
    added_lines: frozenset[int] = frozenset()
    removed_lines: frozenset[int] = frozenset()
