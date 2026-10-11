"""Edge cases for the rules, beyond the fixture corpus. Changes are built in memory."""

from __future__ import annotations

import textwrap

from agent_diff_guard.change import ChangedFile, FileStatus, all_lines
from agent_diff_guard.rules import registry
from agent_diff_guard.rules.base import Finding, RunContext

CTX = RunContext()


def change(path: str, before: str | None, after: str | None) -> ChangedFile:
    before = textwrap.dedent(before) if before is not None else None
    after = textwrap.dedent(after) if after is not None else None
    if before is None:
        assert after is not None
        return ChangedFile(path, FileStatus.ADDED, None, after, added_lines=all_lines(after))
    if after is None:
        return ChangedFile(path, FileStatus.DELETED, before, None, removed_lines=all_lines(before))
    old, new = before.splitlines(), after.splitlines()
    added = frozenset(i for i, line in enumerate(new, 1) if line not in old)
    removed = frozenset(i for i, line in enumerate(old, 1) if line not in new)
    return ChangedFile(path, FileStatus.MODIFIED, before, after, added, removed)


def check(rule_id: str, changed: ChangedFile) -> list[Finding]:
    rule = registry.get(rule_id)
    assert rule is not None
    return list(rule.check(changed, CTX))


def summary(findings: list[Finding]) -> list[tuple[int | None, str]]:
    return [(f.line, f.message) for f in findings]


# ---------------------------------------------------------------- ADG002


def test_adg002_raise_skiptest_and_module_level_skip_call() -> None:
    findings = check(
        "ADG002",
        change(
            "tests/test_a.py",
            """\
            import unittest

            def test_a():
                assert 1
            """,
            """\
            import unittest

            import pytest

            pytest.skip("db unavailable", allow_module_level=True)

            def test_a():
                raise unittest.SkipTest("later")
                assert 1
            """,
        ),
    )

    assert summary(findings) == [
        (5, "Test module gained a module-level `pytest.skip`."),
        (8, "Test `test_a` now raises `unittest.SkipTest`."),
    ]


def test_adg002_pytestmark_list_and_annotated_assignment() -> None:
    before = "import pytest\n\ndef test_a():\n    assert 1\n"
    plain = check(
        "ADG002",
        change("tests/test_a.py", before, before + "\npytestmark = [pytest.mark.skip]\n"),
    )
    annotated = check(
        "ADG002",
        change(
            "tests/test_a.py",
            before,
            before + "\npytestmark: list = [pytest.mark.xfail(strict=True), pytest.mark.slow]\n",
        ),
    )

    assert summary(plain) == [(6, "Test module gained a module-level `pytest.mark.skip`.")]
    assert summary(annotated) == [(6, "Test module gained a module-level `pytest.mark.xfail`.")]


def test_adg002_ignores_other_pytestmark_targets_and_marks() -> None:
    before = "import pytest\n\ndef test_a():\n    assert 1\n"
    after = before + "\nother = pytest.mark.skip\npytestmark: list\npytestmark = pytest.mark.slow\n"
    assert check("ADG002", change("tests/test_a.py", before, after)) == []


def test_adg002_async_test_and_helper_function() -> None:
    findings = check(
        "ADG002",
        change(
            "tests/test_a.py",
            """\
            import pytest

            def helper():
                return 1

            async def test_a():
                assert helper()
            """,
            """\
            import pytest

            @pytest.mark.skip
            def helper():
                pytest.skip("not a test")

            @pytest.mark.skip
            async def test_a():
                assert helper()
            """,
        ),
    )

    assert summary(findings) == [(7, "Test `test_a` gained a `pytest.mark.skip` marker.")]


def test_adg002_skip_inside_nested_function_is_not_the_test_skipping() -> None:
    findings = check(
        "ADG002",
        change(
            "tests/test_a.py",
            "import pytest\n\ndef test_a():\n    assert 1\n",
            "import pytest\n\ndef test_a():\n    def later():\n        pytest.skip()\n"
            "    assert 1\n",
        ),
    )
    assert findings == []


