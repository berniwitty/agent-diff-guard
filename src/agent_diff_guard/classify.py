"""Decide what kind of file a path is, from the path alone."""

from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import PurePosixPath

# A pattern ending in "/" matches any directory component; others match the file name.
DEFAULT_TEST_PATTERNS: tuple[str, ...] = ("tests/", "test_*.py", "*_test.py", "conftest.py")

PYTHON_SUFFIXES = frozenset({".py", ".pyi"})


def is_test_file(path: str, patterns: tuple[str, ...] = DEFAULT_TEST_PATTERNS) -> bool:
    parts = PurePosixPath(path).parts
    directories, name = parts[:-1], parts[-1]
    for pattern in patterns:
        if pattern.endswith("/"):
            if any(fnmatchcase(directory, pattern[:-1]) for directory in directories):
                return True
        elif fnmatchcase(name, pattern):
            return True
    return False


def is_python_file(path: str) -> bool:
    return PurePosixPath(path).suffix in PYTHON_SUFFIXES
