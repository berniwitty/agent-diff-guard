from __future__ import annotations

from agent_diff_guard.rules.base import Finding, Severity
from agent_diff_guard.suppress import Allow, Suppressed, apply_suppressions, parse_allows

SOURCE = """\
a = 1  # adg: allow ADG010 reason="kept for v1 API"
b = 2  # adg: allow adg003, ADG004 reason='folded into a property test'
c = 3  # adg: allow ADG010
d = 4  # adg: allow ADG010 reason=""
e = 5  # noqa  # adg: allow ADG020 reason="vendored # copied as-is"
f = "# adg: allow ADG010 reason='in a string'"
g = 7  # adg allow ADG010 reason="missing colon"
"""


def test_parse_allows() -> None:
    assert parse_allows(SOURCE) == [
        Allow(
            1,
            frozenset({"ADG010"}),
            "kept for v1 API",
            'adg: allow ADG010 reason="kept for v1 API"',
        ),
        Allow(
            2,
            frozenset({"ADG003", "ADG004"}),
            "folded into a property test",
            "adg: allow adg003, ADG004 reason='folded into a property test'",
        ),
        Allow(3, frozenset({"ADG010"}), None, "adg: allow ADG010"),
        Allow(4, frozenset({"ADG010"}), None, 'adg: allow ADG010 reason=""'),
        Allow(
            5,
            frozenset({"ADG020"}),
            "vendored # copied as-is",
            'adg: allow ADG020 reason="vendored # copied as-is"',
        ),
    ]


def test_parse_allows_on_untokenizable_source() -> None:
    assert parse_allows('x = """\n# adg: allow ADG010 reason="r"\n') == []


def finding(rule_id: str, line: int | None, path: str = "src/a.py") -> Finding:
    return Finding(rule_id, Severity.ERROR, path, line, "m", "e")


def test_apply_suppressions_needs_matching_line_rule_and_reason() -> None:
    findings = [
        finding("ADG010", 1),  # suppressed
        finding("ADG004", 2),  # suppressed (second id in the list)
        finding("ADG010", 2),  # wrong rule for line 2
        finding("ADG010", 3),  # no reason
        finding("ADG010", 4),  # empty reason
        finding("ADG001", None),  # no line
        finding("ADG010", 1, "src/other.py"),  # no source for this path
    ]

    kept, suppressed = apply_suppressions(findings, {"src/a.py": SOURCE})

    assert kept == [findings[2], findings[3], findings[4], findings[5], findings[6]]
    assert suppressed == [
        Suppressed(findings[0], "kept for v1 API"),
        Suppressed(findings[1], "folded into a property test"),
    ]


def test_file_level_findings_are_suppressed_by_an_allow_anywhere_in_the_file() -> None:
    source = (
        'import x\n\n# adg: allow ADG001 reason="placeholder replaced"\n'
        "y = 1  # adg: allow ADG001\n"
    )
    removed = finding("ADG001", None, "tests/test_a.py")
    other_rule = finding("ADG003", None, "tests/test_a.py")
    on_a_line = finding("ADG001", 1, "tests/test_a.py")

    kept, suppressed = apply_suppressions(
        [removed, other_rule, on_a_line], {"tests/test_a.py": source}
    )

    assert kept == [other_rule, on_a_line]
    assert suppressed == [Suppressed(removed, "placeholder replaced")]
