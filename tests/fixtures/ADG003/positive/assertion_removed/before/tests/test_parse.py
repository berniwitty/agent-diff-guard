from parse import parse


def test_parse():
    assert parse("1") == 1
    assert parse("-2") == -2
    assert parse(" 3 ") == 3
