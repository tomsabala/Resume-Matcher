"""LaTeX generation from the dynamic document.

These pin the structural decisions a reader of the .tex depends on: which
environment an entry becomes, that empty sections do not emit empty headings,
and that nothing user-authored escapes the ``tex`` filter.
"""

from typing import Any

import pytest

from app.latex.render import (
    LATEX_TEMPLATES,
    UnknownLatexTemplateError,
    contact_url,
    render_document_tex,
)
from app.schemas.document import Contact, ResumeDocument

pytestmark = pytest.mark.unit


def _document(**sections: Any) -> ResumeDocument:
    return ResumeDocument.model_validate(
        {
            "schemaVersion": 2,
            "header": {"name": "Ada Lovelace", "headline": "Engineer"},
            "sections": list(sections.values()),
        }
    )


def _section(key: str, kind: str, **content: Any) -> dict[str, Any]:
    return {
        "id": f"s-{key}",
        "key": key,
        "heading": key.title(),
        "kind": kind,
        "visible": True,
        "column": "main",
        **content,
    }


def _entry(**fields: Any) -> dict[str, Any]:
    return {"id": "e-1", "title": "Acme", "period": "2020", **fields}


@pytest.mark.parametrize("template_id", sorted(LATEX_TEMPLATES))
def test_every_template_produces_a_complete_document(template_id: str) -> None:
    source = render_document_tex(
        _document(s=_section("summary", "text", text="Hello.")), template_id
    )

    assert source.startswith("\\documentclass")
    assert source.count(r"\begin{document}") == 1
    assert source.rstrip().endswith(r"\end{document}")


def test_an_unknown_template_raises_rather_than_silently_picking_one() -> None:
    with pytest.raises(UnknownLatexTemplateError):
        render_document_tex(_document(), "tex-nope")


def test_an_entry_with_bullets_becomes_joblong_and_one_without_becomes_jobshort() -> None:
    """The two environments differ in whether they open an itemize; picking
    the wrong one emits \\item outside a list, which does not compile."""
    with_bullets = render_document_tex(
        _document(
            s=_section(
                "experience",
                "entries",
                entries=[_entry(bullets=[{"text": "Shipped it", "style": "bullet"}])],
            )
        )
    )
    without = render_document_tex(
        _document(
            s=_section("experience", "entries", entries=[_entry(summary="Did work.")])
        )
    )

    assert r"\begin{joblong}{Acme}{2020}" in with_bullets
    assert r"\begin{jobshort}" not in with_bullets
    assert r"\begin{jobshort}{Acme}{2020}" in without
    assert r"\item" not in without


def test_consecutive_entries_are_separated_in_vertical_mode() -> None:
    """`\\vspace` issued in horizontal mode does nothing useful: the next
    entry's title row gets glued to the bullet list above it and indented by
    a space. The separator needs a blank line on both sides, the way the
    reference CV writes it by hand. Observed on a real two-project section.
    """
    source = render_document_tex(
        _document(
            s=_section(
                "projects",
                "entries",
                entries=[
                    {
                        "id": "e-1",
                        "title": "First",
                        "bullets": [{"text": "Did a thing", "style": "bullet"}],
                    },
                    {
                        "id": "e-2",
                        "title": "Second",
                        "bullets": [{"text": "Did another", "style": "bullet"}],
                    },
                ],
            )
        )
    )

    assert "\\end{joblong}\n\n\\vspace{1pt}\n\n\\begin{joblong}{Second}" in source
    # The last entry falls through to the section's own trailing spacing.
    assert source.count(r"\vspace{1pt}") == 1


def test_a_summary_and_bullets_together_keep_the_summary_out_of_the_list() -> None:
    source = render_document_tex(
        _document(
            s=_section(
                "experience",
                "entries",
                entries=[
                    _entry(
                        summary="Owned the platform.",
                        bullets=[{"text": "Shipped it", "style": "bullet"}],
                    )
                ],
            )
        )
    )

    # Search the body: the preamble defines an itemize inside `joblong`.
    body = source[source.index(r"\begin{document}") :]
    assert body.index("Owned the platform.") < body.index(r"\begin{itemize}")


