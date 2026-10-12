from pricing import discount


def test_discount():
    assert discount(200, 25) == 150
