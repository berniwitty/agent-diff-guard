"""R2 implementation hollowing: ADG010 stub-body, ADG011 hardcoded-test-value,
ADG012 exception-swallowed."""

from __future__ import annotations

import ast
from collections import Counter

from agent_diff_guard.astutil import (
    FunctionNode,
    body_without_docstring,
    branch_conditions,
    excess_sites,
    functions,
    import_aliases,
    is_stub_body,
    parse,
    resolved_name,
    source_line,
    special_cases,
    swallowing_handlers,
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


# Literals too common to identify a specific test input.
TRIVIAL_LITERALS = frozenset(
    {
        "NoneType:None",
        "bool:True",
        "bool:False",
        "int:-1",
        "int:0",
        "int:1",
        "int:2",
        "float:0.0",
        "float:1.0",
        "str:''",
        "bytes:b''",
    }
)


class HardcodedTestValueRule:
    id = "ADG011"
    name = "hardcoded-test-value"
    default_severity = Severity.ERROR

    def check(self, change: ChangedFile, ctx: RunContext) -> list[Finding]:
        if not ctx.is_python_source(change.path) or not ctx.assertion_literals:
            return []
        head = parse(change.head_src)
        base = parse(change.base_src)
        if head is None or change.head_src is None or (change.base_src and base is None):
            return []
        base_functions = functions(base) if base is not None else {}
        findings = []
        for qualname, node in functions(head).items():
            before = base_functions.get(qualname)
            existing = branch_conditions(before) if before is not None else Counter[str]()
            for case in special_cases(node):
                if existing[case.condition] > 0:
                    existing[case.condition] -= 1
                    continue
                inputs = [
                    literal
                    for literal in sorted(case.compared - TRIVIAL_LITERALS)
                    if any({literal, case.returned} <= seen for seen in ctx.assertion_literals)
                ]
                if not inputs:
                    continue
                findings.append(
                    Finding(
                        rule_id=self.id,
                        severity=self.default_severity,
                        path=change.path,
                        line=case.line,
                        message=(
                            f"New branch in `{qualname}` returns `{_shown(case.returned)}` when "
                            f"`{case.parameter}` is `{_shown(inputs[0])}`, as a test asserts."
                        ),
                        evidence=source_line(change.head_src, case.line),
                    )
                )
        return findings


def _shown(literal_key: str) -> str:
    return literal_key.split(":", 1)[1]


class SwallowedExceptionRule:
    id = "ADG012"
    name = "exception-swallowed"
    default_severity = Severity.WARN

    def check(self, change: ChangedFile, ctx: RunContext) -> list[Finding]:
        if not is_python_file(change.path):
            return []
        head, base = parse(change.head_src), parse(change.base_src)
        if head is None or change.head_src is None or (change.base_src and base is None):
            return []
        after = swallowing_handlers(head, import_aliases(head))
        before = swallowing_handlers(base, import_aliases(base)) if base is not None else []
        clauses = {handler.line: handler.clause for handler in after}
        new = excess_sites(
            (handler.key for handler in before),
            [(handler.key, handler.line) for handler in after],
            change.added_lines,
        )
        return [
            Finding(
                rule_id=self.id,
                severity=self.default_severity,
                path=change.path,
                line=line,
                message=f"Added `{clauses[line]}` handler that silently discards the error.",
                evidence=source_line(change.head_src, line),
            )
            for _, line in new
        ]


registry.register(StubBodyRule())
registry.register(HardcodedTestValueRule())
registry.register(SwallowedExceptionRule())
