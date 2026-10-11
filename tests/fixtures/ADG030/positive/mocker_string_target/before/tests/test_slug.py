from text import slugify


def test_slugify():
    assert slugify("A B") == "a-b"
