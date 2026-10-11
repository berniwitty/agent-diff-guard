from __future__ import annotations

import ast
import textwrap

import pytest

from agent_diff_guard import astutil


def module(source: str) -> ast.Module:
    parsed = astutil.parse(textwrap.dedent(source))
    assert parsed is not None
    return parsed


def only_function(source: str) -> astutil.FunctionNode:
    [node] = astutil.functions(module(source)).values()
    return node


def test_parse_returns_none_for_missing_or_invalid_source() -> None:
    assert astutil.parse(None) is None
    assert astutil.parse("def f(:\n") is None
    assert astutil.parse("x = 1\0\n") is None
    assert isinstance(astutil.parse("x = 1\n"), ast.Module)


def test_import_aliases() -> None:
    tree = module(
        """
        import os
        import os.path
        import unittest as ut
        from pytest import mark
        from pytest import mark as m2
        from . import sibling
        from .pkg import thing
        from typing import *

        def f():
            import json
        """
    )

    assert astutil.import_aliases(tree) == {
        "os": "os",
        "ut": "unittest",
        "mark": "pytest.mark",
        "m2": "pytest.mark",
        "json": "json",
    }


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        ("pytest.mark.skip", "pytest.mark.skip"),
        ("mark.skip(reason='x')", "pytest.mark.skip"),
        ("ut.skip", "unittest.skip"),
        ("self.skipTest('x')", "self.skipTest"),
        ("local", "local"),
        ("get()()", None),
        ("items[0].skip", None),
    ],
)
def test_resolved_name(expr: str, expected: str | None) -> None:
    aliases = {"mark": "pytest.mark", "ut": "unittest"}
    node = ast.parse(expr, mode="eval").body
    assert astutil.resolved_name(node, aliases) == expected


def test_definitions_qualified_names_and_last_definition_wins() -> None:
    tree = module(
        """
        def top():
            def inner():
                pass

        class Outer:
            class Inner:
                async def method(self):
                    pass

            def method(self):
                return 1

            def method(self):
                return 2
        """
    )

    defs = astutil.definitions(tree)

    assert sorted(defs) == [
        "Outer",
        "Outer.Inner",
        "Outer.Inner.method",
        "Outer.method",
        "top",
        "top.inner",
    ]
    assert ast.unparse(defs["Outer.method"]).endswith("return 2")
    assert sorted(astutil.classes(tree)) == ["Outer", "Outer.Inner"]
    assert "Outer" not in astutil.functions(tree)


@pytest.mark.parametrize(
    "source",
    [
        "def f():\n    pass\n",
        "def f():\n    ...\n",
        "def f():\n    return\n",
        "def f():\n    return None\n",
        "def f():\n    raise NotImplementedError\n",
        "def f():\n    raise NotImplementedError('later')\n",
        "def f():\n    '''Only a docstring.'''\n",
        "def f():\n    '''Doc.'''\n    # TODO\n    pass\n    ...\n",
    ],
)
def test_is_stub_body_true(source: str) -> None:
    assert astutil.is_stub_body(only_function(source))


@pytest.mark.parametrize(
    "source",
    [
        "def f():\n    return 0\n",
        "def f():\n    return x\n",
        "def f():\n    raise ValueError\n",
        "def f():\n    raise\n",
        "def f():\n    pass\n    return 1\n",
        "def f():\n    'not a docstring if not first'\n    x = 1\n",
        "def f():\n    print('...')\n",
        "def f():\n    42\n",
    ],
)
def test_is_stub_body_false(source: str) -> None:
    assert not astutil.is_stub_body(only_function(source))


def test_body_without_docstring_keeps_non_string_first_expression() -> None:
    node = only_function("def f():\n    42\n    return 1\n")
    assert len(astutil.body_without_docstring(node)) == 2


