# agent-diff-guard

`adg` inspects a git diff and reports places where a change looks like a shortcut taken
to make a task "look done": deleted tests, weakened assertions, stubbed functions,
hard-coded answers, silenced checks. See [SPEC.md](SPEC.md).

Status: pre-release scaffold — no rules are implemented yet.

## Development

```bash
uv sync
uv run pytest --cov --cov-report=term-missing
uv run ruff check . && uv run ruff format --check .
uv run mypy --strict src
uv run adg check --base origin/main
```
