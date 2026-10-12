"""AST helpers shared by rules."""

from __future__ import annotations

import ast
import functools
import io
import tokenize
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from enum import StrEnum

FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef
DefinitionNode = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef

# A site is (key, line): something of kind ``key`` found at ``line``.
Site = tuple[str, int]


@functools.lru_cache(maxsize=64)
def parse(source: str | None) -> ast.Module | None:
    """Parse ``source``; ``None`` if it is absent or not valid Python.

    Rules cannot reason about code that does not parse, so they treat it as absent.
    Results are cached so every rule shares one tree per file: never mutate the tree.
    """
    if source is None:
        return None
    try:
        return ast.parse(source)
    except (SyntaxError, ValueError):
        return None


def import_aliases(module: ast.Module) -> dict[str, str]:
    """Map each name bound by an absolute import to the dotted path it refers to."""
    aliases: dict[str, str] = {}
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    aliases[alias.asname] = alias.name
                else:
                    top = alias.name.split(".")[0]
                    aliases[top] = top
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for alias in node.names:
                if alias.name != "*":
                    aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return aliases


def dotted_name(node: ast.expr) -> str | None:
    """``a.b.c`` for a Name/Attribute chain, else ``None``."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return ".".join(reversed(parts))


def resolved_name(node: ast.expr, aliases: dict[str, str]) -> str | None:
    """Dotted name of ``node`` (or of the callee, for a call) with imports resolved."""
    if isinstance(node, ast.Call):
        node = node.func
    name = dotted_name(node)
    if name is None:
        return None
    head, _, rest = name.partition(".")
    full = aliases.get(head, head)
    return f"{full}.{rest}" if rest else full


def definitions(module: ast.Module) -> dict[str, DefinitionNode]:
    """Functions and classes by qualified name (``Outer.method``); later definitions win."""
    found: dict[str, DefinitionNode] = {}

    def visit(body: Iterable[ast.stmt], prefix: str) -> None:
        for node in body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                qualname = f"{prefix}{node.name}"
                found[qualname] = node
                visit(node.body, f"{qualname}.")

    visit(module.body, "")
    return found


def functions(module: ast.Module) -> dict[str, FunctionNode]:
    return {
        name: node
        for name, node in definitions(module).items()
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def classes(module: ast.Module) -> dict[str, ast.ClassDef]:
    return {
        name: node for name, node in definitions(module).items() if isinstance(node, ast.ClassDef)
    }


def body_without_docstring(node: DefinitionNode) -> list[ast.stmt]:
    body = node.body
    first = body[0] if body else None
    if (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        return body[1:]
    return list(body)


def is_stub_body(node: FunctionNode) -> bool:
    """True if the body (after any docstring) is only placeholder statements."""
    return all(_is_stub_statement(stmt) for stmt in body_without_docstring(node))


def _is_stub_statement(stmt: ast.stmt) -> bool:
    if isinstance(stmt, ast.Pass):
        return True
    if isinstance(stmt, ast.Expr):
        return isinstance(stmt.value, ast.Constant) and stmt.value.value is Ellipsis
    if isinstance(stmt, ast.Return):
        return stmt.value is None or (
            isinstance(stmt.value, ast.Constant) and stmt.value.value is None
        )
    if isinstance(stmt, ast.Raise) and stmt.exc is not None:
        exc = stmt.exc.func if isinstance(stmt.exc, ast.Call) else stmt.exc
        return dotted_name(exc) in {"NotImplementedError", "builtins.NotImplementedError"}
    return False


def comments(source: str) -> list[tuple[int, str]] | None:
    """(line, text) of every comment token; ``None`` if ``source`` does not tokenize."""
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, SyntaxError):
        return None
    return [(tok.start[0], tok.string) for tok in tokens if tok.type == tokenize.COMMENT]


def walk_skipping_definitions(nodes: Iterable[ast.AST]) -> Iterator[ast.AST]:
    """Like ``ast.walk`` over ``nodes``, but never yielding or entering a function or class.

    Given a module or function body, this visits the code that runs as part of that body
    and not the code of definitions inside it.
    """
    stack = [node for node in nodes if not _is_definition(node)]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(child for child in ast.iter_child_nodes(node) if not _is_definition(child))


def _is_definition(node: ast.AST) -> bool:
    return isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)


def source_line(source: str, lineno: int) -> str:
    lines = source.splitlines()
    return lines[lineno - 1].strip() if 0 < lineno <= len(lines) else ""


def excess_sites(
    base_keys: Iterable[str], head_sites: Sequence[Site], added_lines: frozenset[int]
) -> list[Site]:
    """Head sites whose key occurs more often at head than at base.

    When a key's count grows by n, n of its head sites are returned, preferring sites on
    added lines, so moved or re-indented occurrences are not reported.
    """
    remaining = Counter(key for key, _ in head_sites) - Counter(base_keys)
    picked = []
    for key, line in sorted(head_sites, key=lambda site: (site[1] not in added_lines, site[1])):
        if remaining[key] > 0:
            remaining[key] -= 1
            picked.append((key, line))
    return sorted(picked, key=lambda site: site[1])


# ---------------------------------------------------------------------------- tests


def test_functions(module: ast.Module) -> dict[str, FunctionNode]:
    """``test*`` functions at module level or in classes (not nested in functions)."""
    defs = definitions(module)
    found: dict[str, FunctionNode] = {}
    for qualname, node in defs.items():
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if not node.name.startswith("test"):
            continue
        parents = qualname.split(".")[:-1]
        prefixes = (".".join(parents[: i + 1]) for i in range(len(parents)))
        if all(isinstance(defs.get(prefix), ast.ClassDef) for prefix in prefixes):
            found[qualname] = node
    return found


def normalized_body(node: FunctionNode) -> str:
    """The body's source without docstring, formatting or comments."""
    return "\n".join(ast.unparse(stmt) for stmt in body_without_docstring(node))