def test_a_plain_bullet_renders_without_a_marker() -> None:
    """``style: plain`` is the document's way of saying "a paragraph inside
    this entry", and it must not sprout a bullet glyph."""
    source = render_document_tex(
        _document(
            s=_section(
                "experience",
                "entries",
                entries=[
                    _entry(
                        bullets=[
                            {"text": "Marked", "style": "bullet"},
                            {"text": "Unmarked", "style": "plain"},
                        ]
                    )
                ],
            )
        )
    )

    assert r"\item Marked" in source
    assert r"\item[] Unmarked" in source


@pytest.mark.parametrize(
    "kind,content",
    [
        ("text", {"text": "   "}),
        ("entries", {"entries": []}),
        ("tags", {"tags": ["", "  "]}),
        ("groups", {"groups": [{"label": "Empty", "values": []}]}),
    ],
)
def test_an_empty_section_emits_no_heading(kind: str, content: dict[str, Any]) -> None:
    source = render_document_tex(_document(s=_section("ghost", kind, **content)))

    assert r"\section{Ghost}" not in source


def test_a_hidden_section_is_omitted() -> None:
    source = render_document_tex(
        _document(s=_section("secret", "text", text="Hidden.", visible=False))
    )

    assert "Hidden." not in source


def test_tags_and_groups_render_as_separated_value_lists() -> None:
    source = render_document_tex(
        _document(
            t=_section("langs", "tags", tags=["Go", "Rust"]),
            g=_section(
                "skills",
                "groups",
                groups=[{"label": "Cloud", "values": ["AWS", "GCP"]}],
            ),
        )
    )

    assert "Go $|$ Rust" in source
    assert r"\textbf{Cloud:} & AWS $|$ GCP" in source


def test_special_characters_survive_every_interpolation_site() -> None:
    """One unfiltered site is enough to break compilation; check the ones a
    resume actually fills."""
    source = render_document_tex(
        _document(
            s=_section(
                "r&d",
                "entries",
                heading="R&D",
                entries=[
                    _entry(
                        title="100% Corp",
                        subtitle="Head of C#",
                        summary="Owned $1M budget",
                        bullets=[{"text": "Cut cost_per_unit by 50%", "style": "bullet"}],
                    )
                ],
            )
        )
    )

    for raw in ("R&D", "100%", "C#", "cost_per_unit", "50%"):
        assert raw not in source
    assert r"Owned \$1M budget" in source
    assert r"\section{R\&D}" in source
    assert r"100\% Corp" in source
    assert r"cost\_per\_unit by 50\%" in source


def test_the_header_name_is_escaped_inside_the_pdf_title_too() -> None:
    document = ResumeDocument.model_validate(
        {"schemaVersion": 2, "header": {"name": "A & B"}, "sections": []}
    )

    source = render_document_tex(document)

    assert "pdftitle={A \\& B}" in source


@pytest.mark.parametrize(
    "kind,value,expected",
    [
        ("email", "ada@example.com", "mailto:ada@example.com"),
        ("phone", "054-526-6266", "tel:0545266266"),
        ("website", "ada.dev", "https://ada.dev"),
        ("website", "https://ada.dev", "https://ada.dev"),
        ("location", "Tel Aviv", ""),
    ],
)
def test_a_contact_url_is_derived_when_the_user_did_not_type_one(
    kind: str, value: str, expected: str
) -> None:
    assert contact_url(Contact(kind=kind, value=value)) == expected


def test_an_explicit_contact_url_is_never_overridden() -> None:
    contact = Contact(kind="website", value="ada.dev", url="https://other.example")

    assert contact_url(contact) == "https://other.example"
