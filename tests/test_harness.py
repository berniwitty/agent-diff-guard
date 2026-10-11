from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.harness import (
    ExpectedFinding,
    build_repo,
    discover_cases,
    git,
    load_expected,
)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_build_repo_records_modify_add_and_delete(tmp_path: Path) -> None:
    case = tmp_path / "case"
    write(case / "before" / "src" / "calc.py", "def add(a, b):\n    return a + b\n")
    write(case / "before" / "tests" / "test_old.py", "def test_old():\n    assert True\n")
    write(case / "after" / "src" / "calc.py", "def add(a, b):\n    pass\n")
    write(case / "after" / "tests" / "test_new.py", "def test_new():\n    assert 1\n")

    repo = build_repo(case, tmp_path / "repo")

    status = git(repo.path, "diff", "--name-status", "--no-renames", repo.base, repo.head)
    assert sorted(status.splitlines()) == [
        "A\ttests/test_new.py",
        "D\ttests/test_old.py",
        "M\tsrc/calc.py",
    ]
    assert git(repo.path, "show", f"{repo.head}:src/calc.py") == "def add(a, b):\n    pass"
    assert git(repo.path, "status", "--porcelain") == ""


def test_build_repo_without_before_adds_everything(tmp_path: Path) -> None:
    case = tmp_path / "case"
    write(case / "after" / "mod.py", "x = 1\n")

    repo = build_repo(case, tmp_path / "repo")

    assert git(repo.path, "ls-tree", "-r", "--name-only", repo.base) == ""
    assert git(repo.path, "diff", "--name-status", repo.base, repo.head) == "A\tmod.py"


def test_build_repo_without_after_deletes_everything(tmp_path: Path) -> None:
    case = tmp_path / "case"
    write(case / "before" / "tests" / "test_x.py", "def test_x():\n    assert 1\n")

    repo = build_repo(case, tmp_path / "repo")

    assert git(repo.path, "diff", "--name-status", repo.base, repo.head) == "D\ttests/test_x.py"


def test_build_repo_rejects_case_without_trees(tmp_path: Path) -> None:
    (tmp_path / "case").mkdir()
    with pytest.raises(ValueError, match="before/ or after/"):
        build_repo(tmp_path / "case", tmp_path / "repo")


def test_build_repo_preserves_line_endings(tmp_path: Path) -> None:
    case = tmp_path / "case"
    (case / "before").mkdir(parents=True)
    (case / "before" / "a.py").write_bytes(b"x = 1\r\n")
    (case / "after").mkdir()
    (case / "after" / "a.py").write_bytes(b"x = 2\r\n")

    repo = build_repo(case, tmp_path / "repo")

    # "x = 2\r\n" is 7 bytes; 6 would mean git converted CRLF to LF on commit.
    assert git(repo.path, "cat-file", "-s", f"{repo.head}:a.py") == "7"


def test_load_expected_parses_findings(tmp_path: Path) -> None:
    path = tmp_path / "expected.json"
    path.write_text(
        json.dumps(
            {
                "findings": [
                    {"rule_id": "ADG002", "path": "tests/test_a.py", "line": 3},
                    {"rule_id": "ADG001", "path": "tests/test_b.py", "line": None},
                ]
            }
        ),
        encoding="utf-8",
    )

    assert load_expected(path) == (
        ExpectedFinding("ADG002", "tests/test_a.py", 3),
        ExpectedFinding("ADG001", "tests/test_b.py", None),
    )


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ([], "'findings' list"),
        ({"findings": {}}, "'findings' list"),
        ({"findings": [{"rule_id": "ADG001", "path": "a.py"}]}, "exactly rule_id"),
        ({"findings": ["ADG001"]}, "exactly rule_id"),
        ({"findings": [{"rule_id": "ADG001", "path": "a.py", "line": "3"}]}, "line must be"),
        ({"findings": [{"rule_id": "ADG001", "path": "a.py", "line": True}]}, "line must be"),
    ],
)
def test_load_expected_rejects_malformed(tmp_path: Path, payload: object, message: str) -> None:
    path = tmp_path / "expected.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        load_expected(path)


def test_discover_cases_walks_rule_kind_case(tmp_path: Path) -> None:
    root = tmp_path / "fixtures"
    for rel in [
        "ADG002/positive/skip_decorator",
        "ADG002/negative/existing_skip",
        "ADG001/positive/file_deleted",
        "ADG001/notes",
    ]:
        (root / rel).mkdir(parents=True)
    write(root / "ADG002" / "positive" / "skip_decorator" / "expected.json", '{"findings": []}')
    write(root / "README.md", "not a rule directory")

    cases = discover_cases(root)

    assert [c.id for c in cases] == [
        "ADG001/positive/file_deleted",
        "ADG002/positive/skip_decorator",
        "ADG002/negative/existing_skip",
    ]
    assert cases[1].expected() == ()


def test_discover_cases_missing_root(tmp_path: Path) -> None:
    assert discover_cases(tmp_path / "nope") == []
