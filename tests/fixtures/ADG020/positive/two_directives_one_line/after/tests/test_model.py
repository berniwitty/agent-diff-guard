import yaml  # type: ignore[import-untyped]  # noqa: F401
from model import Model


def test_name():
    assert Model().name == "m"
