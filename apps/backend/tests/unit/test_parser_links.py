"""Hyperlink recovery from uploaded PDFs.

MarkItDown reads only a PDF's text stream, where a hyperlink is at best its
anchor text and at worst an icon glyph. The links live in each page's
``/Annots`` array, so they are read from there, written into the extracted
text, and re-attached deterministically after the LLM has answered.
"""

from typing import Any

import pytest

from app.latex.compile import compile_tex_to_pdf, latex_engine
from app.latex.render import render_document_tex
from app.schemas.document import Contact, EntryLink, ResumeDocument
from app.services.parser import (
    LINKS_BLOCK_HEADING,
    ExtractedLink,
    _extract_pdf_links,
    _parse_document_sync,
    format_links_block,
    restore_links_from_markdown,
)

pytestmark = pytest.mark.unit


def _pdf_object(body: str) -> bytes:
    return body.encode("latin-1")


def _minimal_pdf(
    lines: list[tuple[float, str]],
    annotations: list[tuple[str, tuple[float, float, float, float]]],
) -> bytes:
    """Build a one-page PDF with the given text lines and URI annotations.

    Hand-built so that annotation handling can be tested without a TeX engine:
    a producer that emits a ``javascript:`` action is exactly what no real
    resume generator will hand us.
    """
    content = "BT /F1 11 Tf\n"
    for baseline, text in lines:
        content += f"1 0 0 1 72 {baseline} Tm ({text}) Tj\n"
    content += "ET"

    annotation_ids = [6 + index for index in range(len(annotations))]
    annots = " ".join(f"{object_id} 0 R" for object_id in annotation_ids)
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        "/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R"
        + (f" /Annots [{annots}]" if annots else "")
        + " >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for uri, rect in annotations:
        objects.append(
            "<< /Type /Annot /Subtype /Link /Border [0 0 0] "
            f"/Rect [{rect[0]} {rect[1]} {rect[2]} {rect[3]}] "
            f"/A << /Type /Action /S /URI /URI ({uri}) >> >>"
        )

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += _pdf_object(f"{index} 0 obj\n{body}\nendobj\n")
    xref_offset = len(out)
    out += _pdf_object(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n")
    for offset in offsets:
        out += _pdf_object(f"{offset:010d} 00000 n \n")
    out += _pdf_object(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    )
    return bytes(out)


def _linked_document(sample_resume: dict[str, Any]) -> ResumeDocument:
    """The sample document with a header url and an entry repo link."""
    document = ResumeDocument.model_validate(sample_resume)
    document.header.contacts.append(
        Contact(kind="github", url="https://github.com/octocat")
    )
    for section in document.sections:
        if section.entries:
            section.entries[0].links.append(
                EntryLink(kind="github", url="https://github.com/octocat/telemetry")
            )
            break
    return document


@pytest.mark.skipif(latex_engine() is None, reason="no LaTeX engine installed")
async def test_annotations_of_our_own_pdf_carry_kind_and_entry_context(
    sample_resume: dict[str, Any], tmp_path: Any
) -> None:
    """The reported bug: a hyperref-built CV keeps its links only if we read
    the annotations. Build the fixture from our own pipeline so no binary blob
    enters the repo."""
    document = _linked_document(sample_resume)
    entry_title = next(
        section.entries[0].title for section in document.sections if section.entries
    )
    pdf = await compile_tex_to_pdf(render_document_tex(document))
    path = tmp_path / "cv.pdf"
    path.write_bytes(pdf)

    links = _extract_pdf_links(path)

    by_url = {link.url: link for link in links}
    assert by_url["https://github.com/octocat"].kind == "github"
    assert by_url["https://github.com/octocat"].scope == "header"
    entry_link = by_url["https://github.com/octocat/telemetry"]
    assert entry_link.kind == "github"
    assert entry_link.scope == "entry"
    assert entry_title.split()[0].lower() in entry_link.context.lower()


def test_only_web_and_contact_schemes_survive(tmp_path: Any) -> None:
    """An annotation action can name any scheme; a resume link cannot."""
    pdf = _minimal_pdf(
        [(700.0, "Portfolio")],
        [
            ("https://example.com/cv", (72.0, 695.0, 200.0, 710.0)),
            ("javascript:alert(1)", (210.0, 695.0, 300.0, 710.0)),
            ("data:text/html,<script>", (310.0, 695.0, 400.0, 710.0)),
        ],
    )
    path = tmp_path / "hand.pdf"
    path.write_bytes(pdf)

    links = _extract_pdf_links(path)

    assert [link.url for link in links] == ["https://example.com/cv"]
    assert links[0].kind == "website"
    assert links[0].context == "Portfolio"


def test_a_pdf_without_annotations_extracts_exactly_as_before(tmp_path: Any) -> None:
    path = tmp_path / "plain.pdf"
    pdf = _minimal_pdf([(700.0, "Jane Doe"), (680.0, "Engineer")], [])
    path.write_bytes(pdf)

    assert _extract_pdf_links(path) == []

    text = _parse_document_sync(pdf, "plain.pdf")

    assert LINKS_BLOCK_HEADING not in text
    assert "Jane Doe" in text


def test_a_pdf_with_annotations_gets_the_block_appended(tmp_path: Any) -> None:
    # 842pt page: the contact row sits inside the top 15% band, the project
    # link far below it.
    pdf = _minimal_pdf(
        [(780.0, "Jane Doe"), (400.0, "Telemetry pipeline")],
        [
            ("https://github.com/jane", (72.0, 775.0, 140.0, 790.0)),
            ("https://github.com/jane/telemetry", (500.0, 395.0, 540.0, 410.0)),
        ],
    )

    text = _parse_document_sync(pdf, "upload.pdf")

    assert LINKS_BLOCK_HEADING in text
    assert (
        '- kind=github scope=header context="Jane Doe" url=https://github.com/jane'
        in text
    )
    assert (
        "- kind=github scope=entry "
        'context="Telemetry pipeline" url=https://github.com/jane/telemetry' in text
    )


def _document_with_entry(title: str) -> dict[str, Any]:
    return {
        "schemaVersion": 2,
        "header": {"name": "Jane Doe", "contacts": []},
        "sections": [
            {
                "key": "projects",
                "heading": "Projects",
                "kind": "entries",
                "entries": [{"title": title, "links": []}],
            }
        ],
    }


def _markdown(*rows: tuple[str, str, str, str]) -> str:
    return format_links_block(
        [
            ExtractedLink(
                url=url,
                kind=kind,
                context=context,
                page=0,
                top=10.0 if scope == "header" else 500.0,
                page_height=842.0,
            )
            for kind, scope, context, url in rows
        ]
    )


def test_a_dropped_header_link_is_restored_as_an_icon_only_contact() -> None:
    parsed = _document_with_entry("Telemetry pipeline")
    markdown = _markdown(("github", "header", "Jane Doe", "https://github.com/jane"))

    restored = restore_links_from_markdown(parsed, markdown)

    assert restored["header"]["contacts"] == [
        {"kind": "github", "label": "", "value": "", "url": "https://github.com/jane"}
    ]


def test_a_link_the_model_already_placed_is_not_duplicated() -> None:
    parsed = _document_with_entry("Telemetry pipeline")
    parsed["header"]["contacts"] = [
        {
            "kind": "github",
            "label": "jane",
            "value": "github.com/jane",
            "url": "https://github.com/jane",
        }
    ]
    markdown = _markdown(("github", "header", "Jane Doe", "https://github.com/jane"))

    restored = restore_links_from_markdown(parsed, markdown)

    assert len(restored["header"]["contacts"]) == 1


def test_a_contact_read_without_its_url_is_completed_not_duplicated() -> None:
    """The anchor text is in the text stream, the url only in the annotation:
    the model emits the value and we supply the href."""
    parsed = _document_with_entry("Telemetry pipeline")
    parsed["header"]["contacts"] = [
        {"kind": "email", "label": "", "value": "jane@example.com", "url": ""}
    ]
    markdown = _markdown(("email", "header", "jane@example.com", "mailto:jane@example.com"))

    restored = restore_links_from_markdown(parsed, markdown)

    assert restored["header"]["contacts"] == [
        {
            "kind": "email",
            "label": "",
            "value": "jane@example.com",
            "url": "mailto:jane@example.com",
        }
    ]


def test_an_entry_link_lands_on_the_entry_its_context_names() -> None:
    parsed = _document_with_entry("Telemetry pipeline")
    parsed["sections"][0]["entries"].insert(0, {"title": "Other work", "links": []})
    markdown = _markdown(
        ("github", "entry", "Telemetry pipeline", "https://github.com/jane/telemetry")
    )

    restored = restore_links_from_markdown(parsed, markdown)

    entries = restored["sections"][0]["entries"]
    assert entries[0]["links"] == []
    assert entries[1]["links"] == [
        {"kind": "github", "url": "https://github.com/jane/telemetry"}
    ]


def test_an_entry_link_matching_no_entry_is_dropped_not_guessed() -> None:
    parsed = _document_with_entry("Telemetry pipeline")
    markdown = _markdown(
        ("github", "entry", "Something else entirely", "https://github.com/jane/other")
    )

    restored = restore_links_from_markdown(parsed, markdown)

    assert restored["sections"][0]["entries"][0]["links"] == []
    assert restored["header"]["contacts"] == []


def test_a_quote_in_the_context_does_not_break_the_block() -> None:
    """The block is machine-parsed, so a quoted anchor text must not end the
    context field early."""
    parsed = _document_with_entry('The "Telemetry" pipeline')
    markdown = _markdown(
        ("github", "entry", 'The "Telemetry" pipeline', "https://github.com/jane/tp")
    )

    restored = restore_links_from_markdown(parsed, markdown)

    assert restored["sections"][0]["entries"][0]["links"] == [
        {"kind": "github", "url": "https://github.com/jane/tp"}
    ]


def test_a_mail_link_on_an_entry_uses_a_kind_the_schema_allows() -> None:
    """``EntryLink.kind`` has no email member; an unusable kind would make the
    whole parse fail schema validation."""
    parsed = _document_with_entry("Telemetry pipeline")
    markdown = _markdown(
        ("email", "entry", "Telemetry pipeline", "mailto:team@example.com")
    )

    restored = restore_links_from_markdown(parsed, markdown)

    assert restored["sections"][0]["entries"][0]["links"] == [
        {"kind": "other", "url": "mailto:team@example.com"}
    ]
    assert ResumeDocument.model_validate(restored)
