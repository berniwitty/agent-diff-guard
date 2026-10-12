"""Rule implementations; importing this package registers every built-in rule."""

from agent_diff_guard.rules import hollowing, suppression, tests
from agent_diff_guard.rules.base import registry

__all__ = ["hollowing", "registry", "suppression", "tests"]
