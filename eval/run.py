"""Measure adg on real commits (SPEC §6).

For each pinned commit in ``eval/commits.txt``:

- **negative**: run adg on parent -> commit. Any finding is a false positive candidate
  (the commit was reviewed and merged upstream) and is listed in the report.
- **positives**: for each rule, inject its shortcut on top of the commit and run adg on
  parent -> injected commit. The rule *detects* the injection when it reports more
  findings in the edited file than it did on the original commit.

Usage::

    python -m eval.run [--commits eval/commits.txt] [--repos eval/.repos]
                       [--out eval/results] [--limit N]
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

from agent_diff_guard.engine import analyze
from agent_diff_guard.git import Git
from agent_diff_guard.rules import registry
from agent_diff_guard.rules.base import Finding, Severity
from eval.inject import MUTATORS, CommitView, commit_edit

EVAL_DIR = Path(__file__).parent
FP_TARGET = 0.05  # SPEC §6: false-positive rate <= 5% on error-level rules


@dataclass
class RuleStats:
    rule_id: str
    severity: str
    applicable: int = 0
    detected: int = 0
    flagged_commits: int = 0
    missed: list[str] = field(default_factory=list)

    def recall(self) -> float | None:
        return self.detected / self.applicable if self.applicable else None


@dataclass
class CommitResult:
    repo: str
    sha: str
    original: list[dict[str, object]]
    injected: dict[str, bool | None]  # rule -> detected (None: not applicable)


def evaluate_commit(repo_name: str, git: Git, sha: str) -> CommitResult:
    head = git.resolve_commit(sha)
    base = git.resolve_commit(f"{head}^")
    rules = registry.all()
    original, _ = analyze(git.root, rules, base=base, head=head)
    view = CommitView.load(git, base, head)
    injected: dict[str, bool | None] = {}
    for rule_id, mutate in MUTATORS.items():
        edit = mutate(view)
        if edit is None:
            injected[rule_id] = None
            continue
        mutated = commit_edit(git, head, edit, rule_id)
        outcome, _ = analyze(git.root, rules, base=base, head=mutated)
        injected[rule_id] = _count(outcome.findings, rule_id, edit.path) > _count(
            original.findings, rule_id, edit.path
        )
    return CommitResult(
        repo=repo_name,
        sha=head,
        original=[_finding_dict(f) for f in original.findings],
        injected=injected,
    )


def _count(findings: Sequence[Finding], rule_id: str, path: str) -> int:
    return sum(1 for f in findings if f.rule_id == rule_id and f.path == path)


def _finding_dict(finding: Finding) -> dict[str, object]:
    data = asdict(finding)
    data["severity"] = str(finding.severity)
    return data


def summarize(results: Sequence[CommitResult]) -> dict[str, RuleStats]:
    stats = {rule.id: RuleStats(rule.id, str(rule.default_severity)) for rule in registry.all()}
    for result in results:
        for rule_id in {str(f["rule_id"]) for f in result.original}:
            stats[rule_id].flagged_commits += 1
        for rule_id, detected in result.injected.items():
            if detected is None:
                continue
            stats[rule_id].applicable += 1
            if detected:
                stats[rule_id].detected += 1
            else:
                stats[rule_id].missed.append(f"{result.repo}@{result.sha[:12]}")
    return stats


def render_markdown(results: Sequence[CommitResult], stats: dict[str, RuleStats]) -> str:
    total = len(results)
    repos = Counter(result.repo for result in results)
    lines = [
        "# agent-diff-guard evaluation",
        "",
        f"{total} commits: " + ", ".join(f"{name} ({n})" for name, n in sorted(repos.items())),
        "",
        "| Rule | Severity | Injected | Detected | Recall | Originals flagged | FP rate |",
        "|---|---|---|---|---|---|---|",
    ]
    for rule_id in sorted(stats):
        s = stats[rule_id]
        recall = s.recall()
        rate = s.flagged_commits / total if total else 0.0
        over = " ⚠" if s.severity == str(Severity.ERROR) and rate > FP_TARGET else ""
        lines.append(
            f"| {rule_id} | {s.severity} | {s.applicable} | {s.detected} "
            f"| {'n/a' if recall is None else f'{recall:.0%}'} "
            f"| {s.flagged_commits} | {rate:.1%}{over} |"
        )
    lines += [
        "",
        f"Target: false-positive rate ≤ {FP_TARGET:.0%} for `error` rules (⚠ marks a miss).",
        "Recall is measured on injected shortcuts, which are more canonical than real",
        "agent shortcuts, so it is an optimistic upper bound.",
        "",
        "## Findings on original commits",
        "",
        "Each is either a rule bug or a real shortcut found in the wild.",
        "",
    ]
    flagged = [(r, f) for r in results for f in r.original]
    if not flagged:
        lines.append("None.")
    for result, finding in flagged:
        where = (
            finding["path"] if finding["line"] is None else f"{finding['path']}:{finding['line']}"
        )
        lines.append(
            f"- `{result.repo}@{result.sha[:12]}` `{where}` {finding['severity']} "
            f"{finding['rule_id']}: {finding['message']}"
        )
    return "\n".join(lines) + "\n"


def read_commits(path: Path) -> list[tuple[str, str]]:
    commits = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            name, sha = line.split()
            commits.append((name, sha))
    return commits


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--commits", type=Path, default=EVAL_DIR / "commits.txt")
    parser.add_argument("--repos", type=Path, default=EVAL_DIR / ".repos")
    parser.add_argument("--out", type=Path, default=EVAL_DIR / "results")
    parser.add_argument("--limit", type=int, default=None, help="Evaluate only N commits.")
    args = parser.parse_args(argv)

    commits = read_commits(args.commits)[: args.limit]
    results = []
    for index, (name, sha) in enumerate(commits, 1):
        print(f"[{index}/{len(commits)}] {name} {sha[:12]}", flush=True)
        results.append(evaluate_commit(name, Git(args.repos / name), sha))
    stats = summarize(results)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "results.json").write_text(
        json.dumps(
            {
                "commits": [asdict(r) for r in results],
                "rules": {rule_id: asdict(s) for rule_id, s in stats.items()},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    report = render_markdown(results, stats)
    (args.out / "RESULTS.md").write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
