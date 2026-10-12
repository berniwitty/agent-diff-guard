from io_utils import read_lines


def test_read_lines(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("a\nb\n")
    assert read_lines(path) == ["a", "b"]


def test_read_lines_empty(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("")
    assert read_lines(path) == []
