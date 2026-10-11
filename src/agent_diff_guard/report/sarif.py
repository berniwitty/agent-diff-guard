"""SARIF 2.1.0 report, for GitHub code scanning annotations."""

from __future__ import annotations

import json
from typing import Any

from agent_diff_guard import __version__
from agent_diff_guard.engine import Outcome
from agent_diff_guard.rules.base import Finding, Severity

SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
_LEVELS = {Severity.ERROR: "error", Severity.WARN: "warning", Severity.INFO: "note"}


def _result(finding: Finding) -> dict[str, Any]:
    physical: dict[str, Any] = {"artifactLocation": {"uri": finding.path}}
    if finding.line is not None:
        physical["region"] = {"startLine": finding.line}
    return {
        "ruleId": finding.rule_id,
        "level": _LEVELS[finding.severity],
        "message": {"text": finding.message},
        "locations": [{"physicalLocation": physical}],
        "properties": {"evidence": finding.evidence},
    }


def render(outcome: Outcome) -> str:
    results = [_result(finding) for finding in outcome.findings]
    for item in outcome.suppressed:
        result = _result(item.finding)
        result["suppressions"] = [{"kind": "inSource", "justification": item.reason}]
        results.append(result)
    report = {
        "$schema": SCHEMA,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "agent-diff-guard",
                        "version": __version__,
                        "rules": [
                            {
                                "id": rule.id,
                                "name": rule.name,
                                "shortDescription": {"text": rule.name.replace("-", " ")},
                                "defaultConfiguration": {"level": _LEVELS[rule.default_severity]},
                            }
                            for rule in outcome.rules
                        ],
                    }
                },
                "results": results,
            }
        ],
    }
    return json.dumps(report, indent=2, ensure_ascii=False)
