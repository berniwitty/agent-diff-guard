from calc import divide


def test_divide():
    assert divide(6, 3) == 2


def test_divide_floats():
    assert divide(1.0, 4.0) == 0.25
