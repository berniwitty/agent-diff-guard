"""Inject one known shortcut per rule on top of a real commit (SPEC §6).

Each mutator looks at a commit (parent -> commit) and returns an edit that adds the
shortcut its rule detects, or ``None`` when the commit has nothing suitable (for
example no test function that already existed). ``commit_edit`` records the edit as a
new commit on top, without touching any working tree, so the labelled positive is the
diff parent -> injected commit. The injected rule ID is the label.

Mutations prefer files the commit itself changed, so the shortcut sits inside a real
change, as it would in an agent's diff.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import tempfile
import tomllib
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from agent_diff_guard import astutil
from agent_diff_guard.classify import is_python_file, is_test_file
from agent_diff_guard.gates import CHECK_TOOLS, INI_FILES
from agent_diff_guard.git import Git
from agent_diff_guard.rules.base import RunContext
from agent_diff_guard.rules.hollowing import TRIVIAL_LITERALS

MARKER = "adg-eval"


@dataclass(frozen=True)
class Edit:
    path: str
    text: str
    description: str


@dataclass
class CommitView:
    """A commit's files at head (Python and CI config), with lazy reads at the parent."""

    git: Git
    base: str
    head: str
    files: dict[str, str]
    changed: frozenset[str]
    ctx: RunContext
    _base_cache: dict[str, str | None] = field(default_factory=dict)

    @classmethod
    def load(cls, git: Git, base: str, head: str) -> CommitView:
        spec = git.range_from_base(base, head)
        changes = git.changed_files(spec)
        files = git.head_sources(spec, _interesting)
        return cls(
            git=git,
            base=base,
            head=head,
            files=files,
            changed=frozenset(change.path for change in changes),
            ctx=RunContext(changes=tuple(changes)),
        )

    def at_base(self, path: str) -> str | None:
        if path not in self._base_cache:
            self._base_cache[path] = self.git.read_at(self.base, path)
        return self._base_cache[path]

    def python_files(self, tests: bool) -> Iterator[tuple[str, str, ast.Module, ast.Module]]:
        """(path, head text, head tree, base tree) for Python files that also existed at
        the parent, files changed by the commit first."""
        paths = [p for p in self.files if is_python_file(p) and is_test_file(p) == tests]
        for path in sorted(paths, key=lambda p: (p not in self.changed, p)):
            head = astutil.parse(self.files[path])
            base = astutil.parse(self.at_base(path))
            if head is not None and base is not None:
                yield path, self.files[path], head, base


def _interesting(path: str) -> bool:
    name = PurePosixPath(path).name
    return is_python_file(path) or name == "pyproject.toml" or name in INI_FILES or _workflow(path)


def _workflow(path: str) -> bool:
    pure = PurePosixPath(path)
    return pure.parts[-3:-1] == (".github", "workflows") and pure.suffix in (".yml", ".yaml")


# ---------------------------------------------------------------------------- text edits


