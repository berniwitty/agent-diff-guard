from calc import add, sub


def test_add():
    assert add(2, 3) == 5


def test_subtract():
    assert sub(5, 3) == 2
