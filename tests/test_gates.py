from __future__ import annotations

import pytest

from agent_diff_guard.gates import (
    Gates,
    from_ini,
    from_pyproject,
    strip_yaml_comment,
    workflow_tool_counts,
)


def test_pyproject_gates() -> None:
    gates = from_pyproject(
        """
        [tool.coverage.report]
        fail_under = 85.5

        [tool.ruff]
        ignore = ["E501"]
        extend-ignore = "W291, W293"

        [tool.ruff.per-file-ignores]
        "tests/*" = ["S101"]

        [tool.ruff.lint]
        extend-ignore = ["B008"]

        [tool.ruff.lint.extend-per-file-ignores]
        "src/legacy.py" = "E722"

        [tool.mypy]
        strict = true
        ignore_errors = true
        disable_error_code = ["import-untyped"]

        [[tool.mypy.overrides]]
        module = "pkg.legacy"
        ignore_errors = true

        [[tool.mypy.overrides]]
        module = ["pkg.a", "pkg.b"]
        disable_error_code = "misc"

        [[tool.mypy.overrides]]
        ignore_errors = false
        """.replace("\n        ", "\n")
    )

    assert gates == Gates(
        fail_under=85.5,
        ruff_ignores=frozenset(
            {"E501", "W291", "W293", "tests/*:S101", "B008", "src/legacy.py:E722"}
        ),
        mypy_strict=True,
        mypy_disabled_codes=frozenset({"*:import-untyped", "pkg.a:misc", "pkg.b:misc"}),
        mypy_ignore_errors=frozenset({"*", "pkg.legacy"}),
    )


@pytest.mark.parametrize(
    "text",
    [
        "",
        "[tool]\ncoverage = 1\n",
        "[tool.coverage.report]\nfail_under = true\n",
        "[tool.coverage.report]\nfail_under = 'high'\n",
        "[tool.mypy]\noverrides = 'x'\n",
        "[tool.mypy]\noverrides = [1]\n",
        "[tool.ruff]\nignore = 5\n",
    ],
)
def test_pyproject_without_usable_gates(text: str) -> None:
    assert from_pyproject(text) == Gates()


def test_pyproject_string_threshold_and_invalid_toml() -> None:
    assert from_pyproject("[tool.coverage.report]\nfail_under = '80'\n") == Gates(fail_under=80.0)
    assert from_pyproject("[tool.coverage.report\n") is None


def test_ini_gates() -> None:
    text = """
[coverage:report]
fail_under = 75

[mypy]
strict = yes
ignore_errors = no
disable_error_code = attr-defined, misc

[mypy-pkg.*]
ignore_errors = True

[flake8]
ignore = E501
"""
    assert from_ini(text, "setup.cfg") == Gates(
        fail_under=75.0,
        mypy_strict=True,
        mypy_disabled_codes=frozenset({"*:attr-defined", "*:misc"}),
        mypy_ignore_errors=frozenset({"pkg.*"}),
    )
    assert from_ini("[report]\nfail_under = 60\n", ".coveragerc") == Gates(fail_under=60.0)
    assert from_ini("[report]\nfail_under = 60\n", "tox.ini") == Gates()
    assert from_ini("not ini at all", "setup.cfg") is None


def test_workflow_tool_counts_ignore_comments() -> None:
    text = """
# pytest is not run here
steps:
  - run: ruff check . && ruff format --check .  # then pytest
  - run: |
      pytest -q
      python -m mypy src
"""
    assert workflow_tool_counts(text) == {"ruff": 2, "pytest": 1, "mypy": 1}


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("  # comment", ""),
        ("run: pytest  # trailing", "run: pytest "),
        ("run: echo '#1'", "run: echo '#1'"),
    ],
)
def test_strip_yaml_comment(line: str, expected: str) -> None:
    assert strip_yaml_comment(line) == expected
