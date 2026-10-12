# Integrations

All integrations run the same check as `adg check` and read
`[tool.agent-diff-guard]` from `pyproject.toml` at the base revision.

## pre-commit

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/berniwitty/agent-diff-guard
    rev: v0.1.0
    hooks:
      - id: agent-diff-guard   # runs `adg check --staged`
```

## GitHub Action

```yaml
# .github/workflows/adg.yml
name: agent-diff-guard
on: [pull_request]
permissions:
  contents: read
  security-events: write   # for the SARIF upload
jobs:
  adg:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0       # adg needs the base commit
      - uses: berniwitty/agent-diff-guard@v0.1.0
        with:
          fail-on: error       # optional; also: base, coverage, upload-sarif, fail-on-findings
```

The action:
- compares the PR head against the PR's base commit (or `github.event.before` on push),
- uploads SARIF so findings appear as code-scanning annotations on the diff,
- writes a Markdown summary to the job summary page,
- fails the step when there are findings at or above `fail-on` (set
  `fail-on-findings: "false"` to only report; the `exit-code` output still says what
  adg found, and usage errors still fail).

This repository runs the action on itself in
[`.github/workflows/action.yml`](../.github/workflows/action.yml): once on each change
(must pass, and uploads its SARIF so findings annotate this repository's PRs) and once on
a commit with a planted stub (must report ADG010).

Code scanning (the SARIF upload) needs GitHub Advanced Security on private repositories.
Set `upload-sarif: "false"` if it is not available; the job summary and exit code still
work.

## Claude Code hook

`adg hook claude-code` is a [Stop hook](https://code.claude.com/docs/en/hooks). When Claude
tries to finish, it checks the working tree. If there are findings, it returns
`{"decision": "block", "reason": ...}` so Claude keeps working and receives the report
with instructions to fix the cause rather than suppress it.

In `.claude/settings.json`:

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          { "type": "command", "command": "adg hook claude-code", "timeout": 120 }
        ]
      }
    ]
  }
}
```

Options:
- `--base origin/main` checks everything on the branch, not just uncommitted changes.
  Use this if the agent commits as it goes.
- `--fail-on warn` also blocks on warnings.
- `--once` blocks only the first time Claude tries to stop (when the hook input has
  `stop_hook_active: false`).

Without `--once`, the hook keeps blocking while findings remain. Claude Code ends the
turn anyway after 8 consecutive stop-hook continuations, and resets that count whenever
Claude calls a tool. So an agent that keeps fixing things keeps getting feedback, and
one that is stuck is stopped.

If `adg` cannot run (not a git repository, invalid config), the hook exits 1. Claude Code
treats that as a non-blocking error and shows the message to the user.

## Agent skill

[`skills/agent-diff-guard/SKILL.md`](../skills/agent-diff-guard/SKILL.md) tells an agent to
run `adg check` before claiming a task is done, and how to respond to each finding. Copy
the `skills/agent-diff-guard/` directory into your agent's skills directory (for Claude
Code: `.claude/skills/` in the project, or `~/.claude/skills/`).
