from parse import parse


def test_parse():
    assert parse("1") == 1


def test_parse_returns_something():
    assert parse("7") is not None
