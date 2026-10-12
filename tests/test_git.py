from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_diff_guard import git as git_module
from agent_diff_guard.change import ChangedFile, FileStatus
from agent_diff_guard.git import DiffSpec, Git, GitError, HeadKind, RawEntry, parse_raw
from tests.harness import git, make_repo

SHA_A = "a" * 40
SHA_B = "b" * 40


def by_path(changes: list[ChangedFile]) -> dict[str, ChangedFile]:
    return {change.path: change for change in changes}


def test_parse_raw_reads_plain_and_rename_records() -> None:
    output = (
        f":100644 100644 {SHA_A} {SHA_B} M\0src/a.py\0"
        f":100644 100644 {SHA_A} {SHA_B} R087\0old name.py\0new name.py\0"
        f":000000 100644 {'0' * 40} {SHA_B} A\0caf\xc3\xa9.py\0"
    ).encode("latin-1")

    assert parse_raw(output) == [
        RawEntry("100644", "100644", SHA_A, SHA_B, "M", "src/a.py"),
        RawEntry("100644", "100644", SHA_A, SHA_B, "R", "new name.py", "old name.py"),
        RawEntry("000000", "100644", "0" * 40, SHA_B, "A", "café.py"),
    ]


def test_parse_raw_empty_output() -> None:
    assert parse_raw(b"") == []


def test_parse_raw_rejects_malformed_record() -> None:
    with pytest.raises(GitError, match="unexpected git diff --raw record"):
        parse_raw(b":100644 M\0a.py\0")


def test_commit_range_reports_modified_lines(tmp_path: Path) -> None:
    repo = make_repo(
        tmp_path,
        {"a.py": "one\ntwo\nthree\nfour\n"},
        {"a.py": "one\nTWO\nthree\nfour\nfive\n"},
    )
    g = Git.discover(repo.path)

    [change] = g.changed_files(g.range_from_base(repo.base, repo.head))

    assert change == ChangedFile(
        path="a.py",
        status=FileStatus.MODIFIED,
        base_src="one\ntwo\nthree\nfour\n",
        head_src="one\nTWO\nthree\nfour\nfive\n",
        added_lines=frozenset({2, 5}),
        removed_lines=frozenset({2}),
    )


def test_commit_range_reports_added_deleted_and_renamed(tmp_path: Path) -> None:
    body = "".join(f"line {i}\n" for i in range(20))
    repo = make_repo(
        tmp_path,
        {"old/mod.py": body, "gone.py": "x = 1\ny = 2\n"},
        {"new/mod.py": body + "extra\n", "fresh.py": "z = 3\n"},
    )
    g = Git.discover(repo.path)

    changes = by_path(g.changed_files(g.range_from_base(repo.base, repo.head)))

    assert sorted(changes) == ["fresh.py", "gone.py", "new/mod.py"]
    renamed = changes["new/mod.py"]
    assert renamed.status is FileStatus.RENAMED
    assert renamed.old_path == "old/mod.py"
    assert renamed.base_src == body
    assert renamed.added_lines == frozenset({21})
    assert renamed.removed_lines == frozenset()
    assert changes["gone.py"] == ChangedFile(
        "gone.py", FileStatus.DELETED, "x = 1\ny = 2\n", None, removed_lines=frozenset({1, 2})
    )
    assert changes["fresh.py"] == ChangedFile(
        "fresh.py", FileStatus.ADDED, None, "z = 3\n", added_lines=frozenset({1})
    )


def test_range_from_base_uses_merge_base(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, {"a.py": "a = 1\n"}, {"a.py": "a = 1\n", "feature.py": "f = 1\n"})
    # main moves on after the feature branch forked from repo.base
    git(repo.path, "branch", "feature", repo.head)
    git(repo.path, "reset", "--hard", "--quiet", repo.base)
    (repo.path / "main_only.py").write_bytes(b"m = 1\n")
    git(repo.path, "add", "main_only.py")
    git(repo.path, "commit", "--quiet", "-m", "main moves on")
    git(repo.path, "checkout", "--quiet", "feature")
    g = Git.discover(repo.path)

    spec = g.range_from_base("main", "feature")

    assert spec == DiffSpec(base=repo.base, head_kind=HeadKind.COMMIT, head=repo.head)
    assert [c.path for c in g.changed_files(spec)] == ["feature.py"]


