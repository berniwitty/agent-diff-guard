import pytest
from parse import parse


def test_rejects_negative():
    with pytest.raises(Exception):
        parse("-1")
