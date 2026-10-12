from datetime import date

from dates import now, parse_date


def test_parse_date(monkeypatch):
    monkeypatch.setattr("dates.now", lambda: date(2024, 1, 2))
    assert parse_date("2024-01-01") == date(2024, 1, 1)