def test_adg002_scope_limits() -> None:
    skip = "import pytest\n\n@pytest.mark.skip\ndef test_a():\n    assert 1\n"
    plain = "import pytest\n\ndef test_a():\n    assert 1\n"
    assert check("ADG002", change("tests/test_a.py", None, skip)) == []
    assert check("ADG002", change("tests/test_a.py", skip, None)) == []
    assert check("ADG002", change("src/a.py", plain, skip)) == []
    assert check("ADG002", change("tests/data.txt", plain, skip)) == []
    assert check("ADG002", change("tests/test_a.py", plain, "def test_a(:\n")) == []
    assert check("ADG002", change("tests/test_a.py", "class test_a:\n    pass\n", skip)) == []


# ---------------------------------------------------------------- ADG010


def test_adg010_evidence_is_truncated_and_reports_docstring_only() -> None:
    long_body = "    return " + " + ".join(f"value_{i}" for i in range(20)) + "\n"
    [long_finding] = check(
        "ADG010",
        change("src/a.py", "def f():\n" + long_body, "def f():\n    pass\n"),
    )
    [doc_finding] = check(
        "ADG010",
        change("src/a.py", "def g():\n    return 1\n", 'def g():\n    """Later."""\n'),
    )

    before, after = long_finding.evidence.split(" -> ")
    assert len(before) == 80
    assert before.endswith("...")
    assert after == "pass"
    assert doc_finding.evidence == "return 1 -> (docstring only)"


def test_adg010_async_method_and_abc_module_import() -> None:
    findings = check(
        "ADG010",
        change(
            "src/a.py",
            """\
            class Repo:
                async def load(self):
                    return await self.db.get()

                def save(self, x):
                    self.db.put(x)
            """,
            """\
            import abc

            class Repo(abc.ABC):
                async def load(self):
                    ...

                @abc.abstractmethod
                def save(self, x):
                    ...
            """,
        ),
    )

    assert summary(findings) == [
        (4, "Function `Repo.load` had real logic and now has a stub body.")
    ]


def test_adg010_ignores_unrelated_decorators_and_scope_limits() -> None:
    real = "def f():\n    return 1\n"
    stub = "import functools\n\n@functools.cache\ndef f():\n    pass\n"
    assert len(check("ADG010", change("src/a.py", real, stub))) == 1
    assert check("ADG010", change("src/a.py", real, None)) == []
    assert check("ADG010", change("src/a.py", None, stub)) == []
    assert check("ADG010", change("src/a.txt", real, stub)) == []
    assert check("ADG010", change("tests/test_a.py", real, stub)) == []
    assert check("ADG010", change("src/a.py", "def f(:\n", stub)) == []


# ---------------------------------------------------------------- ADG020


def test_adg020_directive_variants() -> None:
    findings = check(
        "ADG020",
        change(
            "src/a.py",
            "x = 1\n",
            """\
            # ruff: noqa
            x = 1  # NOQA
            y = f()  # type:ignore
            z = g()  # pylint: disable-next=invalid-name, too-many-args
            w = 2  # noqa is not needed here
            v = 3  # pragma:   no   cover
            """,
        ),
    )

    assert summary(findings) == [
        (1, "Added a `# ruff: noqa` suppression comment."),
        (2, "Added a `# NOQA` suppression comment."),
        (3, "Added a `# type:ignore` suppression comment."),
        (4, "Added a `# pylint: disable-next=invalid-name, too-many-args` suppression comment."),
        (5, "Added a `# noqa` suppression comment."),
        (6, "Added a `# pragma:   no   cover` suppression comment."),
    ]
    assert findings[1].evidence == "x = 1  # NOQA"


def test_adg020_codes_are_part_of_the_directive() -> None:
    before = "import os  # noqa: F401\n"
    after = "import os  # noqa: F401\nimport sys  # noqa: E402\n"
    assert summary(check("ADG020", change("src/a.py", before, after))) == [
        (2, "Added a `# noqa: E402` suppression comment.")
    ]


def test_adg020_ignores_non_directives_and_scope_limits() -> None:
    noqa = "import os  # noqa\n"
    assert check("ADG020", change("src/a.py", "x = 1\n", "x = 1  # see noqa docs\n")) == []
    assert check("ADG020", change("src/a.py", noqa, None)) == []
    assert check("ADG020", change("setup.cfg", "", "# noqa\n")) == []
    assert check("ADG020", change("src/a.py", 'x = """\n', noqa)) == []
    assert check("ADG020", change("src/a.py", "x = 1\n", 'x = """  # noqa\n')) == []
