"""Claude Code ``Stop`` hook: keep the agent working while adg reports findings.

Protocol (https://code.claude.com/docs/en/hooks, Stop): the hook reads a JSON object
on stdin (``cwd``, ``stop_hook_active``, ...). Printing ``{"decision": "block",
"reason": ...}`` and exiting 0 stops Claude from finishing and hands it ``reason``. Any
exit code other than 0 or 2 is a non-blocking error shown to the user. Claude Code ends
the turn anyway after 8 consecutive stop-hook continuations, and resets that count
whenever Claude calls a tool, so blocking until findings are fixed cannot loop forever.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from agent_diff_guard.config import ConfigError
from agent_diff_guard.engine import EXIT_OK, analyze, exit_code
from agent_diff_guard.git import GitError
from agent_diff_guard.report import text
from agent_diff_guard.rules.base import Rule, Severity

EXIT_HOOK_ERROR = 1

INSTRUCTIONS = """\
agent-diff-guard found changes that look like shortcuts: removed or skipped tests, \
weakened assertions, stubbed functions, hard-coded test answers, or silenced checks.

Fix the underlying problem instead: restore and pass the tests, implement the stubbed \
code, remove special cases and suppressions. Do not skip tests, loosen config, or add \
suppressions to make this check pass.

If a finding is a deliberate and correct change, add `# adg: allow <RULE> reason="..."` \
on the flagged line and tell the user about it in your final message. If you cannot fix \
it, stop and explain to the user what is blocking you."""


def claude_code_stop(
    stdin_text: str,
    rules: Sequence[Rule],
    *,
    base: str | None = None,
    fail_on: Severity | None = None,
    once: bool = False,
) -> tuple[int, str, str]:
    """Run the hook; returns (exit code, stdout, stderr)."""
    try:
        payload = json.loads(stdin_text) if stdin_text.strip() else {}
    except json.JSONDecodeError as exc:
        return EXIT_HOOK_ERROR, "", f"agent-diff-guard: hook input is not JSON: {exc}"
    if not isinstance(payload, dict):
        payload = {}
    if once and payload.get("stop_hook_active") is True:
        return EXIT_OK, "", ""
    cwd = payload.get("cwd")
    repo = Path(cwd) if isinstance(cwd, str) and cwd else Path(".")
    try:
        outcome, config = analyze(repo, rules, base=base)
    except (GitError, ConfigError) as exc:
        return EXIT_HOOK_ERROR, "", f"agent-diff-guard: {exc}"
    threshold = fail_on or config.fail_on or Severity.ERROR
    if exit_code(outcome.findings, threshold) == EXIT_OK:
        return EXIT_OK, "", ""
    reason = f"{INSTRUCTIONS}\n\n{text.render(outcome)}"
    return EXIT_OK, json.dumps({"decision": "block", "reason": reason}), ""
