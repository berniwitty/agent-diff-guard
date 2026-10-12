"""R2 implementation hollowing: ADG010 stub-body."""

from __future__ import annotations

import ast

from agent_diff_guard.astutil import (
    FunctionNode,
    body_without_docstring,
    functions,
    import_aliases,
    is_stub_body,
    parse,
    resolved_name,
)
from agent_diff_guard.change import ChangedFile
from agent_diff_guard.classify import is_python_file
from agent_diff_guard.rules.base import Finding, RunContext, Severity, registry

# Decorators that make a placeholder body the intended definition.
_STUB_DECORATORS = frozenset({"abstractmethod", "abstractproperty", "overload"})
_EVIDENCE_WIDTH = 80


class StubBodyRule:
    id = "ADG010"
    name = "stub-body"
    default_severity = Severity.ERROR

    def check(self, change: ChangedFile, ctx: RunContext) -> list[Finding]:
        if not is_python_file(change.path) or ctx.is_test_file(change.path):
            return []
        base, head = parse(change.base_src), parse(change.head_src)
        if base is None or head is None:
            return []
        aliases = import_aliases(head)
        base_functions = functions(base)
        findings = []
        for qualname, node in functions(head).items():
            before = base_functions.get(qualname)
            if before is None or is_stub_body(before) or not is_stub_body(node):
                continue
            if _declared_as_stub(node, aliases):
                continue
            findings.append(
                Finding(
                    rule_id=self.id,
                    severity=self.default_severity,
                    path=change.path,
                    line=node.lineno,
                    message=f"Function `{qualname}` had real logic and now has a stub body.",
                    evidence=f"{_summary(before)} -> {_summary(node)}",
                )
            )
        return findings


def _declared_as_stub(node: FunctionNode, aliases: dict[str, str]) -> bool:
    for decorator in node.decorator_list:
        name = resolved_name(decorator, aliases)
        if name is not None and name.rsplit(".", 1)[-1] in _STUB_DECORATORS:
            return True
    return False


def _summary(node: FunctionNode) -> str:
    body = body_without_docstring(node)
    if not body:
        return "(docstring only)"
    text = "; ".join(" ".join(ast.unparse(stmt).split()) for stmt in body)
    return text if len(text) <= _EVIDENCE_WIDTH else text[: _EVIDENCE_WIDTH - 3] + "..."


registry.register(StubBodyRule())
