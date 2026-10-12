from datetime import date
from unittest import mock

from dates import parse_date


@mock.patch("dates.fetch_timezone", return_value="UTC")
def test_parse_date(_):
    assert parse_date("2024-01-01") == date(2024, 1, 1)