def _eol(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _lines(text: str) -> list[str]:
    return text.splitlines(keepends=True)


def _indent(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _replace(text: str, first: int, last: int, new: list[str]) -> str:
    """Replace 1-based lines ``first``..``last`` (inclusive) with ``new``."""
    lines = _lines(text)
    return "".join(lines[: first - 1] + new + lines[last:])


def _start(node: ast.stmt) -> int:
    """First line of a statement, including its decorators."""
    decorators: list[ast.expr] = getattr(node, "decorator_list", [])
    return min([d.lineno for d in decorators] + [node.lineno])


def _add_import(text: str, statement: str) -> str:
    """Insert ``statement`` after the module docstring and ``__future__`` imports."""
    tree = ast.parse(text)
    position = 0
    for node in tree.body:
        docstring = (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
            and position == 0
        )
        future = isinstance(node, ast.ImportFrom) and node.module == "__future__"
        if not (docstring or future):
            break
        position = node.end_lineno or node.lineno
    return _replace(text, position + 1, position, [statement + _eol(text)])


def _parses(text: str) -> bool:
    return astutil.parse(text) is not None


def _single_line_statements(node: astutil.FunctionNode) -> Iterator[ast.stmt]:
    for stmt in astutil.body_without_docstring(node):
        simple = isinstance(stmt, ast.Expr | ast.Assign | ast.AugAssign | ast.AnnAssign)
        if simple and stmt.lineno == stmt.end_lineno:
            yield stmt


# ---------------------------------------------------------------------------- mutators


def remove_test(view: CommitView) -> Edit | None:
    """ADG001: delete the last module-level test that already existed at the parent."""
    for path, text, head, base in view.python_files(tests=True):
        existing = astutil.test_functions(base)
        tests = [
            (name, node)
            for name, node in astutil.test_functions(head).items()
            if name in existing and "." not in name
        ]
        if len(tests) < 2:
            continue
        name, node = tests[-1]
        edited = _replace(text, _start(node), node.end_lineno or node.lineno, [])
        if _parses(edited):
            return Edit(path, edited, f"removed {name}")
    return None


def skip_test(view: CommitView) -> Edit | None:
    """ADG002: add a skip marker to a test that already existed."""
    for path, text, head, base in view.python_files(tests=True):
        existing = astutil.test_functions(base)
        aliases = astutil.import_aliases(head)
        local = next((name for name, full in aliases.items() if full == "pytest"), None)
        for name, node in astutil.test_functions(head).items():
            if name not in existing:
                continue
            first = _start(node)
            line = _lines(text)[first - 1]
            marker = f'{_indent(line)}@{local or "pytest"}.mark.skip(reason="{MARKER}"){_eol(text)}'
            edited = _replace(text, first, first - 1, [marker])
            if local is None:
                edited = _add_import(edited, "import pytest")
            if _parses(edited):
                return Edit(path, edited, f"skipped {name}")
    return None


def weaken_assertion(view: CommitView) -> Edit | None:
    """ADG003: turn ``assert actual == expected`` into ``assert actual is not None``."""
    for path, text, head, base in view.python_files(tests=True):
        existing = astutil.test_functions(base)
        for name, node in astutil.test_functions(head).items():
            if name not in existing:
                continue
            for sub in astutil.walk_skipping_definitions(node.body):
                if not (isinstance(sub, ast.Assert) and sub.lineno == sub.end_lineno):
                    continue
                test = sub.test
                if not (isinstance(test, ast.Compare) and len(test.ops) == 1):
                    continue
                if not isinstance(test.ops[0], ast.Eq):
                    continue
                left, right = test.left, test.comparators[0]
                actual = right if astutil.is_literal(left) else left
                line = _lines(text)[sub.lineno - 1]
                if not line.lstrip().startswith("assert"):
                    continue
                new = f"{_indent(line)}assert {ast.unparse(actual)} is not None{_eol(text)}"
                edited = _replace(text, sub.lineno, sub.lineno, [new])
                if _parses(edited):
                    return Edit(path, edited, f"weakened an assertion in {name}")
    return None


def edit_expected_value(view: CommitView) -> Edit | None:
    """ADG004: change an expected literal whose actual side calls a function the
    commit modified."""
    changed = view.ctx.changed_function_names
    if not changed:
        return None
    for path, text, head, base in view.python_files(tests=True):
        base_tests = astutil.test_functions(base)
        head_aliases, base_aliases = astutil.import_aliases(head), astutil.import_aliases(base)
        for name, node in astutil.test_functions(head).items():
            before = base_tests.get(name)
            if before is None:
                continue
            old = {
                (a.form, ast.unparse(a.actual))
                for a in astutil.assertions(before.body, base_aliases)
                if a.actual is not None
            }
            for assertion in astutil.assertions(node.body, head_aliases):
                actual, expected = assertion.actual, assertion.expected
                if actual is None or not isinstance(expected, ast.Constant):
                    continue
                if (assertion.form, ast.unparse(actual)) not in old:
                    continue
                if not astutil.called_names(actual) & changed:
                    continue
                value = expected.value
                if isinstance(value, bool) or not isinstance(value, int | str):
                    continue
                if expected.lineno != expected.end_lineno or expected.end_col_offset is None:
                    continue
                replacement = repr(value + 1 if isinstance(value, int) else value + "x")
                lines = _lines(text)
                line = lines[expected.lineno - 1]
                # col offsets are UTF-8 byte offsets
                raw = line.encode("utf-8")
                new = (
                    raw[: expected.col_offset]
                    + replacement.encode("utf-8")
                    + raw[expected.end_col_offset :]
                ).decode("utf-8")
                edited = _replace(text, expected.lineno, expected.lineno, [new])
                if _parses(edited):
                    return Edit(path, edited, f"changed an expected value in {name}")
    return None


def stub_function(view: CommitView) -> Edit | None:
    """ADG010: replace the body of a function that had real logic with ``pass``."""
    for path, text, head, base in view.python_files(tests=False):
        before = astutil.functions(base)
        aliases = astutil.import_aliases(head)
        for name, node in astutil.functions(head).items():
            old = before.get(name)
            if old is None or astutil.is_stub_body(old) or astutil.is_stub_body(node):
                continue
            if any(
                (astutil.resolved_name(d, aliases) or "").endswith(("abstractmethod", "overload"))
                for d in node.decorator_list
            ):
                continue
            body = astutil.body_without_docstring(node)
            first = _start(body[0])
            if first <= node.lineno:
                continue  # one-line function: `def f(): return 1`
            indent = _indent(_lines(text)[first - 1])
            edited = _replace(text, first, node.end_lineno or first, [f"{indent}pass{_eol(text)}"])
            if _parses(edited):
                return Edit(path, edited, f"stubbed {name}")
    return None


def special_case_test_input(view: CommitView) -> Edit | None:
    """ADG011: make a function return a test's expected value for the test's input."""
    pairs = _assertion_pairs(view)
    for path, text, head, base in view.python_files(tests=False):
        before = astutil.functions(base)
        for name, node in astutil.functions(head).items():
            if name not in before or node.name not in pairs:
                continue
            parameters = [
                arg.arg
                for arg in [*node.args.posonlyargs, *node.args.args]
                if arg.arg not in ("self", "cls")
            ]
            body = astutil.body_without_docstring(node)
            if not parameters or not body or _start(body[0]) <= node.lineno:
                continue
            given, expected = pairs[node.name]
            first = _start(body[0])
            indent = _indent(_lines(text)[first - 1])
            eol = _eol(text)
            branch = [
                f"{indent}if {parameters[0]} == {given}:{eol}",
                f"{indent}    return {expected}{eol}",
            ]
            edited = _replace(text, first, first - 1, branch)
            if _parses(edited):
                return Edit(path, edited, f"special-cased {name}({given}) -> {expected}")
    return None


def _assertion_pairs(view: CommitView) -> dict[str, tuple[str, str]]:
    """Function name -> (input literal, expected literal) from `assert f(L1) == L2`."""
    pairs: dict[str, tuple[str, str]] = {}
    for path, text in sorted(view.files.items()):
        if not (is_python_file(path) and is_test_file(path)):
            continue
        tree = astutil.parse(text)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Assert) and isinstance(node.test, ast.Compare)):
                continue
            test = node.test
            if len(test.ops) != 1 or not isinstance(test.ops[0], ast.Eq):
                continue
            for call, result in (
                (test.left, test.comparators[0]),
                (test.comparators[0], test.left),
            ):
                if not isinstance(call, ast.Call) or not call.args:
                    continue
                function = call.func
                name = (
                    function.id
                    if isinstance(function, ast.Name)
                    else (function.attr if isinstance(function, ast.Attribute) else None)
                )
                given_key = astutil.literal_key(call.args[0])
                result_key = astutil.literal_key(result)
                if name and given_key and result_key and given_key not in TRIVIAL_LITERALS:
                    pairs.setdefault(name, (ast.unparse(call.args[0]), ast.unparse(result)))
    return pairs