@dataclass(frozen=True)
class BodyShape:
    """What a test does: its normalised body and the literal values it checks."""

    body: str
    literals: frozenset[str]


def body_shape(node: FunctionNode) -> BodyShape:
    statements = body_without_docstring(node)
    literals = frozenset().union(*(literal_keys(stmt) for stmt in statements))
    return BodyShape(normalized_body(node), literals)


def fingerprint(node: ast.AST) -> str:
    """Structural identity of a node, ignoring positions, formatting and comments."""
    return ast.dump(node)


def called_names(expr: ast.expr) -> set[str]:
    """Simple names of everything called in ``expr`` (``mod.f(x)`` gives ``f``)."""
    names = set()
    for node in ast.walk(expr):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                names.add(node.func.attr)
    return names


# ---------------------------------------------------------------------------- literals


def is_literal(node: ast.expr) -> bool:
    """A constant, a signed number, or a tuple/list/set/dict made only of literals."""
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.UnaryOp):
        return _signed_number(node) is not None
    if isinstance(node, ast.Tuple | ast.List | ast.Set):
        return all(is_literal(element) for element in node.elts)
    if isinstance(node, ast.Dict):
        return all(key is not None and is_literal(key) for key in node.keys) and all(
            is_literal(value) for value in node.values
        )
    return False


def literal_key(node: ast.expr) -> str | None:
    """Type-qualified key for a scalar literal (``int:7``): ``1``, ``1.0``, ``True`` differ."""
    if isinstance(node, ast.Constant) and node.value is not Ellipsis:
        value: object = node.value
    elif isinstance(node, ast.UnaryOp) and (signed := _signed_number(node)) is not None:
        value = signed
    else:
        return None
    return f"{type(value).__name__}:{value!r}"


