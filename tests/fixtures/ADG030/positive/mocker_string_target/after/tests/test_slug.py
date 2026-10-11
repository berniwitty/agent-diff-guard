from text import slugify


def test_slugify(mocker):
    mocker.patch("text.slugify", return_value="a-b")
    assert slugify("A B") == "a-b"
