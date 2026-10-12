import pytest
from parse import parse


def test_rejects_negative():
    with pytest.raises(ValueError, match="negative"):
        parse("-1")
