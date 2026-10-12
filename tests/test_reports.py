"""JSON, SARIF and Markdown reports, plus the suppressed section of the text report."""

from __future__ import annotations

import json as jsonlib

from agent_diff_guard import __version__
from agent_diff_guard.engine import Outcome
from agent_diff_guard.report import json, markdown, sarif, text
from agent_diff_guard.rules import registry
from agent_diff_guard.rules.base import Finding, Severity
from agent_diff_guard.suppress import Suppressed

RULES = tuple(rule for rule in registry.all() if rule.id in {"ADG001", "ADG010", "ADG020"})
STUB = Finding("ADG010", Severity.ERROR, "src/a.py", 3, "Stubbed `f`.", "return 1 -> pass")
REMOVED = Finding("ADG001", Severity.ERROR, "tests/test_b.py", None, "Removed.", "def test_b():")
NOQA = Finding("ADG020", Severity.WARN, "src/c.py", 7, "Added a | pipe.", "x = 1  # noqa")
OUTCOME = Outcome(
    findings=(STUB, REMOVED),
    suppressed=(Suppressed(NOQA, "vendored | as-is"),),
    files_checked=5,
    rules=RULES,
)
EMPTY = Outcome((), (), 0, RULES)


def test_text_lists_suppressions() -> None:
    assert text.render(OUTCOME).splitlines()[-4:] == [
        "Suppressed (1):",
        "  src/c.py:7: ADG020 Added a | pipe.",
        '    reason: "vendored | as-is"',
        "Checked 5 changed file(s) with 3 rule(s): 2 error, 0 warn, 0 info.",
    ]


def test_json_report() -> None:
    assert jsonlib.loads(json.render(OUTCOME)) == {
        "tool": "agent-diff-guard",
        "version": __version__,
        "files_checked": 5,
        "rules": ["ADG001", "ADG010", "ADG020"],
        "summary": {"error": 2, "warn": 0, "info": 0},
        "findings": [
            {
                "rule_id": "ADG010",
                "severity": "error",
                "path": "src/a.py",
                "line": 3,
                "message": "Stubbed `f`.",
                "evidence": "return 1 -> pass",
            },
            {
                "rule_id": "ADG001",
                "severity": "error",
                "path": "tests/test_b.py",
                "line": None,
                "message": "Removed.",
                "evidence": "def test_b():",
            },
        ],
        "suppressed": [
            {
                "rule_id": "ADG020",
                "severity": "warn",
                "path": "src/c.py",
                "line": 7,
                "message": "Added a | pipe.",
                "evidence": "x = 1  # noqa",
                "reason": "vendored | as-is",
            }
        ],
    }


def test_sarif_report() -> None:
    report = jsonlib.loads(sarif.render(OUTCOME))

    assert report["version"] == "2.1.0"
    assert report["$schema"] == sarif.SCHEMA
    [run] = report["runs"]
    driver = run["tool"]["driver"]
    assert (driver["name"], driver["version"]) == ("agent-diff-guard", __version__)
    assert driver["rules"][1] == {
        "id": "ADG010",
        "name": "stub-body",
        "shortDescription": {"text": "stub body"},
        "defaultConfiguration": {"level": "error"},
    }
    # ADG001 is warn by default since v0.1.0 (decided after the evaluation).
    assert [r["defaultConfiguration"]["level"] for r in driver["rules"]] == [
        "warning",
        "error",
        "warning",
    ]
    stub, removed, suppressed = run["results"]
    assert stub == {
        "ruleId": "ADG010",
        "level": "error",
        "message": {"text": "Stubbed `f`."},
        "locations": [
            {
                "physicalLocation": {
                    "artifactLocation": {"uri": "src/a.py"},
                    "region": {"startLine": 3},
                }
            }
        ],
        "properties": {"evidence": "return 1 -> pass"},
    }
    assert removed["locations"] == [
        {"physicalLocation": {"artifactLocation": {"uri": "tests/test_b.py"}}}
    ]
    assert suppressed["level"] == "warning"
    assert suppressed["suppressions"] == [{"kind": "inSource", "justification": "vendored | as-is"}]


def test_sarif_info_level() -> None:
    info = Finding("ADG040", Severity.INFO, "a.py", 1, "m", "e")
    [result] = jsonlib.loads(sarif.render(Outcome((info,), (), 1, ())))["runs"][0]["results"]
    assert result["level"] == "note"


def test_markdown_report_escapes_cells() -> None:
    assert markdown.render(OUTCOME).splitlines() == [
        "## agent-diff-guard",
        "",
        "**2 error, 0 warn, 0 info** in 5 changed file(s), 3 rule(s) checked.",
        "",
        "| Severity | Rule | Location | Finding | Evidence |",
        "|---|---|---|---|---|",
        "| error | ADG010 | `src/a.py:3` | Stubbed `f`. | `return 1 -> pass` |",
        "| error | ADG001 | `tests/test_b.py` | Removed. | `def test_b():` |",
        "",
        "### Suppressed (1)",
        "",
        "| Rule | Location | Finding | Reason |",
        "|---|---|---|---|",
        "| ADG020 | `src/c.py:7` | Added a \\| pipe. | vendored \\| as-is |",
    ]


def test_markdown_without_findings() -> None:
    assert markdown.render(EMPTY) == (
        "## agent-diff-guard\n\n"
        "**0 error, 0 warn, 0 info** in 0 changed file(s), 3 rule(s) checked.\n"
    )
