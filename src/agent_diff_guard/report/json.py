"""Machine-readable JSON report."""

from __future__ import annotations

import dataclasses
import json
from typing import Any

from agent_diff_guard import __version__
from agent_diff_guard.engine import Outcome
from agent_diff_guard.rules.base import Finding


def finding_dict(finding: Finding) -> dict[str, Any]:
    data = dataclasses.asdict(finding)
    data["severity"] = str(finding.severity)
    return data


def render(outcome: Outcome) -> str:
    report = {
        "tool": "agent-diff-guard",
        "version": __version__,
        "files_checked": outcome.files_checked,
        "rules": [rule.id for rule in outcome.rules],
        "summary": {str(severity): count for severity, count in outcome.counts().items()},
        "findings": [finding_dict(finding) for finding in outcome.findings],
        "suppressed": [
            {**finding_dict(item.finding), "reason": item.reason} for item in outcome.suppressed
        ],
    }
    return json.dumps(report, indent=2, ensure_ascii=False)
