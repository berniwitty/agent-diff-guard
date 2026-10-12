"""All git access for adg: resolve revisions, list changed files, read file contents."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from agent_diff_guard.change import ChangedFile, FileStatus, all_lines, parse_hunk_lines

ZERO_SHA = "0" * 40
# Submodules (gitlinks) and symlinks have no source text to analyse.
_SKIPPED_MODES = frozenset({"160000", "120000"})
_STATUS = {
    "A": FileStatus.ADDED,
    "C": FileStatus.ADDED,
    "D": FileStatus.DELETED,
    "M": FileStatus.MODIFIED,
    "T": FileStatus.MODIFIED,
    "R": FileStatus.RENAMED,
}


class GitError(Exception):
    """git failed, or the repository is in a state adg cannot read."""


class HeadKind(StrEnum):
    COMMIT = "commit"
    INDEX = "index"
    WORKTREE = "worktree"


@dataclass(frozen=True)
class DiffSpec:
    """What to compare: a base commit against a head commit, the index, or the worktree."""

    base: str
    head_kind: HeadKind
    head: str | None = None


@dataclass(frozen=True)
class RawEntry:
    """One record of ``git diff --raw -z``."""

    old_mode: str
    new_mode: str
    old_sha: str
    new_sha: str
    status: str
    path: str
    old_path: str | None = None


def parse_raw(output: bytes) -> list[RawEntry]:
    fields = output.split(b"\0")
    entries = []
    i = 0
    while i < len(fields) and fields[i]:
        meta = fields[i].decode("ascii").lstrip(":").split(" ")
        if len(meta) != 5:
            raise GitError(f"unexpected git diff --raw record: {fields[i]!r}")
        old_mode, new_mode, old_sha, new_sha, status = meta
        first = _decode_path(fields[i + 1])
        if status[0] in "RC":
            entries.append(
                RawEntry(
                    old_mode,
                    new_mode,
                    old_sha,
                    new_sha,
                    status[0],
                    _decode_path(fields[i + 2]),
                    first,
                )
            )
            i += 3
        else:
            entries.append(RawEntry(old_mode, new_mode, old_sha, new_sha, status[0], first))
            i += 2
    return entries


class Git:
    def __init__(self, root: Path) -> None:
        self.root = root

    @classmethod
    def discover(cls, path: Path) -> Git:
        top = _run(path, ["rev-parse", "--show-toplevel"]).decode("utf-8").strip()
        return cls(Path(top))

    def run(self, *args: str) -> bytes:
        return _run(self.root, list(args))

    def resolve_commit(self, rev: str) -> str:
        try:
            out = self.run(
                "rev-parse", "--verify", "--quiet", "--end-of-options", f"{rev}^{{commit}}"
            )
        except GitError as exc:
            raise GitError(f"{rev!r} is not a commit in {self.root}") from exc
        return out.decode("ascii").strip()

    def range_from_base(self, base: str, head: str | None = None) -> DiffSpec:
        """Changes since ``base`` forked: to ``head`` if given, else to the working tree."""
        head_sha = self.resolve_commit(head) if head is not None else None
        tip = head_sha if head_sha is not None else self.resolve_commit("HEAD")
        base_sha = self.resolve_commit(base)
        try:
            fork = self.run("merge-base", base_sha, tip).decode("ascii").strip()
        except GitError as exc:
            raise GitError(f"{base!r} and {head or 'HEAD'!r} have no common ancestor") from exc
        if head_sha is None:
            return DiffSpec(base=fork, head_kind=HeadKind.WORKTREE)
        return DiffSpec(base=fork, head_kind=HeadKind.COMMIT, head=head_sha)

    def staged(self) -> DiffSpec:
        return DiffSpec(base=self.resolve_commit("HEAD"), head_kind=HeadKind.INDEX)

    def working_tree(self) -> DiffSpec:
        return DiffSpec(base=self.resolve_commit("HEAD"), head_kind=HeadKind.WORKTREE)

    def changed_files(self, spec: DiffSpec) -> list[ChangedFile]:
        if spec.head_kind is not HeadKind.COMMIT:
            self._reject_unmerged()
        raw = self.run("diff", "--raw", "-z", "--no-abbrev", "-M", *self._rev_args(spec))
        changes = [
            self._to_change(spec, entry) for entry in parse_raw(raw) if _is_text_entry(entry)
        ]
        if spec.head_kind is HeadKind.WORKTREE:
            changes.extend(self._untracked())
        return sorted(changes, key=lambda change: change.path)

    def _rev_args(self, spec: DiffSpec) -> list[str]:
        if spec.head_kind is HeadKind.COMMIT:
            assert spec.head is not None
            return [spec.base, spec.head]
        if spec.head_kind is HeadKind.INDEX:
            return ["--cached", spec.base]
        return [spec.base]

    def _reject_unmerged(self) -> None:
        """Conflicted files show up as ordinary modifications in a worktree diff; refuse them."""
        out = self.run("ls-files", "--unmerged", "-z")
        paths = sorted({_decode_path(rec.split(b"\t", 1)[1]) for rec in out.split(b"\0") if rec})
        if paths:
            raise GitError(f"{', '.join(paths)} has unresolved merge conflicts")

    def _to_change(self, spec: DiffSpec, entry: RawEntry) -> ChangedFile:
        status = _STATUS.get(entry.status)
        if status is None:
            raise GitError(f"{entry.path} has unsupported git status {entry.status!r}")
        base_src = None if status is FileStatus.ADDED else self._blob(entry.old_sha)
        head_src = None if status is FileStatus.DELETED else self._head_text(entry)
        if head_src is None:
            assert base_src is not None
            return ChangedFile(
                entry.path, status, base_src, None, removed_lines=all_lines(base_src)
            )
        if base_src is None:
            return ChangedFile(entry.path, status, None, head_src, added_lines=all_lines(head_src))
        old_path = entry.old_path if status is FileStatus.RENAMED else None
        added, removed = self._line_changes(spec, entry)
        return ChangedFile(entry.path, status, base_src, head_src, added, removed, old_path)

    def _head_text(self, entry: RawEntry) -> str:
        if entry.new_sha != ZERO_SHA:
            return self._blob(entry.new_sha)
        return _decode((self.root / entry.path).read_bytes())

    def _blob(self, sha: str) -> str:
        return _decode(self.run("cat-file", "blob", sha))

    def _line_changes(
        self, spec: DiffSpec, entry: RawEntry
    ) -> tuple[frozenset[int], frozenset[int]]:
        paths = [entry.old_path, entry.path] if entry.old_path else [entry.path]
        patch = self.run(
            "--literal-pathspecs",
            "diff",
            "-U0",
            "--no-color",
            "--no-ext-diff",
            "-M",
            *self._rev_args(spec),
            "--",
            *paths,
        )
        return parse_hunk_lines(patch.decode("utf-8", errors="replace"))

    def _untracked(self) -> list[ChangedFile]:
        out = self.run("ls-files", "--others", "--exclude-standard", "-z")
        changes = []
        for raw_path in filter(None, out.split(b"\0")):
            path = _decode_path(raw_path)
            file = self.root / path
            if file.is_symlink() or not file.is_file():
                continue
            text = _decode(file.read_bytes())
            changes.append(
                ChangedFile(path, FileStatus.ADDED, None, text, added_lines=all_lines(text))
            )
        return changes


def _run(cwd: Path, args: list[str]) -> bytes:
    try:
        proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=False)
    except FileNotFoundError as exc:
        raise GitError("git executable not found on PATH") from exc
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace").strip()
        raise GitError(f"git {args[0]} failed in {cwd}: {detail or f'exit {proc.returncode}'}")
    return proc.stdout


def _is_text_entry(entry: RawEntry) -> bool:
    return entry.old_mode not in _SKIPPED_MODES and entry.new_mode not in _SKIPPED_MODES


def _decode(data: bytes) -> str:
    return data.decode("utf-8-sig", errors="replace")


def _decode_path(data: bytes) -> str:
    return data.decode("utf-8", errors="surrogateescape")
