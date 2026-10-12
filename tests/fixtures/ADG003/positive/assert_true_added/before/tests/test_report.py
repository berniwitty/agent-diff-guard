from report import build


def test_build():
    report = build([1, 2])
    assert report.total == 3
