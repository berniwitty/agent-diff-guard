"""Rule implementations; importing this package registers every built-in rule."""

from agent_diff_guard.rules import coverage, hollowing, mocking, suppression, tests
from agent_diff_guard.rules.base import registry

__all__ = ["coverage", "hollowing", "mocking", "registry", "suppression", "tests"]
