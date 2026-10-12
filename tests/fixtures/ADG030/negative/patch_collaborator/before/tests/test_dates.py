from datetime import date

from dates import parse_date


def test_parse_date():
    assert parse_date("2024-01-01") == date(2024, 1, 1)