def literal_keys(node: ast.AST) -> frozenset[str]:
    """Keys of every scalar literal inside ``node``; ``-3`` counts once, as ``int:-3``."""
    signed_operands = {
        id(sub.operand)
        for sub in ast.walk(node)
        if isinstance(sub, ast.UnaryOp) and _signed_number(sub) is not None
    }
    keys = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.expr) and id(sub) not in signed_operands:
            key = literal_key(sub)
            if key is not None:
                keys.add(key)
    return frozenset(keys)


def _signed_number(node: ast.UnaryOp) -> int | float | complex | None:
    operand = node.operand
    if not isinstance(node.op, ast.USub | ast.UAdd) or not isinstance(operand, ast.Constant):
        return None
    value = operand.value
    if isinstance(value, bool) or not isinstance(value, int | float | complex):
        return None
    return -value if isinstance(node.op, ast.USub) else value


# ---------------------------------------------------------------------------- assertions


class Strength(StrEnum):
    STRONG = "strong"  # pins a value: ==, in, assertEqual, raises(SpecificError)
    WEAK = "weak"  # truthiness, `is not None`, isinstance, raises(Exception)
    TRIVIAL = "trivial"  # cannot fail: assert True, literal == literal
    NEUTRAL = "neutral"  # an assertion we do not grade: mock asserts, predicates


@dataclass(frozen=True)
class Assertion:
    strength: Strength
    line: int
    node: ast.AST
    form: str = ""
    actual: ast.expr | None = None
    expected: ast.expr | None = None


# Predicates that compare values, so `assert isclose(a, b)` is as exact as `assert a == b`.
_VALUE_PREDICATES = frozenset({"isclose", "allclose", "array_equal", "array_equiv"})
_BROAD_EXCEPTIONS = frozenset({"Exception", "BaseException"})
_UNITTEST_TWO_ARG = frozenset(
    {
        "assertEqual",
        "assertEquals",
        "assertNotEqual",
        "assertIn",
        "assertNotIn",
        "assertIs",
        "assertIsNot",
        "assertAlmostEqual",
        "assertNotAlmostEqual",
        "assertCountEqual",
        "assertDictEqual",
        "assertListEqual",
        "assertSetEqual",
        "assertTupleEqual",
        "assertSequenceEqual",
        "assertMultiLineEqual",
        "assertRegex",
        "assertNotRegex",
        "assertGreater",
        "assertGreaterEqual",
        "assertLess",
        "assertLessEqual",
    }
)
_UNITTEST_STRONG_OTHER = frozenset({"assertIsNone", "assertRaisesRegex", "assertWarnsRegex"})
_UNITTEST_WEAK = frozenset({"assertIsNotNone", "assertIsInstance", "assertNotIsInstance"})
_UNITTEST_RAISES = frozenset({"assertRaises", "assertWarns"})
_PYTEST_RAISES = frozenset({"pytest.raises", "pytest.warns"})


def assertions(body: Iterable[ast.stmt], aliases: dict[str, str]) -> list[Assertion]:
    """Assertions in ``body`` (not in nested definitions), in source order."""
    found = []
    for node in walk_skipping_definitions(body):
        if isinstance(node, ast.Assert):
            found.append(_assert_statement(node, aliases))
        elif isinstance(node, ast.Call):
            assertion = _assertion_call(node, aliases)
            if assertion is not None:
                found.append(assertion)
    return sorted(found, key=lambda a: (a.line, getattr(a.node, "col_offset", 0)))


def assertion_literal_sets(module: ast.Module) -> set[frozenset[str]]:
    """For each assertion anywhere in ``module``, the scalar literals it contains."""
    aliases = import_aliases(module)
    sets = set()
    for node in ast.walk(module):
        if isinstance(node, ast.Assert):
            keys = literal_keys(node.test)
        elif isinstance(node, ast.Call) and _assertion_call(node, aliases) is not None:
            keys = frozenset().union(*(literal_keys(arg) for arg in node.args))
        else:
            continue
        if keys:
            sets.add(keys)
    return sets


