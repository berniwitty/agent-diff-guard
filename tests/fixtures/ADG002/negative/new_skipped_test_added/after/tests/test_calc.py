import pytest
from calc import add, mul, sub


def test_add():
    assert add(2, 3) == 5


def test_sub():
    assert sub(5, 3) == 2


@pytest.mark.skip(reason="mul not implemented yet")
def test_mul():
    assert mul(2, 3) == 6
