"""LaTeX escaping — the boundary every user string crosses.

A miss here is not a formatting bug: unescaped ``%`` silently eats the rest of
a line, and unescaped ``\\`` lets resume content execute as LaTeX.
"""

import pytest

from app.latex.escape import escape_tex

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("100%", r"100\%"),
        ("R&D", r"R\&D"),
        ("$120k", r"\$120k"),
        ("snake_case", r"snake\_case"),
        ("#hashtag", r"\#hashtag"),
        ("2^10", r"2\textasciicircum{}10"),
        ("~approx", r"\textasciitilde{}approx"),
        ("{braced}", r"\{braced\}"),
        ("back\\slash", r"back\textbackslash{}slash"),
    ],
)
def test_each_special_character_is_neutralised(raw: str, expected: str) -> None:
    assert escape_tex(raw) == expected


def test_the_adversarial_mix_from_the_spec() -> None:
    assert escape_tex("100% \\& more_$") == r"100\% \textbackslash{}\& more\_\$"


def test_a_backslash_is_escaped_before_the_characters_it_introduces() -> None:
    """Escaping ``\\`` last would double-escape every replacement's own
    backslash and emit literal ``\\textbackslash``."""
    assert escape_tex("\\") == r"\textbackslash{}"
    assert escape_tex("\\%") == r"\textbackslash{}\%"


@pytest.mark.parametrize(
    "attack",
    [
        r"\input{/etc/passwd}",
        r"\write18{rm -rf /}",
        r"\immediate\write\@auxout{}",
        r"\catcode`\%=12",
        r"\end{document}\input{secrets}",
    ],
)
def test_injection_attempts_become_inert_text(attack: str) -> None:
    escaped = escape_tex(attack)

    # No control sequence survives: every backslash is neutralised, and the
    # braces that would delimit an argument are literal.
    assert "\\input" not in escaped
    assert "\\write" not in escaped
    assert "\\end{document}" not in escaped
    assert escaped.count(r"\textbackslash{}") == attack.count("\\")


def test_unbalanced_braces_do_not_leak_into_the_output() -> None:
    assert escape_tex("a{b") == r"a\{b"
    assert escape_tex("a}b") == r"a\}b"


def test_ordinary_text_and_unicode_pass_through_untouched() -> None:
    assert escape_tex("Staff Engineer — Tel Aviv") == "Staff Engineer — Tel Aviv"
    assert escape_tex("שירות צבאי") == "שירות צבאי"


def test_non_strings_are_coerced_so_templates_need_no_guard() -> None:
    assert escape_tex(None) == ""
    assert escape_tex(42) == "42"