def test_working_tree_includes_unstaged_untracked_and_deleted(tmp_path: Path) -> None:
    repo = make_repo(
        tmp_path, {}, {"a.py": "a = 1\n", "b.py": "b = 1\n", ".gitignore": "ignored.py\n"}
    )
    (repo.path / "a.py").write_bytes(b"a = 2\n")
    (repo.path / "b.py").unlink()
    (repo.path / "new.py").write_bytes(b"n = 1\n")
    (repo.path / "ignored.py").write_bytes(b"i = 1\n")
    g = Git.discover(repo.path)

    changes = by_path(g.changed_files(g.working_tree()))

    assert sorted(changes) == ["a.py", "b.py", "new.py"]
    assert changes["a.py"].head_src == "a = 2\n"
    assert changes["a.py"].added_lines == frozenset({1})
    assert changes["b.py"].status is FileStatus.DELETED
    assert changes["new.py"] == ChangedFile(
        "new.py", FileStatus.ADDED, None, "n = 1\n", added_lines=frozenset({1})
    )


def test_range_from_base_without_head_reads_working_tree(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, {"a.py": "a = 1\n"}, {"a.py": "a = 2\n"})
    (repo.path / "a.py").write_bytes(b"a = 3\n")
    g = Git.discover(repo.path)

    spec = g.range_from_base(repo.base)
    [change] = g.changed_files(spec)

    assert spec.head_kind is HeadKind.WORKTREE
    assert (change.base_src, change.head_src) == ("a = 1\n", "a = 3\n")


def test_staged_reads_index_not_working_tree(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, {}, {"a.py": "a = 1\n", "b.py": "b = 1\n"})
    (repo.path / "a.py").write_bytes(b"a = 2\n")
    git(repo.path, "add", "a.py")
    (repo.path / "a.py").write_bytes(b"a = 3\n")
    (repo.path / "b.py").write_bytes(b"b = 2\n")
    (repo.path / "untracked.py").write_bytes(b"u = 1\n")
    g = Git.discover(repo.path)

    [change] = g.changed_files(g.staged())

    assert (change.path, change.head_src) == ("a.py", "a = 2\n")


def test_discover_from_subdirectory_finds_root(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, {}, {"pkg/a.py": "a = 1\n"})
    assert Git.discover(repo.path / "pkg").root.resolve() == repo.path.resolve()


def test_submodule_entries_are_skipped(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, {}, {"a.py": "a = 1\n"})
    git(repo.path, "update-index", "--add", "--cacheinfo", f"160000,{repo.head},vendor/sub")
    git(repo.path, "commit", "--quiet", "-m", "add gitlink")
    g = Git.discover(repo.path)

    assert g.changed_files(g.range_from_base(repo.head, "HEAD")) == []


def test_utf8_bom_is_stripped(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, {}, {})
    (repo.path / "bom.py").write_bytes(b"\xef\xbb\xbfx = 1\n")
    g = Git.discover(repo.path)

    [change] = g.changed_files(g.working_tree())

    assert change.head_src == "x = 1\n"


def test_unmerged_paths_are_rejected(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, {"a.py": "a = 0\n"}, {"a.py": "a = 1\n"})
    git(repo.path, "checkout", "--quiet", "-b", "other", repo.base)
    (repo.path / "a.py").write_bytes(b"a = 2\n")
    git(repo.path, "commit", "--quiet", "-am", "conflict")
    with pytest.raises(subprocess.CalledProcessError):
        git(repo.path, "merge", "--quiet", "main")
    g = Git.discover(repo.path)

    with pytest.raises(GitError, match=r"a\.py has unresolved merge conflicts"):
        g.changed_files(g.working_tree())
    with pytest.raises(GitError, match=r"a\.py has unresolved merge conflicts"):
        g.changed_files(g.staged())


