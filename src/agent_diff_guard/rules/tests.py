"""R1 test tampering: ADG001 test-removed, ADG002 test-skipped, ADG003 assertion-weakened,
ADG004 expected-value-edited."""

from __future__ import annotations

import ast
import difflib
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass

from agent_diff_guard.astutil import (
    Assertion,
    FunctionNode,
    Site,
    Strength,
    approx_calls,
    assertions,
    body_shape,
    body_without_docstring,
    called_names,
    classes,
    excess_sites,
    import_aliases,
    parse,
    resolved_name,
    source_line,
    test_functions,
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

    base_classes = classes(base)
    for qualname, node in classes(head).items():
        before_class = base_classes.get(qualname)
        if before_class is None:
            continue
        for key, line in _excess(
            _decorator_sites(before_class, base_aliases),
            _decorator_sites(node, head_aliases),
            added,
        ):
            yield line, f"Test class `{qualname}` gained a `{key}` marker."

    base_tests = test_functions(base)
    for qualname, test in test_functions(head).items():
        before = base_tests.get(qualname)
        if before is None:
            continue
        for key, line in _excess(
            _function_sites(before, base_aliases), _function_sites(test, head_aliases), added
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


# ---------------------------------------------------------------------------- ADG001

# Bodies at least this similar count as the same test (renamed or moved)...
SIMILARITY = 0.8
# ...if they also share at least this much of their literal values.
SAME_VALUES = 0.5


class RemovedTestRule:
    id = "ADG001"
    name = "test-removed"
    default_severity = Severity.ERROR

    def check(self, change: ChangedFile, ctx: RunContext) -> list[Finding]:
        if not ctx.is_python_test(change.path) or change.base_src is None:
            return []
        base = parse(change.base_src)
        if base is None:
            return []
        before = test_functions(base)
        if change.head_src is None:
            missing = [name for name, node in before.items() if not _moved(node, ctx)]
            if not missing:
                return []
            return [
                self._finding(
                    change.path,
                    f"Deleted test file removed {len(missing)} test(s).",
                    ", ".join(missing),
                )
            ]
        head = parse(change.head_src)
        if head is None:
            return []
        after = test_functions(head)
        return [
            self._finding(
                change.path,
                f"Test `{name}` was removed.",
                f"{source_line(change.base_src, node.lineno)}  (base line {node.lineno})",
            )
            for name, node in before.items()
            if name not in after and not _moved(node, ctx)
        ]

    def _finding(self, path: str, message: str, evidence: str) -> Finding:
        return Finding(self.id, self.default_severity, path, None, message, evidence)


def _moved(node: FunctionNode, ctx: RunContext) -> bool:
    """A test new elsewhere in the diff does the same thing: a rename or a move.

    The body must be similar *and* check mostly the same values, so deleting a test
    while adding a similar-looking test of other values is still a removal.
    """
    shape = body_shape(node)
    return any(
        _similar(shape.body, other.body) and _overlap(shape.literals, other.literals) >= SAME_VALUES
        for other in ctx.new_test_shapes
    )


def _overlap(first: frozenset[str], second: frozenset[str]) -> float:
    """Jaccard overlap of two literal sets; two tests without literals overlap fully."""
    if not first and not second:
        return 1.0
    return len(first & second) / len(first | second)


def _similar(first: str, second: str) -> bool:
    if first == second:
        return True
    matcher = difflib.SequenceMatcher(None, first, second, autojunk=False)
    return (
        matcher.real_quick_ratio() >= SIMILARITY
        and matcher.quick_ratio() >= SIMILARITY
        and matcher.ratio() >= SIMILARITY
    )


# ---------------------------------------------------------------- shared by ADG003/004


@dataclass(frozen=True)
class _TestPair:
    qualname: str
    before: FunctionNode
    after: FunctionNode
    base_aliases: dict[str, str]
    head_aliases: dict[str, str]


def _test_pairs(change: ChangedFile, ctx: RunContext) -> list[_TestPair]:
    """Test functions present, under the same qualified name, at base and head."""
    if not ctx.is_python_test(change.path):
        return []
    base, head = parse(change.base_src), parse(change.head_src)
    if base is None or head is None:
        return []
    before = test_functions(base)
    base_aliases, head_aliases = import_aliases(base), import_aliases(head)
    return [
        _TestPair(qualname, before[qualname], node, base_aliases, head_aliases)
        for qualname, node in test_functions(head).items()
        if qualname in before
    ]


# ---------------------------------------------------------------------------- ADG003


class WeakenedAssertionRule:
    id = "ADG003"
    name = "assertion-weakened"
    default_severity = Severity.ERROR

    def check(self, change: ChangedFile, ctx: RunContext) -> list[Finding]:
        findings = []
        for pair in _test_pairs(change, ctx):
            assert change.head_src is not None
            for line, message, evidence in _weakenings(pair, change.added_lines):
                findings.append(
                    Finding(
                        rule_id=self.id,
                        severity=self.default_severity,
                        path=change.path,
                        line=line,
                        message=message,
                        evidence=evidence or source_line(change.head_src, line),
                    )
                )
        return findings


def _weakenings(pair: _TestPair, added: frozenset[int]) -> Iterator[tuple[int, str, str]]:
    """(line, message, evidence or "") for each way the test got weaker."""
    name = pair.qualname
    before = assertions(pair.before.body, pair.base_aliases)
    after = assertions(pair.after.body, pair.head_aliases)

    if len(after) < len(before) and not _gained_parametrize(pair):
        removed = Counter(ast.unparse(a.node) for a in before) - Counter(
            ast.unparse(a.node) for a in after
        )
        yield (
            pair.after.lineno,
            f"Test `{name}` has fewer assertions than before ({len(before)} -> {len(after)}).",
            " | ".join(list(removed.elements())[:3]),
        )

    strong_lost = _count(before, Strength.STRONG) - _count(after, Strength.STRONG)
    if strong_lost > 0:
        for line in _new_lines(before, after, Strength.WEAK, added)[:strong_lost]:
            yield line, f"Test `{name}` replaced an exact assertion with a weaker check.", ""

    for line in _new_lines(before, after, Strength.TRIVIAL, added):
        yield line, f"Test `{name}` gained an assertion that always passes.", ""

    base_approx = {
        call.expected: call for call in approx_calls(pair.before.body, pair.base_aliases)
    }
    for call in approx_calls(pair.after.body, pair.head_aliases):
        old = base_approx.get(call.expected)
        if old is None:
            continue
        widened = [
            f"{label} {old_value:g} -> {new_value:g}"
            for label, old_value, new_value in (
                ("rel", old.rel, call.rel),
                ("abs", old.abs, call.abs),
            )
            if new_value > old_value
        ]
        if widened:
            yield (
                call.line,
                f"Test `{name}` widened a `pytest.approx` tolerance ({', '.join(widened)}).",
                "",
            )


def _count(found: list[Assertion], strength: Strength) -> int:
    return sum(1 for assertion in found if assertion.strength is strength)


def _new_lines(
    before: list[Assertion], after: list[Assertion], strength: Strength, added: frozenset[int]
) -> list[int]:
    base_keys = [str(strength)] * _count(before, strength)
    head_sites = [(str(strength), a.line) for a in after if a.strength is strength]
    return [line for _, line in excess_sites(base_keys, head_sites, added)]


def _gained_parametrize(pair: _TestPair) -> bool:
    def count(node: FunctionNode, aliases: dict[str, str]) -> int:
        return sum(
            1
            for decorator in node.decorator_list
            if resolved_name(decorator, aliases) == "pytest.mark.parametrize"
        )

    return count(pair.after, pair.head_aliases) > count(pair.before, pair.base_aliases)


# ---------------------------------------------------------------------------- ADG004


class ExpectedValueEditedRule:
    id = "ADG004"
    name = "expected-value-edited"
    default_severity = Severity.WARN

    def check(self, change: ChangedFile, ctx: RunContext) -> list[Finding]:
        if not ctx.changed_function_names:
            return []
        findings = []
        for pair in _test_pairs(change, ctx):
            assert change.head_src is not None
            for line, old, new, function in _edited_expectations(pair, ctx):
                findings.append(
                    Finding(
                        rule_id=self.id,
                        severity=self.default_severity,
                        path=change.path,
                        line=line,
                        message=(
                            f"Expected value changed from `{old}` to `{new}` "
                            f"while `{function}` was modified."
                        ),
                        evidence=source_line(change.head_src, line),
                    )
                )
        return findings


def _edited_expectations(pair: _TestPair, ctx: RunContext) -> Iterator[tuple[int, str, str, str]]:
    def comparisons(
        node: FunctionNode, aliases: dict[str, str]
    ) -> list[tuple[Assertion, str, str]]:
        return [
            (a, f"{a.form}:{ast.unparse(a.actual)}", ast.unparse(a.expected))
            for a in assertions(node.body, aliases)
            if a.actual is not None and a.expected is not None
        ]

    before = comparisons(pair.before, pair.base_aliases)
    unchanged = Counter((key, expected) for _, key, expected in before)
    for assertion, key, expected in comparisons(pair.after, pair.head_aliases):
        if unchanged[(key, expected)] > 0:
            unchanged[(key, expected)] -= 1
            continue
        old = [old for _, old_key, old in before if old_key == key and old != expected]
        assert assertion.actual is not None
        linked = sorted(called_names(assertion.actual) & ctx.changed_function_names)
        if old and linked:
            yield assertion.line, old[0], expected, linked[0]


registry.register(RemovedTestRule())
registry.register(SkippedTestRule())
registry.register(WeakenedAssertionRule())
registry.register(ExpectedValueEditedRule())
