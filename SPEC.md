# agent-diff-guard — Specification (v0.1)

> Catch the shortcuts coding agents take to make a task "look done":
> deleted tests, weakened assertions, stubbed functions, hard-coded answers,
> and silenced linters. Runs as a CLI, a pre-commit hook, a GitHub Action,
> and a Claude Code hook.

## 1. Problem

Coding agents are optimised to reach a passing state. When the honest path is hard,
they sometimes take a shortcut that passes CI but defeats its purpose: skipping the
failing test, loosening an assertion, special-casing the test input, or adding
`# type: ignore`. These changes are small, easy to miss in review, and invisible to
CI because CI is green.

agent-diff-guard inspects a **diff** (base → head) and reports **findings**: places
where the change matches a known shortcut pattern. It does not judge whether code is
good; it flags changes a human reviewer must look at before merging.

## 2. Scope

**v0.1:** Python repositories only (stdlib `ast`), git diffs, rules R1–R5 below.

**Later:** JS/TS via tree-sitter, per-repo custom rules, LLM-assisted second pass
(optional, off by default — the core must stay deterministic and offline).

**Non-goals:** general linting (ruff does that), security scanning, code style.

## 3. Rules

Each rule has a stable ID, a default severity (`error` / `warn` / `info`), a docs page,
and positive + negative fixtures. Test files are identified by path
(`tests/`, `test_*.py`, `*_test.py`, `conftest.py`), configurable.

### R1 — Test tampering
| ID | Name | Default | Detects |
|----|------|---------|---------|
| ADG001 | test-removed | error | Test file deleted, or a `test_*` function present in base is missing in head (AST compare; renames tracked by body similarity). |
| ADG002 | test-skipped | error | Added `pytest.mark.skip/skipif/xfail`, `unittest.skip*`, `pytest.skip()` calls, or an early `return` at the top of a test function. |
| ADG003 | assertion-weakened | error | Within a test function present in both base and head: fewer `assert`/`self.assert*`/`pytest.raises` calls; strong → weak assertion (`assertEqual` → `assertTrue`, `==` → `is not None`); `assert True`; widened `pytest.approx` tolerance. |
| ADG004 | expected-value-edited | warn | A literal on the expected side of an assertion changed **in the same diff** as the implementation it tests. Legitimate sometimes — flagged for review, not blocked. |

### R2 — Implementation hollowing
| ID | Name | Default | Detects |
|----|------|---------|---------|
| ADG010 | stub-body | error | A non-test function whose body becomes only `pass`, `...`, `return None`, `raise NotImplementedError`, or a TODO comment, where base had real logic. |
| ADG011 | hardcoded-test-value | error | New branch in non-test code comparing an argument to a literal that also appears in a test assertion (e.g. `if n == 7: return 13`). Literal pool built from all test files in head. |
| ADG012 | exception-swallowed | warn | Added `except:` / `except Exception:` whose body is only `pass`, `...`, or `return <constant>`. |

### R3 — Suppression
| ID | Name | Default | Detects |
|----|------|---------|---------|
| ADG020 | suppression-added | warn | New `# type: ignore`, `# noqa`, `# pragma: no cover`, `# pylint: disable`. |
| ADG021 | gate-loosened | error | Changes that lower a quality gate: coverage `fail_under` reduced, new ruff/mypy ignores in `pyproject.toml`/`setup.cfg`, test or lint steps removed from `.github/workflows/*`. |

### R4 — Mocking
| ID | Name | Default | Detects |
|----|------|---------|---------|
| ADG030 | mocked-subject | warn | A test patches (`mock.patch`, `monkeypatch.setattr`) the function it is named after or that its module imports as the subject under test. |

### R5 — Coverage (optional input)
| ID | Name | Default | Detects |
|----|------|---------|---------|
| ADG040 | uncovered-change | info | Added non-test lines not executed by the test suite. Requires `--coverage coverage.xml`; skipped otherwise. |

### Inline suppression
`# adg: allow ADG003 reason="switched to property-based test"` on the flagged line.
A suppression **without a reason is itself a finding** (ADG099). Suppressions are
listed in every report so they stay visible to reviewers.

## 4. Architecture

