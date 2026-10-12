# agent-diff-guard

`adg` inspects a git diff and reports places where a change looks like a shortcut taken
to make a task "look done": deleted tests, weakened assertions, stubbed functions,
hard-coded answers, silenced checks. See [SPEC.md](SPEC.md).

Status: pre-release. Implemented rules:

| ID | Name | Default |
|----|------|---------|
| [ADG001](docs/rules/ADG001.md) | test-removed | error |
| [ADG002](docs/rules/ADG002.md) | test-skipped | error |
| [ADG003](docs/rules/ADG003.md) | assertion-weakened | error |
| [ADG004](docs/rules/ADG004.md) | expected-value-edited | warn |
| [ADG010](docs/rules/ADG010.md) | stub-body | error |
| [ADG011](docs/rules/ADG011.md) | hardcoded-test-value | error |
| [ADG012](docs/rules/ADG012.md) | exception-swallowed | warn |
| [ADG020](docs/rules/ADG020.md) | suppression-added | warn |
| [ADG021](docs/rules/ADG021.md) | gate-loosened | error |
| [ADG030](docs/rules/ADG030.md) | mocked-subject | warn |
| [ADG040](docs/rules/ADG040.md) | uncovered-change (needs `--coverage`) | info |
| [ADG099](docs/rules/ADG099.md) | suppression-without-reason | warn |

## Usage

```bash
adg check                      # uncommitted changes (staged, unstaged, untracked) vs HEAD
adg check --staged             # staged changes vs HEAD
adg check --base origin/main   # everything since the branch forked from origin/main
adg check --base v1.0 --head v1.1
adg check --format sarif > adg.sarif   # also: json, markdown
adg check --base origin/main --coverage coverage.xml   # enables ADG040
adg explain ADG003
```

Exit code: `0` no findings at or above `--fail-on` (default `error`), `1` findings,
`2` usage or git error.

## Integrations

pre-commit hook, GitHub Action (SARIF annotations + job summary), Claude Code Stop hook
(`adg hook claude-code`) and an agent skill: see [docs/integrations.md](docs/integrations.md).

## Suppressing a finding

Put an allow comment with a reason on the flagged line:

```python
def legacy_hook(event):  # adg: allow ADG010 reason="kept for plugin API v1"
    pass
```

A suppression without a non-empty reason suppresses nothing and is reported as ADG099.
Every suppression is listed in the report. Findings without a line (a removed test) are
suppressed by an allow for that rule anywhere in the file.

## Configuration

```toml
[tool.agent-diff-guard]
test-patterns = ["tests/", "test_*.py", "*_test.py", "conftest.py"]
exclude = ["tests/fixtures/"]   # "dir/" prefixes or globs on the path
disable = ["ADG004"]
severity = { ADG020 = "error" }
fail-on = "warn"                # --fail-on on the command line wins
```

Configuration is read from `pyproject.toml` **at the base revision**, so a change cannot
loosen the checks applied to itself. A new setting takes effect once it is merged.

## Development

```bash
uv sync
uv run pytest --cov --cov-report=term-missing
uv run ruff check . && uv run ruff format --check .
uv run mypy --strict src
uv run adg check --base origin/main
```
