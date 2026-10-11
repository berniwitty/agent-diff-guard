# agent-diff-guard

`adg` inspects a git diff and reports places where a change looks like a shortcut taken
to make a task "look done": deleted tests, weakened assertions, stubbed functions,
hard-coded answers, silenced checks. See [SPEC.md](SPEC.md).

Status: pre-release. Implemented rules:

| ID | Name | Default |
|----|------|---------|
| [ADG002](docs/rules/ADG002.md) | test-skipped | error |
| [ADG010](docs/rules/ADG010.md) | stub-body | error |
| [ADG020](docs/rules/ADG020.md) | suppression-added | warn |

## Usage

```bash
adg check                      # uncommitted changes (staged, unstaged, untracked) vs HEAD
adg check --staged             # staged changes vs HEAD
adg check --base origin/main   # everything since the branch forked from origin/main
adg check --base v1.0 --head v1.1
```

Exit code: `0` no findings at or above `--fail-on` (default `error`), `1` findings,
`2` usage or git error.

## Development

```bash
uv sync
uv run pytest --cov --cov-report=term-missing
uv run ruff check . && uv run ruff format --check .
uv run mypy --strict src
uv run adg check --base origin/main
```
