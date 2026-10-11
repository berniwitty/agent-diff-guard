"""R4 mocking: ADG030 mocked-subject."""

from __future__ import annotations

import ast

from agent_diff_guard.astutil import (
    FunctionNode,
    excess_sites,
    from_imports,
    import_aliases,
    parse,
    patch_targets,
    source_line,
    test_functions,
    walk_skipping_definitions,
)
from agent_diff_guard.change import ChangedFile
from agent_diff_guard.rules.base import Finding, RunContext, Severity, registry


class MockedSubjectRule:
    id = "ADG030"
    name = "mocked-subject"
    default_severity = Severity.WARN

    def check(self, change: ChangedFile, ctx: RunContext) -> list[Finding]:
        if not ctx.is_python_test(change.path):
            return []
        head, base = parse(change.head_src), parse(change.base_src)
        if head is None or change.head_src is None or (change.base_src and base is None):
            return []
        imported = from_imports(head)
        subjects_imported = set(imported) | set(imported.values())
        aliases = import_aliases(head)
        base_tests = test_functions(base) if base is not None else {}
        base_aliases = import_aliases(base) if base is not None else {}
        findings = []
        for qualname, test in test_functions(head).items():
            before = base_tests.get(qualname)
            old = patch_targets(before, base_aliases) if before is not None else []
            new = excess_sites(
                (name for name, _ in old), patch_targets(test, aliases), change.added_lines
            )
            for name, line in new:
                if name in subjects_imported and _is_subject(name, test):
                    findings.append(
                        Finding(
                            rule_id=self.id,
                            severity=self.default_severity,
                            path=change.path,
                            line=line,
                            message=f"Test `{qualname}` patches `{name}`, the function it tests.",
                            evidence=source_line(change.head_src, line),
                        )
                    )
        return findings


def _is_subject(name: str, test: FunctionNode) -> bool:
    """The test is named after ``name`` or calls it directly (``name(...)``)."""
    if name in test.name:
        return True
    return any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name
        for node in walk_skipping_definitions(test.body)
    )


registry.register(MockedSubjectRule())
