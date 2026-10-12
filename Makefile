.PHONY: eval eval-repos eval-commits

# Clone (or update) the repositories in eval/repos.txt into eval/.repos/.
eval-repos:
	uv run python -m eval.fetch

# Pin 100 candidate commits per repository in eval/commits.txt.
eval-commits:
	uv run python -c "import pathlib; pathlib.Path('eval/commits.txt').write_text('# name  sha\n')"
	for repo in httpx pydantic rich; do uv run python -m eval.select_commits $$repo >> eval/commits.txt; done

# Recall on injected shortcuts and false positives on the pinned commits.
eval:
	uv run python -m eval.run
