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


# ---------------------------------------------------------------- ADG001


def test_adg001_deleted_file_with_all_tests_moved_is_not_reported() -> None:
    tests = "def test_a():\n    assert f(1) == 2\n"
    removed = change("tests/test_old.py", tests, None)
    moved = change("tests/test_new.py", None, tests)
    ctx = RunContext(changes=(removed, moved))
    rule = registry.get("ADG001")
    assert rule is not None

    assert list(rule.check(removed, ctx)) == []


def test_adg001_reports_each_removed_test_with_base_line() -> None:
    findings = check(
        "ADG001",
        change(
            "tests/test_a.py",
            "def test_a():\n    assert 1\n\n"
            "class TestB:\n    def test_b(self):\n        assert 2\n",
            "def helper():\n    pass\n",
        ),
    )
    assert [(f.line, f.message, f.evidence) for f in findings] == [
        (None, "Test `test_a` was removed.", "def test_a():  (base line 1)"),
        (None, "Test `TestB.test_b` was removed.", "def test_b(self):  (base line 5)"),
    ]


def test_adg001_scope_limits() -> None:
    tests = "def test_a():\n    assert 1\n"
    assert check("ADG001", change("tests/test_a.py", None, tests)) == []
    assert check("ADG001", change("tests/test_a.py", "def test_a(:\n", None)) == []
    assert check("ADG001", change("tests/test_a.py", tests, "def test_a(:\n")) == []
    assert check("ADG001", change("tests/helpers.py", "def make():\n    pass\n", None)) == []
    assert check("ADG001", change("tests/data.txt", tests, None)) == []


def test_adg001_similarity_threshold() -> None:
    base = "def test_a():\n    assert compute(1, 2, 3) == 6\n"
    similar = "def test_b():\n    assert compute(1, 2, 3) == 7\n"
    different = "def test_b():\n    client.post('/x')\n"
    for head, expected in ((similar, 0), (different, 1)):
        changed = change("tests/test_a.py", base, head)
        ctx = RunContext(changes=(changed,))
        rule = registry.get("ADG001")
        assert rule is not None
        assert len(list(rule.check(changed, ctx))) == expected


# ---------------------------------------------------------------- ADG003


def test_adg003_fewer_assertions_evidence_lists_removed_ones() -> None:
    [finding] = check(
        "ADG003",
        change(
            "tests/test_a.py",
            "def test_a():\n    assert f(1) == 1\n    assert f(2) == 2\n    assert f(3) == 3\n",
            "def test_a():\n    assert f(1) == 1\n",
        ),
    )
    assert finding.line == 1
    assert finding.message == "Test `test_a` has fewer assertions than before (3 -> 1)."
    assert finding.evidence == "assert f(2) == 2 | assert f(3) == 3"


def test_adg003_widened_abs_and_unpaired_approx() -> None:
    findings = check(
        "ADG003",
        change(
            "tests/test_a.py",
            "import pytest\n\ndef test_a():\n    assert x == pytest.approx(1.0)\n"
            "    assert y == pytest.approx(2.0)\n",
            "import pytest\n\ndef test_a():\n    assert x == pytest.approx(1.0, abs=0.5)\n"
            "    assert y == pytest.approx(3.0, rel=0.5)\n",
        ),
    )
    assert summary(findings) == [
        (4, "Test `test_a` widened a `pytest.approx` tolerance (abs 1e-12 -> 0.5).")
    ]


def test_adg003_scope_limits() -> None:
    strong = "def test_a():\n    assert f() == 1\n"
    weak = "def test_a():\n    assert f()\n"
    assert check("ADG003", change("src/a.py", strong, weak)) == []
    assert check("ADG003", change("tests/test_a.py", None, weak)) == []
    assert check("ADG003", change("tests/test_a.py", strong, "def test_a(:\n")) == []
    assert summary(check("ADG003", change("tests/test_a.py", strong, weak))) == [
        (2, "Test `test_a` replaced an exact assertion with a weaker check.")
    ]


# ---------------------------------------------------------------- ADG004


def adg004(test_before: str, test_after: str, *impl: ChangedFile) -> list[Finding]:
    test = change("tests/test_calc.py", test_before, test_after)
    rule = registry.get("ADG004")
    assert rule is not None
    return list(rule.check(test, RunContext(changes=(test, *impl))))


