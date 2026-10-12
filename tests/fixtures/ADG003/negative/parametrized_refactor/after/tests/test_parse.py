import pytest
from parse import parse


@pytest.mark.parametrize(("text", "value"), [("1", 1), ("-2", -2), (" 3 ", 3)])
def test_parse(text, value):
    assert parse(text) == value
