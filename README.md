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

## Install

```bash
pip install shortcut-guard   # provides the `adg` command
```

The distribution is called `shortcut-guard` because `agent-diff-guard` was already taken
on PyPI; the command (`adg`) and the import package (`agent_diff_guard`) keep this name.

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

## Evaluation

The benchmark needs no manual labelling (SPEC §6). Original commits from
well-maintained projects are the negatives; `eval/inject.py` plants one shortcut per
rule on top of each commit for the positives.

```bash
make eval-repos     # clone eval/repos.txt into eval/.repos/   (uv run python -m eval.fetch)
make eval-commits   # pin candidate commits in eval/commits.txt (uv run python -m eval.select_commits NAME)
make eval           # write eval/results/RESULTS.md           (uv run python -m eval.run)
```

Results on 300 commits from httpx, pydantic and rich (details and every flagged original
commit: [docs/evaluation.md](docs/evaluation.md)):

| Rule | Severity | Injected | Detected | Recall | Originals flagged | FP rate |
|---|---|---|---|---|---|---|
| ADG001 | error | 300 | 297 | 99% | 24 | 8.0% ⚠ |
| ADG002 | error | 300 | 300 | 100% | 2 | 0.7% |
| ADG003 | error | 300 | 298 | 99% | 11 | 3.7% |
| ADG004 | warn | 23 | 23 | 100% | 1 | 0.3% |
| ADG010 | error | 300 | 300 | 100% | 0 | 0.0% |
| ADG011 | error | 300 | 300 | 100% | 0 | 0.0% |
| ADG012 | warn | 300 | 300 | 100% | 3 | 1.0% |
| ADG020 | warn | 300 | 299 | 100% | 38 | 12.7% |
| ADG021 | error | 200 | 200 | 100% | 2 | 0.7% |
| ADG030 | warn | 300 | 300 | 100% | 0 | 0.0% |
| ADG040 | info | 0 | 0 | n/a | 0 | 0.0% |
| ADG099 | warn | 300 | 300 | 100% | 0 | 0.0% |

`error` rules meet the ≤ 5% false-positive target except **ADG001 (8.0%)**, whose flags
on honest commits are feature removals and test rewrites; see the analysis.

Injected shortcuts are more canonical than the shortcuts real agents take, so recall
on them is an optimistic upper bound.

## Development

```bash
uv sync
uv run pytest --cov --cov-report=term-missing
uv run ruff check . && uv run ruff format --check .
uv run mypy --strict src
uv run adg check --base origin/main
```

## License

MIT, see [LICENSE](LICENSE).
