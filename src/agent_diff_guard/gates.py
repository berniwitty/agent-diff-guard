"""Quality-gate settings read from configuration text. Pure parsing: no I/O."""

from __future__ import annotations

import configparser
import re
import tomllib
from collections import Counter
from dataclasses import dataclass
from typing import Any

# Files whose INI sections can hold coverage or mypy settings.
INI_FILES = frozenset({"setup.cfg", "tox.ini", ".coveragerc", "mypy.ini", ".mypy.ini"})

CHECK_TOOLS = re.compile(
    r"\b(pytest|ruff|mypy|flake8|pylint|pyright|black|isort|tox|nox|coverage|unittest|"
    r"pre-commit|adg)\b"
)
CONTINUE_ON_ERROR = re.compile(r"^\s*-?\s*continue-on-error:\s*true\b", re.IGNORECASE)
OR_TRUE = re.compile(r"\|\|\s*true\b")


@dataclass(frozen=True)
class Gates:
    """The parts of a configuration that decide how strict CI is.

    Ruff per-file ignores are ``"<pattern>:<code>"``; mypy entries are keyed by module
    pattern, ``"*"`` for the global section.
    """

    fail_under: float | None = None
    ruff_ignores: frozenset[str] = frozenset()
    mypy_strict: bool = False
    mypy_disabled_codes: frozenset[str] = frozenset()  # "<module>:<code>"
    mypy_ignore_errors: frozenset[str] = frozenset()  # module patterns


def from_pyproject(text: str) -> Gates | None:
    """Gates in pyproject.toml; ``None`` if it is not valid TOML."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return None
    tool = _table(data, "tool")
    report = _table(_table(tool, "coverage"), "report")
    ruff = _table(tool, "ruff")
    ignores: set[str] = set()
    for section in (ruff, _table(ruff, "lint")):
        for key in ("ignore", "extend-ignore"):
            ignores |= set(_codes(section.get(key)))
        for key in ("per-file-ignores", "extend-per-file-ignores"):
            for pattern, codes in _table(section, key).items():
                ignores |= {f"{pattern}:{code}" for code in _codes(codes)}
    mypy = _table(tool, "mypy")
    disabled = {f"*:{code}" for code in _codes(mypy.get("disable_error_code"))}
    ignore_errors = {"*"} if mypy.get("ignore_errors") is True else set()
    overrides = mypy.get("overrides")
    for override in overrides if isinstance(overrides, list) else []:
        if not isinstance(override, dict):
            continue
        modules = override.get("module")
        for module in [modules] if isinstance(modules, str) else _codes(modules):
            if override.get("ignore_errors") is True:
                ignore_errors.add(module)
            disabled |= {f"{module}:{code}" for code in _codes(override.get("disable_error_code"))}
    return Gates(
        fail_under=_number(report.get("fail_under")),
        ruff_ignores=frozenset(ignores),
        mypy_strict=mypy.get("strict") is True,
        mypy_disabled_codes=frozenset(disabled),
        mypy_ignore_errors=frozenset(ignore_errors),
    )


def from_ini(text: str, filename: str) -> Gates | None:
    """Gates in setup.cfg, tox.ini, .coveragerc or mypy.ini; ``None`` if unparseable."""
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(text)
    except configparser.Error:
        return None
    report = "report" if filename == ".coveragerc" else "coverage:report"
    fail_under = _number(parser.get(report, "fail_under", fallback=None))
    disabled: set[str] = set()
    ignore_errors: set[str] = set()
    strict = False
    for section in parser.sections():
        if section == "mypy":
            module = "*"
            strict = _flag(parser.get(section, "strict", fallback=None))
        elif section.startswith("mypy-"):
            module = section[len("mypy-") :]
        else:
            continue
        if _flag(parser.get(section, "ignore_errors", fallback=None)):
            ignore_errors.add(module)
        codes = parser.get(section, "disable_error_code", fallback="")
        disabled |= {f"{module}:{code}" for code in _codes(codes)}
    return Gates(
        fail_under=fail_under,
        mypy_strict=strict,
        mypy_disabled_codes=frozenset(disabled),
        mypy_ignore_errors=frozenset(ignore_errors),
    )


def workflow_tool_counts(text: str) -> Counter[str]:
    """How often each check tool is named outside comments in a workflow file."""
    counts: Counter[str] = Counter()
    for line in text.splitlines():
        counts.update(match.group(1) for match in CHECK_TOOLS.finditer(strip_yaml_comment(line)))
    return counts


def strip_yaml_comment(line: str) -> str:
    if line.lstrip().startswith("#"):
        return ""
    position = line.find(" #")
    return line if position < 0 else line[:position]


def _table(data: object, key: str) -> dict[str, Any]:
    value = data.get(key) if isinstance(data, dict) else None
    return value if isinstance(value, dict) else {}


def _codes(value: object) -> list[str]:
    """A list of strings, or a comma-separated string, as a list of stripped items."""
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return []


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _flag(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"1", "yes", "true", "on"}
