from pricing import total


def test_checkout_sum():
    assert total([1, 2]) == 3