def test_unknown_status_is_rejected(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, {}, {"a.py": "a = 1\n"})
    g = Git.discover(repo.path)
    spec = g.working_tree()
    entry = RawEntry("100644", "100644", SHA_A, SHA_B, "X", "a.py")

    with pytest.raises(GitError, match="unsupported git status 'X'"):
        g._to_change(spec, entry)


def test_not_a_repository(tmp_path: Path) -> None:
    with pytest.raises(GitError, match="git rev-parse failed"):
        Git.discover(tmp_path)


def test_unknown_revision(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, {}, {"a.py": "a = 1\n"})
    with pytest.raises(GitError, match="'nope' is not a commit"):
        Git.discover(repo.path).range_from_base("nope")


def test_unrelated_histories(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, {}, {"a.py": "a = 1\n"})
    git(repo.path, "checkout", "--quiet", "--orphan", "island")
    git(repo.path, "commit", "--quiet", "-m", "unrelated")
    with pytest.raises(GitError, match="'main' and 'HEAD' have no common ancestor"):
        Git.discover(repo.path).range_from_base("main")


def test_missing_git_executable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def no_git(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("git")

    monkeypatch.setattr(git_module.subprocess, "run", no_git)
    with pytest.raises(GitError, match="git executable not found"):
        Git.discover(tmp_path)


def is_py(path: str) -> bool:
    return path.endswith(".py")


def test_head_sources_commit_reads_unchanged_files_too(tmp_path: Path) -> None:
    repo = make_repo(
        tmp_path,
        {"tests/test_a.py": "a = 1\n", "notes.txt": "n\n"},
        {"tests/test_a.py": "a = 1\n", "tests/test_b.py": "b = 2\n", "notes.txt": "n\n"},
    )
    g = Git.discover(repo.path)

    sources = g.head_sources(g.range_from_base(repo.base, repo.head), is_py)

    assert sources == {"tests/test_a.py": "a = 1\n", "tests/test_b.py": "b = 2\n"}


def test_head_sources_index_and_worktree(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, {}, {"a.py": "a = 1\n", "gone.py": "g = 1\n"})
    (repo.path / "a.py").write_bytes(b"a = 2\n")
    git(repo.path, "add", "a.py")
    (repo.path / "a.py").write_bytes(b"a = 3\n")
    (repo.path / "gone.py").unlink()
    (repo.path / "new.py").write_bytes(b"n = 1\n")
    g = Git.discover(repo.path)

    staged = g.head_sources(g.staged(), is_py)
    worktree = g.head_sources(g.working_tree(), is_py)

    assert staged == {"a.py": "a = 2\n", "gone.py": "g = 1\n"}
    assert worktree == {"a.py": "a = 3\n", "new.py": "n = 1\n"}


def test_head_sources_skips_gitlinks(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, {}, {"a.py": "a = 1\n"})
    git(repo.path, "update-index", "--add", "--cacheinfo", f"160000,{repo.head},vendor/sub.py")
    git(repo.path, "commit", "--quiet", "-m", "add gitlink")
    g = Git.discover(repo.path)

    assert g.head_sources(g.range_from_base(repo.base, "HEAD"), is_py) == {"a.py": "a = 1\n"}
    assert g.head_sources(g.staged(), is_py) == {"a.py": "a = 1\n"}


def test_blobs_reports_missing_objects(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, {}, {"a.py": "a = 1\n"})
    g = Git.discover(repo.path)
    with pytest.raises(GitError, match=f"cannot read blob {SHA_A}: {SHA_A} missing"):
        g._blobs([SHA_A])
    assert g._blobs([]) == {}