def _assert_statement(node: ast.Assert, aliases: dict[str, str]) -> Assertion:
    test = node.test
    actual, expected, form = _compare_sides(test)
    return Assertion(_expression_strength(test, aliases), node.lineno, node, form, actual, expected)


def _expression_strength(test: ast.expr, aliases: dict[str, str]) -> Strength:
    if isinstance(test, ast.Constant):
        return Strength.TRIVIAL if test.value else Strength.NEUTRAL
    if isinstance(test, ast.Compare):
        if is_literal(test.left) and all(is_literal(c) for c in test.comparators):
            return Strength.TRIVIAL
        if len(test.ops) == 1 and isinstance(test.ops[0], ast.IsNot | ast.NotEq):
            sides = (test.left, test.comparators[0])
            if any(isinstance(side, ast.Constant) and side.value is None for side in sides):
                return Strength.WEAK
        return Strength.STRONG
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        return _expression_strength(test.operand, aliases)
    if isinstance(test, ast.Name | ast.Attribute):
        return Strength.WEAK
    if isinstance(test, ast.Call):
        name = resolved_name(test, aliases) or ""
        if name.rsplit(".", 1)[-1] in _VALUE_PREDICATES:
            return Strength.STRONG
        # Truthiness of a call result: `assert parse(s)` passes for any non-empty answer.
        return Strength.WEAK
    return Strength.NEUTRAL


def _compare_sides(test: ast.expr) -> tuple[ast.expr | None, ast.expr | None, str]:
    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return None, None, ""
    return _split_actual_expected(test.left, test.comparators[0], type(test.ops[0]).__name__)


def _split_actual_expected(
    first: ast.expr, second: ast.expr, form: str
) -> tuple[ast.expr | None, ast.expr | None, str]:
    if is_literal(second) and not is_literal(first):
        return first, second, form
    if is_literal(first) and not is_literal(second):
        return second, first, form
    return None, None, form


def _assertion_call(node: ast.Call, aliases: dict[str, str]) -> Assertion | None:
    name = resolved_name(node, aliases)
    if name in _PYTEST_RAISES:
        return Assertion(_raises_strength(node, aliases), node.lineno, node, name)
    func = node.func
    if not isinstance(func, ast.Attribute) or not func.attr.startswith("assert"):
        return None
    if isinstance(func.value, ast.Name) and func.value.id == "self":
        return _unittest_assertion(node, func.attr, aliases)
    return Assertion(Strength.NEUTRAL, node.lineno, node, func.attr)


def _unittest_assertion(node: ast.Call, method: str, aliases: dict[str, str]) -> Assertion:
    args = node.args
    if method in ("assertTrue", "assertFalse"):
        constant = args[0] if args and isinstance(args[0], ast.Constant) else None
        if constant is not None and bool(constant.value) == (method == "assertTrue"):
            return Assertion(Strength.TRIVIAL, node.lineno, node, method)
        return Assertion(Strength.WEAK, node.lineno, node, method)
    if method in _UNITTEST_WEAK:
        return Assertion(Strength.WEAK, node.lineno, node, method)
    if method in _UNITTEST_RAISES:
        return Assertion(_raises_strength(node, aliases), node.lineno, node, method)
    if method in _UNITTEST_TWO_ARG:
        if len(args) >= 2 and is_literal(args[0]) and is_literal(args[1]):
            return Assertion(Strength.TRIVIAL, node.lineno, node, method)
        sides = _split_actual_expected(args[0], args[1], method) if len(args) >= 2 else None
        actual, expected, _ = sides if sides else (None, None, method)
        return Assertion(Strength.STRONG, node.lineno, node, method, actual, expected)
    if method in _UNITTEST_STRONG_OTHER:
        return Assertion(Strength.STRONG, node.lineno, node, method)
    return Assertion(Strength.NEUTRAL, node.lineno, node, method)


