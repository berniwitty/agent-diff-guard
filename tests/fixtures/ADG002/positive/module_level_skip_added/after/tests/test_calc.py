import pytest
from calc import add, sub

pytestmark = pytest.mark.skip(reason="wip")


def test_add():
    assert add(2, 3) == 5


def test_sub():
    assert sub(5, 3) == 2
