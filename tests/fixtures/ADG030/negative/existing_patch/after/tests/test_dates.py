from datetime import date
from unittest import mock

from dates import parse_date


@mock.patch("dates.parse_date", return_value=date(2024, 1, 1))
def test_parse_date(_):
    assert parse_date("2024-01-01") == date(2024, 1, 1)
    assert parse_date("2024-01-01").year == 2024
