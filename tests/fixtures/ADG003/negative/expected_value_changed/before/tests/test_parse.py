from parse import parse


def test_parse():
    assert parse("42") == 41
