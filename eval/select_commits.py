"""Pick recent non-merge commits that change both Python source and Python tests.

Usage::

    python -m eval.select_commits NAME [--repos eval/.repos] [--count 100] >> eval/commits.txt

Prints ``NAME SHA`` lines, newest first. The selection only depends on the repository's
history, so re-running it at the same HEAD gives the same commits; commits.txt pins them.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterator, Sequence
from pathlib import Path

from agent_diff_guard.classify import is_python_file, is_test_file
from agent_diff_guard.git import Git
from eval.run import EVAL_DIR


def candidate_commits(git: Git, scan: int) -> Iterator[str]:
    """Non-merge commits with a parent that touch both a test and a non-test .py file."""
    log = git.run("log", "--no-merges", "--format=%H %P", f"-n{scan}", "HEAD")
    for line in log.decode("ascii").splitlines():
        sha, *parents = line.split()
        if len(parents) != 1:
            continue
        files = git.run("diff-tree", "--no-commit-id", "--name-only", "-r", "-z", sha)
        paths = [p.decode("utf-8", "surrogateescape") for p in files.split(b"\0") if p]
        python = [p for p in paths if is_python_file(p)]
        if any(is_test_file(p) for p in python) and any(not is_test_file(p) for p in python):
            yield sha


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("name")
    parser.add_argument("--repos", type=Path, default=EVAL_DIR / ".repos")
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--scan", type=int, default=3000, help="How many commits to look at.")
    args = parser.parse_args(argv)
    git = Git(args.repos / args.name)
    for index, sha in enumerate(candidate_commits(git, args.scan)):
        if index >= args.count:
            break
        print(f"{args.name} {sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
