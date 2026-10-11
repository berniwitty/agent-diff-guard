from __future__ import annotations

import pytest

from agent_diff_guard.change import all_lines, parse_hunk_lines
from agent_diff_guard.classify import is_python_file, is_test_file


def test_parse_hunk_lines_handles_counts_and_pure_insertions() -> None:
    patch = "\n".join(
        [
            "diff --git a/a.py b/a.py",
            "--- a/a.py",
            "+++ b/a.py",
            "@@ -2 +2 @@ def f():",  # one line replaced (counts omitted mean 1)
            "-    return 1",
            "+    return 2",
            "@@ -10,0 +11,2 @@",  # pure insertion: count 0 on the old side
            "+x = 1",
            "+y = 2",
            "@@ -20,3 +22,0 @@",  # pure deletion
            "-a",
            "-b",
            "-c",
        ]
    )

    added, removed = parse_hunk_lines(patch)

    assert added == frozenset({2, 11, 12})
    assert removed == frozenset({2, 20, 21, 22})


def test_parse_hunk_lines_ignores_content_lines() -> None:
    assert parse_hunk_lines("+@@ -1 +1 @@\n") == (frozenset(), frozenset())


def test_all_lines() -> None:
    assert all_lines("a\nb\n") == frozenset({1, 2})
    assert all_lines("a\nb") == frozenset({1, 2})
    assert all_lines("") == frozenset()


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("tests/test_calc.py", True),
        ("tests/helpers.py", True),
        ("pkg/tests/unit/data.py", True),
        ("src/test_utils.py", True),
        ("src/calc_test.py", True),
        ("conftest.py", True),
        ("src/pkg/conftest.py", True),
        ("src/calc.py", False),
        ("src/testing.py", False),
        ("src/contest.py", False),
        ("tests.py", False),
        ("docs/tests.md", False),
    ],
)
def test_is_test_file_default_patterns(path: str, expected: bool) -> None:
    assert is_test_file(path) is expected


def test_is_test_file_custom_patterns() -> None:
    assert is_test_file("spec/calc.py", ("spec/",))
    assert not is_test_file("tests/calc.py", ("spec/",))
    assert is_test_file("src/check_calc.py", ("check_*.py",))


@pytest.mark.parametrize(
    ("path", "expected"),
    [("a.py", True), ("a.pyi", True), ("a.pyc", False), ("a.txt", False), ("py", False)],
)
def test_is_python_file(path: str, expected: bool) -> None:
    assert is_python_file(path) is expected
