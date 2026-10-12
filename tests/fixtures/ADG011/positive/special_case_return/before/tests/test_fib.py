from fib import fib


def test_fib_small():
    assert fib(1) == 1


def test_fib_seven():
    assert fib(7) == 13
