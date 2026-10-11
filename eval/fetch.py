"""Clone the evaluation repositories listed in eval/repos.txt into eval/.repos/.

Usage::

    python -m eval.fetch

Existing clones are fetched instead of re-cloned. The repositories are only read as
data (git objects parsed with ``ast``); none of their code is run.
"""

from __future__ import annotations

import argparse
import subprocess
from collections.abc import Sequence
from pathlib import Path

from eval.run import EVAL_DIR


def read_repos(path: Path) -> list[tuple[str, str]]:
    repos = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            name, url = line.split()
            repos.append((name, url))
    return repos


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repos-file", type=Path, default=EVAL_DIR / "repos.txt")
    parser.add_argument("--dest", type=Path, default=EVAL_DIR / ".repos")
    args = parser.parse_args(argv)
    args.dest.mkdir(parents=True, exist_ok=True)
    for name, url in read_repos(args.repos_file):
        target = args.dest / name
        if target.exists():
            subprocess.run(["git", "-C", str(target), "fetch", "--quiet"], check=True)
        else:
            subprocess.run(
                ["git", "clone", "--quiet", "--no-checkout", url, str(target)], check=True
            )
        print(f"{name}: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
