from pricing import discount


def test_discount_is_capped():
    assert discount(100, 95) == 10
