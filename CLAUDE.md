# CLAUDE.md

Instructions for coding agents working in this repository. Read SPEC.md before any task.

## Project
agent-diff-guard (`adg`) inspects a git diff and reports places where a change looks
like a shortcut (deleted tests, weakened assertions, stubbed functions, hard-coded
answers, silenced checks). This tool exists to catch exactly the behaviour listed under
"Never" below — this repo must hold itself to that standard.

## Commands
```bash
uv sync                          # install
uv run pytest                    # tests
uv run pytest --cov --cov-report=term-missing
uv run ruff check . && uv run ruff format --check .
uv run mypy --strict src
uv run adg check --base origin/main   # dogfood on your own changes
make eval                        # precision/recall on the evaluation corpus
```

## Definition of done
A task is done only when ALL of these pass locally and you have shown the output:
1. `uv run pytest` — all green, no new skips.
2. `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy --strict src`.
3. Coverage ≥ 90%.
4. `uv run adg check --base origin/main` reports no `error` findings.
5. If you added or changed a rule: positive fixture, negative fixture, and
   `docs/rules/<ID>.md` exist, `eval/inject.py` has a mutation for it, and
   `make eval` still meets the false-positive target.

Do not say a task is complete before running these. If one fails and you cannot fix
it, stop and report what failed and why.

## Never
- Delete, skip, or `xfail` a test to get the suite green.
- Weaken an assertion, widen a tolerance, or change an expected value to match new
  output — unless the task explicitly says the old expectation was wrong; then say so.
- Edit files under `tests/fixtures/` or `eval/` to make a rule's tests pass. Fixtures
  are ground truth. If you believe a fixture is wrong, stop and ask.
- Add `# type: ignore`, `# noqa`, `# pragma: no cover`, or new ignores in
  `pyproject.toml`.
- Lower `fail_under`, remove CI steps, or edit `.github/workflows/` without being asked.
- Replace a function body with a stub, or special-case a value that appears in a test.
- Catch broad exceptions and swallow them.

## Architecture rules
- Rules live in `src/agent_diff_guard/rules/`, implement the `Rule` protocol in
  `rules/base.py`, and register in the registry. One rule ID per class.
- Rules are pure: they take a `ChangedFile` and `RunContext` and return findings.
  No git calls, no filesystem I/O, no network inside a rule.
- Git access only through `git.py`. Parsing only through stdlib `ast`.
- No LLM calls anywhere in the core path. The tool must be deterministic and offline.
- New runtime dependencies need a one-line justification in the PR description.

## Writing a rule (workflow)
1. Write `docs/rules/<ID>.md`: what it detects, why it matters, one bad and one
   acceptable example, known false positives.
2. Add fixtures: `tests/fixtures/<ID>/positive/<case>/{before,after}/` and
   `.../negative/<case>/{before,after}/`, each with `expected.json`.
3. Run tests — confirm they fail for the right reason.
4. Implement the rule. Keep messages to one sentence; put the snippet in `evidence`.
5. Run the full definition-of-done checklist.

## Style
- Python 3.11+, full type hints, dataclasses (frozen where possible).
- Small functions; AST helpers go in `astutil.py`, not inside rules.
- Error messages say what was found and where, not how the tool works.

## Git
- One issue → one branch → one PR. Branch name: `<issue-number>-short-slug`.
- Conventional commits: `feat(rules): add ADG003 assertion-weakened`.
- PR description: what changed, how it was tested, anything you were unsure about.

## When unsure
Ask instead of guessing on: changing a rule's default severity, changing the `Rule`
or `Finding` interface, anything touching fixtures or the evaluation corpus.