def _raises_strength(node: ast.Call, aliases: dict[str, str]) -> Strength:
    if any(keyword.arg == "match" for keyword in node.keywords):
        return Strength.STRONG
    expected = node.args[0] if node.args else None
    for keyword in node.keywords:
        if keyword.arg == "expected_exception":
            expected = keyword.value
    if expected is None:
        return Strength.NEUTRAL
    name = resolved_name(expected, aliases)
    if name is not None and name.rsplit(".", 1)[-1] in _BROAD_EXCEPTIONS:
        return Strength.WEAK
    return Strength.STRONG


@dataclass(frozen=True)
class Approx:
    expected: str
    line: int
    rel: float
    abs: float


APPROX_DEFAULT_REL = 1e-6
APPROX_DEFAULT_ABS = 1e-12


def approx_calls(body: Iterable[ast.stmt], aliases: dict[str, str]) -> list[Approx]:
    """``pytest.approx`` calls with numeric (or default) tolerances, in source order."""
    found = []
    for node in walk_skipping_definitions(body):
        if not isinstance(node, ast.Call) or resolved_name(node, aliases) != "pytest.approx":
            continue
        if not node.args:
            continue
        tolerance = {"rel": APPROX_DEFAULT_REL, "abs": APPROX_DEFAULT_ABS}
        numeric = True
        for keyword in node.keywords:
            if keyword.arg in tolerance:
                value = _number(keyword.value)
                if value is None:
                    numeric = False
                else:
                    tolerance[keyword.arg] = value
        if numeric:
            expected = ast.unparse(node.args[0])
            found.append(Approx(expected, node.lineno, tolerance["rel"], tolerance["abs"]))
    return sorted(found, key=lambda call: call.line)


def _number(node: ast.expr) -> float | None:
    if isinstance(node, ast.UnaryOp):
        signed = _signed_number(node)
        return float(signed) if isinstance(signed, int | float) else None
    value = node.value if isinstance(node, ast.Constant) else None
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return None


# ---------------------------------------------------------------------------- branches


@dataclass(frozen=True)
class SpecialCase:
    """``if <param> == <literal>: return <literal>`` and its conditional-expression form."""

    line: int
    condition: str
    parameter: str
    compared: frozenset[str]
    returned: str


def branch_conditions(node: FunctionNode) -> Counter[str]:
    """Source of every ``if`` and conditional-expression test in the function's own body."""
    return Counter(
        ast.unparse(sub.test)
        for sub in walk_skipping_definitions(node.body)
        if isinstance(sub, ast.If | ast.IfExp)
    )