```
src/agent_diff_guard/
  cli.py            # typer app: `adg check`, `adg rules`, `adg explain <ID>`
  git.py            # resolve base/head, list changed files, read file at a revision
  change.py         # ChangedFile: path, status, base_src, head_src, added/removed line numbers
  classify.py       # is_test_file(), language detection
  config.py         # [tool.agent-diff-guard] in pyproject.toml
  suppress.py       # parse inline allow comments
  rules/
    base.py         # Rule protocol, Finding, Severity, registry
    tests.py        # ADG001–004
    hollowing.py    # ADG010–012
    suppression.py  # ADG020–021
    mocking.py      # ADG030
    coverage.py     # ADG040
  report/
    text.py  json.py  sarif.py  markdown.py
```

```python
class Rule(Protocol):
    id: str                  # "ADG003"
    name: str                # "assertion-weakened"
    default_severity: Severity
    def check(self, change: ChangedFile, ctx: RunContext) -> Iterable[Finding]: ...

@dataclass(frozen=True)
class Finding:
    rule_id: str
    severity: Severity
    path: str
    line: int | None
    message: str             # one sentence, human-readable
    evidence: str            # the offending snippet, before → after where useful
```

Rules are pure functions of (`ChangedFile`, `RunContext`): no git calls, no I/O.
This keeps every rule unit-testable from fixtures.

**Exit codes:** `0` no findings at/above `--fail-on` (default `error`); `1` findings;
`2` usage or internal error.

## 5. Integrations

| Surface | How |
|---------|-----|
| CLI | `adg check --base origin/main` · `adg check --staged` · `adg check --format sarif` |
| pre-commit | `.pre-commit-hooks.yaml` exposing `adg check --staged` |
| GitHub Action | `action.yml`: runs on PRs, uploads SARIF (inline annotations), posts a markdown summary |
| Claude Code hook | Hook that runs `adg check` on the working tree when the agent tries to finish, and feeds findings back so it fixes them before stopping. (Verify the current hook protocol in the official docs before implementing.) |
| Agent skill | `SKILL.md` telling the agent to self-check with `adg` before claiming a task is done |

## 6. Evaluation

A rule set nobody has measured is a guess. The repo ships a benchmark that needs
**no manual labelling** — every label is known by construction.

- **Source commits:** a few hundred recent commits that touch both source and tests,
  taken from well-maintained Python repositories (e.g. httpx, pydantic, rich).
  Pinned by SHA in `eval/commits.txt` for reproducibility.
- **Negatives:** the original commits, assumed honest (reviewed and merged upstream).
- **Positives by injection:** `eval/inject.py` applies one shortcut mutation per rule
  to a commit's after-state (remove a test function, add a skip decorator, drop
  assertions, replace a body with `pass`, add a literal special-case, add
  `# type: ignore`, lower `fail_under`, …). The injected rule ID is the label.
- **Metrics:** per-rule recall on injected diffs; per-rule false-positive rate on
  original commits. Regenerated by `make eval`, reported in the README.
- **Flagged originals:** findings on original commits are listed in the eval report.
  Each is either a rule bug (fix it) or a real shortcut found in the wild (report it).
- **Known limitation:** injected shortcuts are more canonical than real agent
  shortcuts, so recall is an optimistic upper bound. Stated in the README.

Unit-test fixtures in `tests/fixtures/` are separate from the eval set and are not
used for metrics.

Target for v0.1: false-positive rate ≤ 5% on `error`-level rules (a noisy gate gets
disabled).

## 7. Quality bar for this repo

- `ruff check`, `ruff format --check`, `mypy --strict`, `pytest` — all in CI.
- Coverage `fail_under = 90`.
- Every rule: positive fixture, negative fixture, docs page. No exceptions.
- **Dogfooding:** CI runs `adg check --base origin/main` on every PR to this repo.

## 8. Milestones

| # | Deliverable | Est. |
|---|-------------|------|
| M0 | Scaffold: uv, typer CLI stub, CI with all gates, fixture harness (temp git repo from `before/`/`after/`) | 1 day |
| M1 | `git.py` + `change.py`; rules ADG002, ADG010, ADG020 (simplest, regex/AST-light) | 2 days |
| M2 | AST rules ADG001, ADG003, ADG004, ADG011 | 3 days |
| M3 | Config, inline suppression, text/JSON/SARIF/markdown reports | 2 days |
| M4 | ADG012, ADG021, ADG030, ADG040; pre-commit, GitHub Action, Claude Code hook, skill | 2 days |
| M5 | `eval/inject.py` + commit list + `make eval` + README results; tag v0.1.0, publish to PyPI | 2 days |