def test_walk_skipping_definitions_stays_in_the_given_body() -> None:
    tree = module(
        """
        a = call_one()

        def f():
            call_two()

        class C:
            call_three()

        if True:
            call_four()
        """
    )

    names = {
        node.func.id
        for node in astutil.walk_skipping_definitions(tree.body)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert names == {"call_one", "call_four"}


def test_comments_ignores_strings_and_reports_lines() -> None:
    source = 'x = "# not a comment"  # real\n# second\n'
    assert astutil.comments(source) == [(1, "# real"), (2, "# second")]


def test_comments_returns_none_when_source_does_not_tokenize() -> None:
    assert astutil.comments('x = """unterminated\n') is None
    assert astutil.comments("if x:\n        a = 1\n    b = 2\n") is None


def test_source_line_bounds() -> None:
    assert astutil.source_line("a\n  b  \n", 2) == "b"
    assert astutil.source_line("a\n", 0) == ""
    assert astutil.source_line("a\n", 5) == ""


def test_excess_sites_prefers_added_lines_and_counts_per_key() -> None:
    head = [("noqa", 1), ("noqa", 5), ("ignore", 7), ("noqa", 9)]
    # base had one noqa: one of the three head noqas is old; lines 5 and 9 were added
    assert astutil.excess_sites(["noqa"], head, frozenset({5, 9})) == [
        ("noqa", 5),
        ("ignore", 7),
        ("noqa", 9),
    ]


def test_excess_sites_falls_back_to_unchanged_lines() -> None:
    assert astutil.excess_sites([], [("k", 3)], frozenset()) == [("k", 3)]
    assert astutil.excess_sites(["k", "k"], [("k", 3)], frozenset({3})) == []


# ---------------------------------------------------------------- M2 helpers


def test_test_functions_only_module_level_and_class_methods() -> None:
    tree = module(
        """
        def test_top():
            def test_nested():
                pass

        class TestThing:
            def test_method(self):
                pass

            def helper(self):
                pass

            class TestInner:
                async def test_deep(self):
                    pass

        def helper():
            pass
        """
    )
    assert sorted(astutil.test_functions(tree)) == [
        "TestThing.TestInner.test_deep",
        "TestThing.test_method",
        "test_top",
    ]


def test_normalized_body_ignores_docstring_comments_and_formatting() -> None:
    first = only_function('def f():\n    """Doc."""\n    x = (1 +\n  2)  # c\n    return x\n')
    second = only_function("def g():\n    x = 1 + 2\n    return x\n")
    assert astutil.normalized_body(first) == astutil.normalized_body(second)


def test_fingerprint_ignores_position() -> None:
    first = module("def f():\n    return 1\n")
    second = module("\n\n\ndef f():\n        return 1\n")
    assert astutil.fingerprint(first) == astutil.fingerprint(second)


def test_called_names() -> None:
    expr = ast.parse("calc.add(sub(1), x)[0] + other()()", mode="eval").body
    assert astutil.called_names(expr) == {"add", "sub", "other"}


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("5", True),
        ("-5", True),
        ("+2.5", True),
        ("'s'", True),
        ("None", True),
        ("(1, -2, 'x')", True),
        ("[1, [2]]", True),
        ("{1, 2}", True),
        ("{'a': 1}", True),
        ("{**base}", False),
        ("-x", False),
        ("not 1", False),
        ("-'s'", False),
        ("-True", False),
        ("[1, x]", False),
        ("f()", False),
    ],
)
def test_is_literal(source: str, expected: bool) -> None:
    assert astutil.is_literal(ast.parse(source, mode="eval").body) is expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("7", "int:7"),
        ("-7", "int:-7"),
        ("+7", "int:7"),
        ("1.0", "float:1.0"),
        ("True", "bool:True"),
        ("'a'", "str:'a'"),
        ("None", "NoneType:None"),
        ("...", None),
        ("x", None),
        ("(1,)", None),
    ],
)
def test_literal_key(source: str, expected: str | None) -> None:
    assert astutil.literal_key(ast.parse(source, mode="eval").body) == expected


def test_literal_keys_counts_signed_numbers_once() -> None:
    node = ast.parse("f(-3, 'a') == [4, -3.5]", mode="eval").body
    assert astutil.literal_keys(node) == {"int:-3", "str:'a'", "int:4", "float:-3.5"}


def strengths(source: str) -> list[tuple[str, int]]:
    fn = only_function(textwrap.dedent(source))
    aliases = {"pytest": "pytest", "raises": "pytest.raises"}
    return [(str(a.strength), a.line) for a in astutil.assertions(fn.body, aliases)]


def test_assert_statement_strengths() -> None:
    assert strengths(
        """\
        def test():
            assert x == 1
            assert x is not None
            assert None != x
            assert x
            assert not x
            assert obj.attr
            assert isinstance(x, int)
            assert True
            assert 1 == 1
            assert False
            assert x and y
            assert check(x)
            assert x is None
            assert math.isclose(x, 1.0)
        """
    ) == [
        ("strong", 2),
        ("weak", 3),
        ("weak", 4),
        ("weak", 5),
        ("weak", 6),
        ("weak", 7),
        ("weak", 8),
        ("trivial", 9),
        ("trivial", 10),
        ("neutral", 11),
        ("neutral", 12),
        ("weak", 13),
        ("strong", 14),
        ("strong", 15),
    ]