def special_cases(node: FunctionNode) -> list[SpecialCase]:
    """Branches that compare a parameter to literals and return a literal."""
    arguments = node.args
    parameters = {
        arg.arg
        for arg in [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
        if arg.arg not in ("self", "cls")
    }
    found = []
    for sub in walk_skipping_definitions(node.body):
        if isinstance(sub, ast.If):
            first = sub.body[0]
            if isinstance(first, ast.Return) and first.value is not None:
                case = _special_case(sub.lineno, sub.test, first.value, parameters)
                if case is not None:
                    found.append(case)
        elif isinstance(sub, ast.IfExp):
            case = _special_case(sub.lineno, sub.test, sub.body, parameters)
            if case is not None:
                found.append(case)
    return sorted(found, key=lambda case: case.line)


def _special_case(
    line: int, test: ast.expr, result: ast.expr, parameters: set[str]
) -> SpecialCase | None:
    returned = literal_key(result)
    if returned is None or not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return None
    left, right, op = test.left, test.comparators[0], test.ops[0]
    if isinstance(op, ast.Eq):
        if isinstance(right, ast.Name) and not isinstance(left, ast.Name):
            left, right = right, left
        key = literal_key(right)
        if isinstance(left, ast.Name) and left.id in parameters and key is not None:
            return SpecialCase(line, ast.unparse(test), left.id, frozenset({key}), returned)
    if (
        isinstance(op, ast.In)
        and isinstance(left, ast.Name)
        and left.id in parameters
        and isinstance(right, ast.Tuple | ast.List | ast.Set)
        and right.elts
    ):
        keys = [literal_key(element) for element in right.elts]
        if all(key is not None for key in keys):
            compared = frozenset(key for key in keys if key is not None)
            return SpecialCase(line, ast.unparse(test), left.id, compared, returned)
    return None


# ---------------------------------------------------------------------------- handlers


@dataclass(frozen=True)
class SwallowingHandler:
    """A catch-all ``except`` whose body discards the error."""

    line: int
    clause: str  # "except:" or "except Exception:"
    key: str  # clause and body, to match the same handler between revisions


def swallowing_handlers(module: ast.Module, aliases: dict[str, str]) -> list[SwallowingHandler]:
    found = []
    for node in ast.walk(module):
        if not isinstance(node, ast.ExceptHandler) or not _catches_everything(node.type, aliases):
            continue
        if node.body and all(_discards(stmt) for stmt in node.body):
            clause = "except:" if node.type is None else f"except {ast.unparse(node.type)}:"
            body = "; ".join(ast.unparse(stmt) for stmt in node.body)
            found.append(SwallowingHandler(node.lineno, clause, f"{clause} {body}"))
    return sorted(found, key=lambda handler: handler.line)


def _catches_everything(kind: ast.expr | None, aliases: dict[str, str]) -> bool:
    if kind is None:
        return True
    candidates = kind.elts if isinstance(kind, ast.Tuple) else [kind]
    for candidate in candidates:
        name = resolved_name(candidate, aliases)
        if name is not None and name.rsplit(".", 1)[-1] in _BROAD_EXCEPTIONS:
            return True
    return False


def _discards(stmt: ast.stmt) -> bool:
    if isinstance(stmt, ast.Pass):
        return True
    if isinstance(stmt, ast.Expr):
        return isinstance(stmt.value, ast.Constant) and stmt.value.value is Ellipsis
    if isinstance(stmt, ast.Return):
        return stmt.value is None or isinstance(stmt.value, ast.Constant) or is_literal(stmt.value)
    return False


# ---------------------------------------------------------------------------- mocking


def from_imports(module: ast.Module) -> dict[str, str]:
    """Names bound by ``from <module> import <name> [as <local>]``: local -> original name."""
    names = {}
    for node in ast.walk(module):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for alias in node.names:
                if alias.name != "*":
                    names[alias.asname or alias.name] = alias.name
    return names


_PATCH_SUFFIXES = ("mock.patch", "mocker.patch")
_PATCH_OBJECT_SUFFIXES = ("patch.object",)


def patch_targets(node: FunctionNode, aliases: dict[str, str]) -> list[tuple[str, int]]:
    """(patched attribute name, line) for mock/monkeypatch patches in a test function."""
    calls = [d for d in node.decorator_list if isinstance(d, ast.Call)]
    calls += [sub for sub in walk_skipping_definitions(node.body) if isinstance(sub, ast.Call)]
    found = []
    for call in calls:
        name = resolved_name(call, aliases) or ""
        target = _patched_name(name, call.args)
        if target is not None:
            found.append((target, call.lineno))
    return sorted(found, key=lambda site: site[1])


def _patched_name(callee: str, args: list[ast.expr]) -> str | None:
    def string(index: int) -> str | None:
        arg = args[index] if len(args) > index else None
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
        return None

    if callee.endswith(_PATCH_OBJECT_SUFFIXES):
        return string(1)
    if callee == "patch" or callee.endswith(_PATCH_SUFFIXES):
        dotted = string(0)
        return dotted.rsplit(".", 1)[-1] if dotted else None
    if callee == "monkeypatch.setattr":
        dotted = string(0)
        if dotted is not None and "." in dotted and len(args) == 2:
            return dotted.rsplit(".", 1)[-1]
        return string(1)
    return None
