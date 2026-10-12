"""The evaluation harness: every mutator's shortcut is caught by its rule."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_diff_guard.git import Git
from eval import fetch, run, select_commits
from eval.inject import MUTATORS, CommitView, commit_edit, loosen_gate
from tests.harness import git, make_repo

PRICING_BEFORE = '''"""Pricing."""


def total(items):
    return sum(item.price for item in items)


def discount(price, percent):
    rate = percent / 100
    return price * (1 - rate)
'''

PRICING_AFTER = PRICING_BEFORE.replace("rate = percent / 100", "rate = min(percent, 90) / 100")

TESTS = """from shop.pricing import discount, total


class Item:
    def __init__(self, price):
        self.price = price


def test_total():
    assert total([Item(3), Item(4)]) == 7


def test_discount():
    assert discount(200, 25) == 150
"""

TESTS_AFTER = (
    TESTS
    + """

def test_discount_is_capped():
    assert discount(100, 95) == 10
"""
)

PYPROJECT = '[project]\nname = "shop"\n\n[tool.coverage.report]\nfail_under = 90\n'


@pytest.fixture
def honest_commit(tmp_path: Path) -> tuple[Git, str, str]:
    """A realistic change: implementation fix plus a new test, nothing suspicious."""
    before = {
        "src/shop/pricing.py": PRICING_BEFORE,
        "tests/test_pricing.py": TESTS,
        "pyproject.toml": PYPROJECT,
    }
    after = {**before, "src/shop/pricing.py": PRICING_AFTER, "tests/test_pricing.py": TESTS_AFTER}
    repo = make_repo(tmp_path, before, after)
    return Git(repo.path), repo.base, repo.head


def test_every_injected_shortcut_is_detected(honest_commit: tuple[Git, str, str]) -> None:
    repo, _, head = honest_commit

    result = run.evaluate_commit("shop", repo, head)

    assert result.original == []
    assert result.injected == {rule_id: True for rule_id in MUTATORS}


def test_mutators_return_none_without_material(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, {"README.md": "a\n"}, {"README.md": "b\n"})
    view = CommitView.load(Git(repo.path), repo.base, repo.head)
    assert {rule_id: mutate(view) for rule_id, mutate in MUTATORS.items()} == dict.fromkeys(
        MUTATORS
    )


def test_injected_commit_leaves_the_repository_untouched(
    honest_commit: tuple[Git, str, str],
) -> None:
    repo, base, head = honest_commit
    view = CommitView.load(repo, base, head)
    edit = MUTATORS["ADG010"](view)
    assert edit is not None

    injected = commit_edit(repo, head, edit, "ADG010")

    assert git(repo.root, "rev-parse", "HEAD") == head
    assert git(repo.root, "status", "--porcelain") == ""
    assert git(repo.root, "rev-parse", f"{injected}^") == head
    assert git(repo.root, "diff", "--name-only", head, injected) == "src/shop/pricing.py"


@pytest.mark.parametrize(
    ("files", "changed_path", "expected"),
    [
        (
            {"pyproject.toml": "[tool.ruff.lint]\nselect = ['E']\n"},
            "pyproject.toml",
            "[tool.ruff.lint]\nextend-ignore = [\"E501\"]\nselect = ['E']\n",
        ),
        (
            {"pyproject.toml": "[tool.ruff]\nline-length = 90\n"},
            "pyproject.toml",
            '[tool.ruff]\nextend-ignore = ["E501"]\nline-length = 90\n',
        ),
        (
            # E501 is already ignored, so the injection must pick another code.
            {"pyproject.toml": "[tool.ruff]\nignore = ['E501']\n"},
            "pyproject.toml",
            "[tool.ruff]\nextend-ignore = [\"F401\"]\nignore = ['E501']\n",
        ),
        (
            {".github/workflows/ci.yml": "steps:\n  - run: pytest -q\n"},
            ".github/workflows/ci.yml",
            "steps:\n  - run: pytest -q || true\n",
        ),
        (
            {"setup.cfg": "[coverage:report]\nfail_under = 85.5  # keep\n"},
            "setup.cfg",
            "[coverage:report]\nfail_under = 75.5  # keep\n",
        ),
    ],
)
def test_loosen_gate_fallbacks(
    tmp_path: Path, files: dict[str, str], changed_path: str, expected: str
) -> None:
    repo = make_repo(tmp_path, files, {**files, "x.py": "x = 1\n"})
    edit = loosen_gate(CommitView.load(Git(repo.path), repo.base, repo.head))
    assert edit is not None
    assert (edit.path, edit.text) == (changed_path, expected)


@pytest.mark.parametrize(
    "files",
    [
        {"pyproject.toml": "[tool.ruff]\nextend-ignore = ['E501']\n"},
        {"pyproject.toml": "[tool.ruff\n"},
        {"pyproject.toml": "[tool.ruff]\nignore = ['E501', 'F401', 'E722', 'B008', 'S101']\n"},
        {"pyproject.toml": "[project]\nname = 'x'\n"},
        {"setup.cfg": "[coverage:report]\nfail_under = 5\n"},
        {".github/workflows/ci.yml": "steps:\n  - run: pytest || exit 0\n"},
    ],
)
def test_loosen_gate_not_applicable(tmp_path: Path, files: dict[str, str]) -> None:
    repo = make_repo(tmp_path, files, {**files, "x.py": "x = 1\n"})
    assert loosen_gate(CommitView.load(Git(repo.path), repo.base, repo.head)) is None


def test_summary_and_report() -> None:
    results = [
        run.CommitResult(
            "shop",
            "a" * 40,
            [
                {
                    "rule_id": "ADG010",
                    "severity": "error",
                    "path": "src/a.py",
                    "line": 3,
                    "message": "Stubbed.",
                    "evidence": "pass",
                }
            ],
            {"ADG010": True, "ADG002": False, "ADG004": None},
        ),
        run.CommitResult("shop", "b" * 40, [], {"ADG010": True, "ADG002": True}),
    ]

    stats = run.summarize(results)
    report = run.render_markdown(results, stats)

    assert (stats["ADG010"].applicable, stats["ADG010"].detected) == (2, 2)
    assert stats["ADG010"].flagged_commits == 1
    assert stats["ADG002"].recall() == 0.5
    assert stats["ADG002"].missed == ["shop@aaaaaaaaaaaa"]
    assert stats["ADG004"].recall() is None
    assert "| ADG010 | error | 2 | 2 | 100% | 1 | 50.0% ⚠ |" in report
    assert "| ADG004 | warn | 0 | 0 | n/a | 0 | 0.0% |" in report
    assert "- `shop@aaaaaaaaaaaa` `src/a.py:3` error ADG010: Stubbed." in report
    assert run.render_markdown([], run.summarize([])).count("None.") == 1


def test_run_main_end_to_end(tmp_path: Path, honest_commit: tuple[Git, str, str]) -> None:
    repo, _, head = honest_commit
    commits = tmp_path / "commits.txt"
    # Clones live at <repos>/<name>; make_repo put this one at <tmp_path>/repo.
    commits.write_text(f"# pinned\n{repo.root.name} {head}  # honest\n\n", encoding="utf-8")
    out = tmp_path / "out"

    code = run.main(
        ["--commits", str(commits), "--repos", str(repo.root.parent), "--out", str(out)]
    )
    args = ["--commits", str(commits), "--repos", str(repo.root.parent)]
    parallel = run.main([*args, "--out", str(out / "p"), "--jobs", "2"])

    assert code == parallel == 0
    assert (out / "p" / "RESULTS.md").read_text(encoding="utf-8") == (out / "RESULTS.md").read_text(
        encoding="utf-8"
    )
    assert "| ADG001 | error | 1 | 1 | 100% | 0 | 0.0% |" in (out / "RESULTS.md").read_text(
        encoding="utf-8"
    )
    assert '"sha": "' + head in (out / "results.json").read_text(encoding="utf-8")


def test_select_commits(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = make_repo(tmp_path, {"src/a.py": "a = 1\n"}, {"src/a.py": "a = 2\n"})
    only_source = repo.head
    (repo.path / "src" / "a.py").write_text("a = 3\n", encoding="utf-8")
    (repo.path / "tests").mkdir()
    (repo.path / "tests" / "test_a.py").write_text("def test_a():\n    pass\n", encoding="utf-8")
    git(repo.path, "add", "--all")
    git(repo.path, "commit", "--quiet", "-m", "source and tests")
    both = git(repo.path, "rev-parse", "HEAD")

    assert list(select_commits.candidate_commits(Git(repo.path), 10)) == [both]
    assert only_source != both
    select_commits.main(["repo", "--repos", str(repo.path.parent), "--count", "5"])
    assert capsys.readouterr().out == f"repo {both}\n"
    select_commits.main(["repo", "--repos", str(repo.path.parent), "--count", "0"])
    assert capsys.readouterr().out == ""


def test_read_repos_and_commits(tmp_path: Path) -> None:
    listing = tmp_path / "repos.txt"
    listing.write_text("# comment\nhttpx https://example.invalid/httpx  # note\n\n", "utf-8")
    assert fetch.read_repos(listing) == [("httpx", "https://example.invalid/httpx")]
