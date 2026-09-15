"""LaTeX escaping — the boundary every user string crosses.

A miss here is not a formatting bug: unescaped ``%`` silently eats the rest of
a line, and unescaped ``\\`` lets resume content execute as LaTeX.
"""

import pytest

from app.latex.escape import _UNICODE, escape_tex, escape_tex_rich

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
        ("<", r"\textless{}"),
        (">", r"\textgreater{}"),
        ("a|b", r"a\textbar{}b"),
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


@pytest.mark.parametrize("char,macro", _UNICODE)
def test_unicode_the_engine_cannot_typeset_becomes_a_macro(
    char: str, macro: str
) -> None:
    """Each of these aborts the compile with "Unicode character ... not set up
    for use with LaTeX"; the mapped form is what makes the character printable
    at all."""
    result = escape_tex(f"x{char}y")

    assert result == f"x{macro}y"
    assert char not in result


def test_a_mapped_character_is_not_re_escaped_by_the_same_pass() -> None:
    """The macros contain ``\\`` and ``$``, which are themselves in the
    replacement table: a second pass would emit ``\\textbackslash{}geq``."""
    assert escape_tex("≥") == r"$\geq$"
    assert r"\textbackslash" not in escape_tex("≥ ✓ π")


def test_rich_text_tags_become_latex_markup() -> None:
    assert escape_tex_rich("<strong>bold</strong>") == r"\textbf{bold}"
    assert escape_tex_rich("<b>bold</b>") == r"\textbf{bold}"
    assert escape_tex_rich("<em>it</em>") == r"\textit{it}"
    assert escape_tex_rich("<i>it</i>") == r"\textit{it}"
    assert escape_tex_rich("<u>under</u>") == r"\underline{under}"


def test_rich_text_entities_are_decoded_before_escaping() -> None:
    """``&amp;`` must reach the engine as ``\\&``, not ``\\&amp;``, and the
    ``&lt;`` TipTap writes for a typed ``<`` must survive as a real ``<``."""
    assert escape_tex_rich("R&amp;D") == r"R\&D"
    assert escape_tex_rich("p99 &lt; 200ms") == r"p99 \textless{} 200ms"


def test_rich_text_paragraph_wrappers_do_not_print() -> None:
    assert escape_tex_rich("<p>only</p>") == "only"
    assert escape_tex_rich("<p>one</p><p>two</p>") == r"one\par two"
    assert escape_tex_rich("a<br>b") == "a\\\\ b"


def test_rich_text_links_render_only_for_safe_schemes() -> None:
    assert (
        escape_tex_rich('<a href="https://x.dev">link</a>')
        == r"\href{https://x.dev}{link}"
    )
    assert escape_tex_rich('<a href="javascript:alert(1)">click</a>') == "click"
    assert escape_tex_rich('<a href="data:text/html,x">click</a>') == "click"


def test_rich_text_drops_tags_the_sanitiser_should_have_removed() -> None:
    """The backend does not trust the client sanitiser."""
    assert escape_tex_rich("<script>alert(1)</script>ok") == "alert(1)ok"


@pytest.mark.parametrize(
    "markup",
    [
        "<strong>unclosed",
        "</strong>stray",
        "<em><strong>misnested</em></strong>",
        '<a href="https://x.dev">open',
    ],
)
def test_rich_text_always_balances_its_braces(markup: str) -> None:
    """An unbalanced group is a failed compile, so malformed markup must not
    be able to produce one. The inputs carry no literal braces, so every brace
    in the result is one this function opened."""
    result = escape_tex_rich(markup)

    assert result.count("{") == result.count("}")


def test_rich_text_coerces_like_escape_tex() -> None:
    assert escape_tex_rich(None) == ""
    assert escape_tex_rich(42) == "42"
