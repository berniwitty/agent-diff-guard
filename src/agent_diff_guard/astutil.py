"""AST helpers shared by rules."""

from __future__ import annotations

import ast
import io
import tokenize
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence

FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef
DefinitionNode = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef

# A site is (key, line): something of kind ``key`` found at ``line``.
Site = tuple[str, int]


def parse(source: str | None) -> ast.Module | None:
    """Parse ``source``; ``None`` if it is absent or not valid Python.

    Rules cannot reason about code that does not parse, so they treat it as absent.
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
