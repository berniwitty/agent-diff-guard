"""R1 test tampering: ADG002 test-skipped."""

from __future__ import annotations

import ast
from collections.abc import Iterator

from agent_diff_guard.astutil import (
    FunctionNode,
    Site,
    body_without_docstring,
    definitions,
    excess_sites,
    import_aliases,
    parse,
    resolved_name,
    source_line,
    walk_skipping_definitions,
)
from agent_diff_guard.change import ChangedFile
from agent_diff_guard.classify import is_python_file
from agent_diff_guard.rules.base import Finding, RunContext, Severity, registry

SKIP_MARKERS = frozenset(
    {
        "pytest.mark.skip",
        "pytest.mark.skipif",
        "pytest.mark.xfail",
        "unittest.skip",
        "unittest.skipIf",
        "unittest.skipUnless",
        "unittest.expectedFailure",
    }
)
SKIP_CALLS = frozenset({"pytest.skip", "pytest.xfail", "self.skipTest"})
SKIP_EXCEPTIONS = frozenset({"unittest.SkipTest", "unittest.case.SkipTest"})
_EARLY_RETURN = "early-return"


class SkippedTestRule:
    id = "ADG002"
    name = "test-skipped"
    default_severity = Severity.ERROR

    def check(self, change: ChangedFile, ctx: RunContext) -> list[Finding]:
        if not is_python_file(change.path) or not ctx.is_test_file(change.path):
            return []
        base, head = parse(change.base_src), parse(change.head_src)
        if base is None or head is None or change.head_src is None:
            return []
        return [
            Finding(
                rule_id=self.id,
                severity=self.default_severity,
                path=change.path,
                line=line,
                message=message,
                evidence=source_line(change.head_src, line),
            )
            for line, message in _new_skips(base, head, change.added_lines)
        ]


def _new_skips(
    base: ast.Module, head: ast.Module, added: frozenset[int]
) -> Iterator[tuple[int, str]]:
    base_aliases, head_aliases = import_aliases(base), import_aliases(head)

    for key, line in _excess(
        _module_sites(base, base_aliases), _module_sites(head, head_aliases), added
    ):
        yield line, f"Test module gained a module-level `{key}`."

    base_defs = definitions(base)
    for qualname, node in definitions(head).items():
        before = base_defs.get(qualname)
        if isinstance(node, ast.ClassDef) and isinstance(before, ast.ClassDef):
            for key, line in _excess(
                _decorator_sites(before, base_aliases), _decorator_sites(node, head_aliases), added
            ):
                yield line, f"Test class `{qualname}` gained a `{key}` marker."
        elif (
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and isinstance(before, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.name.startswith("test")
        ):
            for key, line in _excess(
                _function_sites(before, base_aliases), _function_sites(node, head_aliases), added
            ):
                yield line, _function_message(qualname, key)


def _function_message(qualname: str, key: str) -> str:
    if key == _EARLY_RETURN:
        return f"Test `{qualname}` now returns before running its checks."
    if key in SKIP_CALLS:
        return f"Test `{qualname}` now calls `{key}`."
    if key in SKIP_EXCEPTIONS:
        return f"Test `{qualname}` now raises `{key}`."
    return f"Test `{qualname}` gained a `{key}` marker."


def _excess(base_sites: list[Site], head_sites: list[Site], added: frozenset[int]) -> list[Site]:
    return excess_sites((key for key, _ in base_sites), head_sites, added)


def _decorator_sites(node: ast.ClassDef | FunctionNode, aliases: dict[str, str]) -> list[Site]:
    return [
        (name, decorator.lineno)
        for decorator in node.decorator_list
        if (name := resolved_name(decorator, aliases)) in SKIP_MARKERS
    ]


def _function_sites(node: FunctionNode, aliases: dict[str, str]) -> list[Site]:
    sites = _decorator_sites(node, aliases) + _skip_statement_sites(node.body, aliases)
    body = body_without_docstring(node)
    if body and isinstance(body[0], ast.Return):
        sites.append((_EARLY_RETURN, body[0].lineno))
    return sites


def _skip_statement_sites(body: list[ast.stmt], aliases: dict[str, str]) -> list[Site]:
    sites = []
    for sub in walk_skipping_definitions(body):
        if isinstance(sub, ast.Call):
            name = resolved_name(sub, aliases)
            if name in SKIP_CALLS:
                sites.append((name, sub.lineno))
        elif isinstance(sub, ast.Raise) and sub.exc is not None:
            name = resolved_name(sub.exc, aliases)
            if name in SKIP_EXCEPTIONS:
                sites.append((name, sub.lineno))
    return sites


def _module_sites(module: ast.Module, aliases: dict[str, str]) -> list[Site]:
    sites = _skip_statement_sites(module.body, aliases)
    for node in walk_skipping_definitions(module.body):
        if _assigns_pytestmark(node):
            assert isinstance(node, ast.Assign | ast.AnnAssign) and node.value is not None
            sites.extend(_marker_sites(node.value, aliases))
    return sites


def _assigns_pytestmark(node: ast.AST) -> bool:
    if isinstance(node, ast.Assign):
        targets = node.targets
    elif isinstance(node, ast.AnnAssign) and node.value is not None:
        targets = [node.target]
    else:
        return False
    return any(isinstance(target, ast.Name) and target.id == "pytestmark" for target in targets)


def _marker_sites(expr: ast.expr, aliases: dict[str, str]) -> list[Site]:
    """Skip markers in a ``pytestmark`` value, called (``skip(...)``) or bare (``skip``)."""
    callees = {id(node.func) for node in ast.walk(expr) if isinstance(node, ast.Call)}
    return [
        (name, node.lineno)
        for node in ast.walk(expr)
        if isinstance(node, ast.Call | ast.Attribute | ast.Name)
        and id(node) not in callees
        and (name := resolved_name(node, aliases)) in SKIP_MARKERS
    ]


registry.register(SkippedTestRule())
