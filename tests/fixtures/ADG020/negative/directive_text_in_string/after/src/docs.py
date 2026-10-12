HELP = "usage: tool [options]"
TIP = "add # noqa to silence ruff, or # type: ignore for mypy"


def explain():
    """Never write # pragma: no cover without a reason."""
    return TIP
