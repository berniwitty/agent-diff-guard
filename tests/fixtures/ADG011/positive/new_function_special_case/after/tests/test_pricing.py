from pricing import price


def test_bulk_price():
    assert price(37) == 112.5
