"""Build throwaway git repositories from rule fixtures.

A fixture case is laid out as::

    tests/fixtures/<RULE_ID>/<positive|negative>/<case>/
        before/        # tree at the base commit
        after/         # tree at the head commit
        expected.json  # {"findings": [{"rule_id": ..., "path": ..., "line": ...}]}

Git does not store empty directories, so a missing ``before/`` or ``after/`` means an
empty tree (every file added, or every file deleted). A case must have at least one.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

FIXTURES_ROOT = Path(__file__).parent / "fixtures"
KINDS = ("positive", "negative")

_REPO_CONFIG = {
    "user.name": "adg-fixture",
    "user.email": "fixture@adg.invalid",
    "core.autocrlf": "false",
    "commit.gpgsign": "false",
}


@dataclass(frozen=True)
class FixtureRepo:
    path: Path
    base: str
    head: str


@dataclass(frozen=True)
class ExpectedFinding:
    rule_id: str
    path: str
    line: int | None


@dataclass(frozen=True)
class FixtureCase:
    rule_id: str
    kind: str
    name: str
    root: Path

    @property
    def id(self) -> str:
        return f"{self.rule_id}/{self.kind}/{self.name}"

    def expected(self) -> tuple[ExpectedFinding, ...]:
        return load_expected(self.root / "expected.json")


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def build_repo(case_dir: Path, dest: Path) -> FixtureRepo:
    """Create a repo at ``dest`` with a base commit from ``before/`` and head from ``after/``."""
    before, after = case_dir / "before", case_dir / "after"
    if not before.is_dir() and not after.is_dir():
        raise ValueError(f"{case_dir}: fixture needs a before/ or after/ directory")
    dest.mkdir(parents=True, exist_ok=True)
    git(dest, "init", "--quiet", "--initial-branch=main")
    for key, value in _REPO_CONFIG.items():
        git(dest, "config", key, value)
    _replace_tree(dest, before)
    base = _commit(dest, "before")
    _replace_tree(dest, after)
    head = _commit(dest, "after")
    _verify_diff(dest, base, head, before, after)
    return FixtureRepo(path=dest, base=base, head=head)


def write_tree(root: Path, files: dict[str, str]) -> None:
    """Write ``{relative path: text}`` under ``root`` with LF line endings."""
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")


def make_repo(tmp_path: Path, before: dict[str, str], after: dict[str, str]) -> FixtureRepo:
    """Build a two-commit repo from inline trees (for tests that are not rule fixtures)."""
    case = tmp_path / "case"
    write_tree(case / "before", before)
    write_tree(case / "after", after)
    (case / "before").mkdir(parents=True, exist_ok=True)
    (case / "after").mkdir(parents=True, exist_ok=True)
    return build_repo(case, tmp_path / "repo")


def load_expected(path: Path) -> tuple[ExpectedFinding, ...]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("findings"), list):
        raise ValueError(f"{path}: expected an object with a 'findings' list")
    findings = []
    for item in data["findings"]:
        if not isinstance(item, dict) or set(item) != {"rule_id", "path", "line"}:
            raise ValueError(f"{path}: each finding needs exactly rule_id, path and line")
        line = item["line"]
        if line is not None and (not isinstance(line, int) or isinstance(line, bool)):
            raise ValueError(f"{path}: line must be an integer or null, got {line!r}")
        findings.append(ExpectedFinding(rule_id=item["rule_id"], path=item["path"], line=line))
    return tuple(findings)


def discover_cases(root: Path = FIXTURES_ROOT) -> list[FixtureCase]:
    if not root.is_dir():
        return []
    cases = []
    for rule_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for kind in KINDS:
            kind_dir = rule_dir / kind
            if not kind_dir.is_dir():
                continue
            for case_dir in sorted(p for p in kind_dir.iterdir() if p.is_dir()):
                cases.append(FixtureCase(rule_dir.name, kind, case_dir.name, case_dir))
    return cases


def _replace_tree(repo: Path, source: Path) -> None:
    for entry in repo.iterdir():
        if entry.name == ".git":
            continue
        if entry.is_dir():
            shutil.rmtree(entry)
        else:
            entry.unlink()
    if source.is_dir():
        # copyfile, not copy2: copied mtimes can make git trust a stale stat cache.
        shutil.copytree(source, repo, dirs_exist_ok=True, copy_function=shutil.copyfile)


def _commit(repo: Path, message: str) -> str:
    # Rebuild the index from file contents rather than trusting stat information.
    git(repo, "read-tree", "--empty")
    git(repo, "add", "--all")
    git(repo, "commit", "--quiet", "--allow-empty", "--no-verify", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def _verify_diff(repo: Path, base: str, head: str, before: Path, after: Path) -> None:
    """Fail loudly if git's view of the change differs from the fixture trees."""
    expected = {
        rel
        for rel in _files(before) | _files(after)
        if not (before / rel).is_file()
        or not (after / rel).is_file()
        or (before / rel).read_bytes() != (after / rel).read_bytes()
    }
    actual = set(git(repo, "diff", "--name-only", "--no-renames", base, head).splitlines())
    if actual != expected:
        raise RuntimeError(
            f"{repo}: git recorded {sorted(actual)}, trees differ in {sorted(expected)}"
        )


def _files(root: Path) -> set[str]:
    if not root.is_dir():
        return set()
    return {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
