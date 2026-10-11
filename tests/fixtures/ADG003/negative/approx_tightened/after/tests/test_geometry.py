import pytest
from geometry import area


def test_area():
    assert area(2) == pytest.approx(12.566, rel=1e-4)