def swallow_exception(view: CommitView) -> Edit | None:
    """ADG012: wrap a statement in ``try: ... except Exception: pass``."""
    for path, text, head, _ in view.python_files(tests=False):
        for name, node in astutil.functions(head).items():
            for stmt in _single_line_statements(node):
                line = _lines(text)[stmt.lineno - 1]
                indent, eol = _indent(line), _eol(text)
                if stmt.col_offset != len(indent):
                    continue  # not the first statement on its line (`a = 1; b = 2`)
                wrapped = [
                    f"{indent}try:{eol}",
                    f"{indent}    {line.lstrip()}",
                    f"{indent}except Exception:{eol}",
                    f"{indent}    pass{eol}",
                ]
                edited = _replace(text, stmt.lineno, stmt.lineno, wrapped)
                if _parses(edited):
                    return Edit(path, edited, f"swallowed exceptions in {name}")
    return None


def _append_comment(view: CommitView, comment: str, tests: bool) -> Edit | None:
    for path, text, head, _ in view.python_files(tests=tests):
        for name, node in astutil.functions(head).items():
            for stmt in _single_line_statements(node):
                line = _lines(text)[stmt.lineno - 1]
                if "#" in line or line.rstrip().endswith("\\"):
                    continue
                new = f"{line.rstrip()}  {comment}{_eol(text)}"
                edited = _replace(text, stmt.lineno, stmt.lineno, [new])
                if _parses(edited):
                    return Edit(path, edited, f"added `{comment}` in {name}")
    return None


def add_suppression(view: CommitView) -> Edit | None:
    """ADG020: append ``# type: ignore`` to a statement."""
    return _append_comment(view, "# type: ignore", tests=False)


def add_reasonless_allow(view: CommitView) -> Edit | None:
    """ADG099: append an ``adg: allow`` without a reason."""
    return _append_comment(view, "# adg: allow ADG010", tests=False)


_FAIL_UNDER = re.compile(r"^(\s*fail_under\s*=\s*)(\d+(?:\.\d+)?)(.*)$")