ADD_CHANGED = change(
    "src/calc.py", "def add(a, b):\n    return a + b\n", "def add(a, b):\n    return b + a\n"
)


def test_adg004_new_function_counts_as_changed() -> None:
    new_impl = change("src/calc.py", None, "def add(a, b):\n    return a + b\n")
    findings = adg004(
        "def test_a():\n    assert add(1, 1) == 3\n",
        "def test_a():\n    assert add(1, 1) == 2\n",
        new_impl,
    )
    assert summary(findings) == [
        (2, "Expected value changed from `3` to `2` while `add` was modified.")
    ]


def test_adg004_unrelated_function_change_is_ignored() -> None:
    other = change(
        "src/other.py", "def mul(a, b):\n    return a * b\n", "def mul(a, b):\n    return b * a\n"
    )
    assert (
        adg004(
            "def test_a():\n    assert add(1, 1) == 3\n",
            "def test_a():\n    assert add(1, 1) == 2\n",
            other,
        )
        == []
    )


def test_adg004_ignores_test_and_unparseable_implementation_changes() -> None:
    helper = change(
        "tests/helpers.py", "def add(a, b):\n    return 1\n", "def add(a, b):\n    return 2\n"
    )
    broken = change("src/calc.py", "def add(a, b):\n    return a\n", "def add(:\n")
    before = "def test_a():\n    assert add(1, 1) == 3\n"
    after = "def test_a():\n    assert add(1, 1) == 2\n"
    assert adg004(before, after, helper, broken) == []
    assert adg004(before, after, ADD_CHANGED, change("src/notes.txt", "a", "b")) != []


def test_adg004_repeated_identical_assertions_are_paired_one_to_one() -> None:
    before = "def test_a():\n    assert add(1, 1) == 2\n    assert add(1, 1) == 2\n"
    after = "def test_a():\n    assert add(1, 1) == 2\n    assert add(1, 1) == 3\n"
    assert summary(adg004(before, after, ADD_CHANGED)) == [
        (3, "Expected value changed from `2` to `3` while `add` was modified.")
    ]


# ---------------------------------------------------------------- ADG011


def adg011(before: str | None, after: str, *assertion_literals: frozenset[str]) -> list[Finding]:
    changed = change("src/fib.py", before, after)
    rule = registry.get("ADG011")
    assert rule is not None
    ctx = RunContext(changes=(changed,), assertion_literals=frozenset(assertion_literals))
    return list(rule.check(changed, ctx))


SEVEN_IS_13 = frozenset({"int:7", "int:13"})


def test_adg011_message_and_evidence() -> None:
    [finding] = adg011(
        "def fib(n):\n    return n\n",
        "def fib(n):\n    if n == 7:\n        return 13\n    return n\n",
        SEVEN_IS_13,
    )
    assert finding.message == "New branch in `fib` returns `13` when `n` is `7`, as a test asserts."
    assert finding.evidence == "if n == 7:"


def test_adg011_needs_a_literal_pool_and_parseable_sources() -> None:
    cheat = "def fib(n):\n    if n == 7:\n        return 13\n    return n\n"
    assert adg011("def fib(n):\n    return n\n", cheat) == []
    assert adg011("def fib(:\n", cheat, SEVEN_IS_13) == []
    assert adg011("def fib(n):\n    return n\n", "def fib(:\n", SEVEN_IS_13) == []
    changed = change("tests/test_fib.py", None, cheat)
    rule = registry.get("ADG011")
    assert rule is not None
    ctx = RunContext(changes=(changed,), assertion_literals=frozenset({SEVEN_IS_13}))
    assert list(rule.check(changed, ctx)) == []


def test_adg011_method_in_class_and_duplicate_condition() -> None:
    before = (
        "class C:\n    def f(self, n):\n        if n == 7:\n            return 1\n"
        "        return n\n"
    )
    after = (
        "class C:\n    def f(self, n):\n        if n == 7:\n            return 1\n"
        "        if n == 7:\n            return 13\n        return n\n"
    )
    findings = adg011(before, after, SEVEN_IS_13)
    assert summary(findings) == [
        (5, "New branch in `C.f` returns `13` when `n` is `7`, as a test asserts.")
    ]
