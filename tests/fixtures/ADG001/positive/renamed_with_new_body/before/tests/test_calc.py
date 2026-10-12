from calc import divide


def test_divide():
    assert divide(6, 3) == 2


def test_divide_by_zero_raises():
    try:
        divide(1, 0)
    except ZeroDivisionError:
        return
    raise AssertionError("expected ZeroDivisionError")