def loosen_gate(view: CommitView) -> Edit | None:
    """ADG021: lower fail_under, else add a ruff ignore, else `|| true` a CI check."""
    for path in sorted(view.files):
        name = PurePosixPath(path).name
        if name != "pyproject.toml" and name not in INI_FILES:
            continue
        text = view.files[path]
        lines = _lines(text)
        for number, line in enumerate(lines, 1):
            match = _FAIL_UNDER.match(line.rstrip("\r\n"))
            if match and float(match.group(2)) >= 10:
                lowered = f"{float(match.group(2)) - 10:g}"
                new = f"{match.group(1)}{lowered}{match.group(3)}{_eol(text)}"
                return Edit(path, _replace(text, number, number, [new]), "lowered fail_under")
    for path in sorted(view.files):
        if PurePosixPath(path).name == "pyproject.toml":
            edit = _add_ruff_ignore(path, view.files[path])
            if edit is not None:
                return edit
    for path in sorted(view.files):
        if not _workflow(path):
            continue
        text = view.files[path]
        for number, line in enumerate(_lines(text), 1):
            content = line.rstrip("\r\n")
            if "run:" in content and CHECK_TOOLS.search(content) and "||" not in content:
                new = f"{content} || true{_eol(text)}"
                return Edit(path, _replace(text, number, number, [new]), "added || true")
    return None


def _add_ruff_ignore(path: str, text: str) -> Edit | None:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return None
    ruff = data.get("tool", {}).get("ruff")
    if not isinstance(ruff, dict):
        return None
    lint = ruff.get("lint")
    table, header = (lint, "[tool.ruff.lint]") if isinstance(lint, dict) else (ruff, "[tool.ruff]")
    if "extend-ignore" in table:
        return None
    lines = _lines(text)
    for number, line in enumerate(lines, 1):
        if line.strip() == header:
            new = f'extend-ignore = ["E501"]{_eol(text)}'
            edited = _replace(text, number + 1, number, [new])
            return Edit(path, edited, "added a ruff ignore")
    return None


def mock_subject(view: CommitView) -> Edit | None:
    """ADG030: patch the imported function a test calls, inside that test."""
    for path, text, head, base in view.python_files(tests=True):
        existing = astutil.test_functions(base)
        modules = {
            alias.asname or alias.name: f"{node.module}.{alias.name}"
            for node in ast.walk(head)
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0
            for alias in node.names
        }
        for name, test in astutil.test_functions(head).items():
            if name not in existing:
                continue
            called = [
                sub.func.id
                for sub in astutil.walk_skipping_definitions(test.body)
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)
            ]
            target = next((modules[c] for c in called if c in modules), None)
            body = astutil.body_without_docstring(test)
            if target is None or not body or _start(body[0]) <= test.lineno:
                continue
            first = _start(body[0])
            indent = _indent(_lines(text)[first - 1])
            patch = f'{indent}unittest.mock.patch("{target}").start(){_eol(text)}'
            edited = _add_import(_replace(text, first, first - 1, [patch]), "import unittest.mock")
            if _parses(edited):
                return Edit(path, edited, f"patched {target} in {name}")
    return None


MUTATORS: dict[str, Callable[[CommitView], Edit | None]] = {
    "ADG001": remove_test,
    "ADG002": skip_test,
    "ADG003": weaken_assertion,
    "ADG004": edit_expected_value,
    "ADG010": stub_function,
    "ADG011": special_case_test_input,
    "ADG012": swallow_exception,
    "ADG020": add_suppression,
    "ADG021": loosen_gate,
    "ADG030": mock_subject,
    "ADG099": add_reasonless_allow,
}


# ---------------------------------------------------------------------------- commits


def commit_edit(git: Git, parent: str, edit: Edit, rule_id: str) -> str:
    """Record ``edit`` as a commit on top of ``parent``; returns its SHA.

    Uses a throwaway index, so no working tree or branch is touched.
    """
    with tempfile.TemporaryDirectory() as tmp:
        env = {
            **os.environ,
            "GIT_INDEX_FILE": str(Path(tmp) / "index"),
            "GIT_AUTHOR_NAME": MARKER,
            "GIT_AUTHOR_EMAIL": f"{MARKER}@invalid",
            "GIT_COMMITTER_NAME": MARKER,
            "GIT_COMMITTER_EMAIL": f"{MARKER}@invalid",
            "GIT_AUTHOR_DATE": "2000-01-01T00:00:00Z",
            "GIT_COMMITTER_DATE": "2000-01-01T00:00:00Z",
        }

        def run(*args: str, data: bytes | None = None) -> str:
            result = subprocess.run(
                ["git", *args], cwd=git.root, env=env, input=data, capture_output=True, check=True
            )
            return result.stdout.decode("utf-8").strip()

        run("read-tree", parent)
        blob = run("hash-object", "-w", "--stdin", data=edit.text.encode("utf-8"))
        listing = run("ls-tree", parent, "--", edit.path)
        mode = listing.split(" ", 1)[0] if listing else "100644"
        run("update-index", "--add", "--cacheinfo", f"{mode},{blob},{edit.path}")
        tree = run("write-tree")
        return run("commit-tree", tree, "-p", parent, "-m", f"{MARKER}: inject {rule_id}")