def test_unittest_and_pytest_call_strengths() -> None:
    assert strengths(
        """\
        def test(self):
            self.assertEqual(f(), 1)
            self.assertTrue(f())
            self.assertTrue(True)
            self.assertFalse(0)
            self.assertFalse(1)
            self.assertIsNotNone(f())
            self.assertIsNone(f())
            self.assertRaises(ValueError, f)
            self.assertRaises(Exception, f)
            self.assertEqual(1, 1)
            self.assertLogs()
            client.assert_called_once()
            pytest.raises(ValueError)
            raises(Exception, match="x")
            pytest.raises(expected_exception=builtins.BaseException)
            pytest.raises()
            self.assertIn(f())
            other.method()
        """
    ) == [
        ("strong", 2),
        ("weak", 3),
        ("trivial", 4),
        ("trivial", 5),
        ("weak", 6),
        ("weak", 7),
        ("strong", 8),
        ("strong", 9),
        ("weak", 10),
        ("trivial", 11),
        ("neutral", 12),
        ("neutral", 13),
        ("strong", 14),
        ("strong", 15),
        ("weak", 16),
        ("neutral", 17),
        ("strong", 18),
    ]


def test_assertions_record_actual_and_expected_sides() -> None:
    fn = only_function(
        "def test(self):\n"
        "    assert add(2, 3) == 5\n"
        "    assert 5 == add(2, 3)\n"
        "    self.assertEqual(slug('a'), 'a')\n"
        "    assert a == b\n"
        "    assert 1 < x < 3\n"
    )
    found = astutil.assertions(fn.body, {})
    sides = [
        (a.form, a.actual and ast.unparse(a.actual), a.expected and ast.unparse(a.expected))
        for a in found
    ]
    assert sides == [
        ("Eq", "add(2, 3)", "5"),
        ("Eq", "add(2, 3)", "5"),
        ("assertEqual", "slug('a')", "'a'"),
        ("Eq", None, None),
        ("", None, None),
    ]


def test_assertion_literal_sets_cover_asserts_and_assert_calls() -> None:
    tree = module(
        """
        def test_a(self):
            assert fib(7) == 13
            self.assertEqual(price(37), 112.5)
            assert ok
            print(99)
        """
    )
    assert astutil.assertion_literal_sets(tree) == {
        frozenset({"int:7", "int:13"}),
        frozenset({"int:37", "float:112.5"}),
    }


def test_approx_calls_read_numeric_tolerances_and_defaults() -> None:
    fn = only_function(
        "def test():\n"
        "    assert a == pytest.approx(1.5)\n"
        "    assert b == pytest.approx(2, rel=0.1, abs=-0.0)\n"
        "    assert c == pytest.approx(3, rel=TOL)\n"
        "    assert d == pytest.approx()\n"
        "    assert e == approx(4, abs=1)\n"
    )
    calls = astutil.approx_calls(fn.body, {"pytest": "pytest", "approx": "pytest.approx"})
    assert calls == [
        astutil.Approx("1.5", 2, astutil.APPROX_DEFAULT_REL, astutil.APPROX_DEFAULT_ABS),
        astutil.Approx("2", 3, 0.1, -0.0),
        astutil.Approx("4", 6, astutil.APPROX_DEFAULT_REL, 1.0),
    ]


def test_branch_conditions_and_special_cases() -> None:
    fn = only_function(
        """\
        def f(self, n, *, mode, cls=None):
            if n == 7:
                return 13
            if 9 == n:
                return -1
            if n in [4, 5]:
                return "x"
            if mode == "fast":
                return compute()
            if self == 3:
                return 4
            if n == other:
                return 1
            if n in (x, 2):
                return 1
            if n in ():
                return 1
            if n > 3:
                return 1
            if n == 8:
                log()
            return 21 if n == 20 else 0
        """
    )
    cases = [
        (c.line, c.parameter, sorted(c.compared), c.returned) for c in astutil.special_cases(fn)
    ]
    assert cases == [
        (2, "n", ["int:7"], "int:13"),
        (4, "n", ["int:9"], "int:-1"),
        (6, "n", ["int:4", "int:5"], "str:'x'"),
        (22, "n", ["int:20"], "int:21"),
    ]
    assert astutil.branch_conditions(fn)["n == 7"] == 1
    assert sum(astutil.branch_conditions(fn).values()) == 11
