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
