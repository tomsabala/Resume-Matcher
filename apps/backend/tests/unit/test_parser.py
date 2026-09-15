"""Unit tests for pure parsing helpers in app.services.parser.

The LLM frequently drops months when parsing resume dates ("Jun 2020 - Aug 2021"
→ "2020 - 2021"). restore_dates_from_markdown() patches that back from the raw
markdown: the field is ``period`` on each entry of every ``entries`` section,
and an entry is matched to a markdown date by its ``(title, subtitle)``
identity, so the same year range in two sections still resolves correctly.

has_meaningful_resume_content() guards the other end of the parse: every field
of ``ResumeDocument`` defaults to empty, so an all-defaults response validates
and would otherwise be stored as a "parsed" resume.
"""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.services.parser import (
    DocumentValidationError,
    _extract_markdown_dates,
    _extract_tex_source,
    has_meaningful_resume_content,
    parse_resume_to_json,
    restore_dates_from_markdown,
)


def _entry(**fields: Any) -> dict[str, Any]:
    return {"id": fields.pop("id", "e-1"), **fields}


def _section(key: str, kind: str, **content: Any) -> dict[str, Any]:
    return {
        "id": f"s-{key}",
        "key": key,
        "heading": key.title(),
        "kind": kind,
        **content,
    }


def _document(*sections: dict[str, Any], **header: Any) -> dict[str, Any]:
    document: dict[str, Any] = {"schemaVersion": 2, "sections": list(sections)}
    if header:
        document["header"] = header
    return document


def _periods(document: dict[str, Any], key: str) -> list[str]:
    section = next(s for s in document["sections"] if s["key"] == key)
    return [entry.get("period") for entry in section["entries"]]


class TestExtractMarkdownDates:
    def test_finds_full_range(self):
        assert _extract_markdown_dates("Worked Jun 2020 - Aug 2021 there") == ["Jun 2020 - Aug 2021"]

    def test_finds_present_range(self):
        assert _extract_markdown_dates("May 2021 - Present") == ["May 2021 - Present"]

    def test_finds_single_date(self):
        assert _extract_markdown_dates("Graduated Jun 2023") == ["Jun 2023"]

    def test_ignores_year_only(self):
        # Year-only "2020 - 2021" has no month token → not captured.
        assert _extract_markdown_dates("2020 - 2021") == []


class TestRestoreDatesFromMarkdown:
    def test_restores_months_in_an_entry_period(self):
        parsed = _document(
            _section(
                "experience",
                "entries",
                entries=[_entry(title="Dev", subtitle="Acme Corp", period="2020 - 2021")],
            )
        )
        markdown = "Dev, Acme Corp, Jun 2020 - Aug 2021, built things"
        result = restore_dates_from_markdown(parsed, markdown)
        assert _periods(result, "experience") == ["Jun 2020 - Aug 2021"]

    def test_restores_single_date(self):
        parsed = _document(
            _section(
                "education",
                "entries",
                entries=[_entry(title="MIT", subtitle="B.S. Computer Science", period="2023")],
            )
        )
        markdown = "MIT — B.S. Computer Science, Jun 2023"
        result = restore_dates_from_markdown(parsed, markdown)
        assert _periods(result, "education") == ["Jun 2023"]

    def test_leaves_periods_that_already_have_months(self):
        parsed = _document(
            _section(
                "experience",
                "entries",
                entries=[_entry(title="Dev", subtitle="Acme Corp", period="Jan 2020 - Mar 2021")],
            )
        )
        # Same years, different months → must NOT be overwritten.
        result = restore_dates_from_markdown(parsed, "Dev, Acme Corp, Jun 2020 - Aug 2021")
        assert _periods(result, "experience") == ["Jan 2020 - Mar 2021"]

    def test_no_markdown_dates_is_noop(self):
        parsed = _document(
            _section("experience", "entries", entries=[_entry(period="2020 - 2021")])
        )
        result = restore_dates_from_markdown(parsed, "no dates here at all")
        assert _periods(result, "experience") == ["2020 - 2021"]

    def test_no_matching_year_key_is_noop(self):
        parsed = _document(
            _section("experience", "entries", entries=[_entry(period="2019 - 2020")])
        )
        # Different years → no candidate to borrow months from.
        result = restore_dates_from_markdown(parsed, "Jun 2021 - Aug 2022")
        assert _periods(result, "experience") == ["2019 - 2020"]

    def test_restores_in_a_user_authored_entries_section(self):
        """Nothing privileges the built-in keys: any ``entries`` section works."""
        parsed = _document(
            _section(
                "volunteering",
                "entries",
                entries=[_entry(title="Mentor", subtitle="Code Club", period="2019")],
            )
        )
        markdown = "Mentor, Code Club — Feb 2019 - Nov 2019"
        result = restore_dates_from_markdown(parsed, markdown)
        assert _periods(result, "volunteering") == ["Feb 2019 - Nov 2019"]

    def test_identity_selects_between_equal_year_ranges_across_sections(self):
        """Two entries share a year key; (title, subtitle) picks the right date."""
        parsed = _document(
            _section(
                "experience",
                "entries",
                entries=[
                    _entry(
                        id="e-acme",
                        title="Senior Engineer",
                        subtitle="Acme Corp",
                        period="2020 - 2021",
                    )
                ],
            ),
            _section(
                "volunteering",
                "entries",
                entries=[
                    _entry(
                        id="e-club",
                        title="Mentor",
                        subtitle="Code Club",
                        period="2020 - 2021",
                    )
                ],
            ),
        )
        markdown = (
            "Senior Engineer, Acme Corp — Jan 2020 - Mar 2021\n"
            "Mentor, Code Club — Jun 2020 - Aug 2021\n"
        )
        result = restore_dates_from_markdown(parsed, markdown)
        assert _periods(result, "experience") == ["Jan 2020 - Mar 2021"]
        assert _periods(result, "volunteering") == ["Jun 2020 - Aug 2021"]

    def test_tolerates_a_document_without_sections(self):
        # Must not raise on a minimal/odd structure.
        parsed = {"schemaVersion": 2, "header": {"name": "X"}}
        assert restore_dates_from_markdown(parsed, "Jun 2020 - Aug 2021") == parsed

    def test_skips_non_dict_entries(self):
        """Pre-validation LLM output may hold junk beside real entries."""
        parsed = _document(
            _section(
                "experience",
                "entries",
                entries=[
                    "not a dict",
                    _entry(title="Dev", subtitle="Acme Corp", period="2020 - 2021"),
                ],
            )
        )
        result = restore_dates_from_markdown(
            parsed, "Dev, Acme Corp, Jun 2020 - Aug 2021"
        )
        assert result["sections"][0]["entries"][1]["period"] == "Jun 2020 - Aug 2021"


class TestMeaningfulResumeContent:
    def test_rejects_an_empty_payload(self):
        assert has_meaningful_resume_content({}) is False

    def test_rejects_a_document_whose_sections_are_all_empty(self):
        assert has_meaningful_resume_content(
            _document(
                _section("summary", "text", text="   "),
                _section("experience", "entries", entries=[]),
                _section("stack", "tags", tags=["", " "]),
                _section("skills", "groups", groups=[{"label": "Technical", "values": []}]),
            )
        ) is False

    def test_accepts_a_header_with_only_a_name(self):
        assert has_meaningful_resume_content(_document(name="Jane Doe")) is True

    @pytest.mark.parametrize(
        "section",
        [
            pytest.param(_section("summary", "text", text="Backend engineer."), id="text"),
            pytest.param(
                _section(
                    "experience",
                    "entries",
                    entries=[_entry(title="Engineer")],
                ),
                id="entries",
            ),
            pytest.param(_section("stack", "tags", tags=["Python"]), id="tags"),
            pytest.param(
                _section(
                    "skills",
                    "groups",
                    groups=[{"label": "Technical", "values": ["Python"]}],
                ),
                id="groups",
            ),
        ],
    )
    def test_accepts_content_in_every_section_kind(self, section: dict[str, Any]):
        assert has_meaningful_resume_content(_document(section)) is True

    def test_rejects_a_section_carrying_only_structural_fields(self):
        """A section is scaffolding: id/key/kind/heading are never content."""
        assert has_meaningful_resume_content(
            _document(
                {
                    "id": "s-publications",
                    "key": "publications",
                    "heading": "Publications",
                    "headingI18nKey": "resume.sections.publications",
                    "kind": "text",
                    "visible": True,
                    "column": "side",
                }
            )
        ) is False

    def test_rejects_entries_that_only_carry_structural_fields(self):
        assert has_meaningful_resume_content(
            _document(
                _section(
                    "experience",
                    "entries",
                    entries=[
                        {
                            "id": "e-1",
                            "title": "",
                            "subtitle": "",
                            "meta": "",
                            "period": "",
                            "links": [],
                            "summary": "",
                            "bullets": [{"text": "  ", "style": "bullet"}],
                        }
                    ],
                )
            )
        ) is False


class TestParseResumeToJson:
    @pytest.mark.asyncio
    @patch("app.services.parser.complete_json", new_callable=AsyncMock)
    async def test_parse_rejects_empty_llm_json(self, mock_complete_json):
        mock_complete_json.return_value = {}
        with pytest.raises(ValueError, match="empty structured resume"):
            await parse_resume_to_json("Jane Doe")

    @pytest.mark.asyncio
    @patch("app.services.parser.complete_json", new_callable=AsyncMock)
    async def test_parse_rejects_default_only_llm_entries(self, mock_complete_json):
        mock_complete_json.return_value = _document(
            _section("experience", "entries", entries=[{}])
        )
        with pytest.raises(ValueError, match="empty structured resume"):
            await parse_resume_to_json("Jane Doe")


class TestExtractTexSource:
    """A ``.tex`` upload is read as source: it keeps the links, bold and
    structure a PDF's text stream has already lost. The engine is never run."""

    def test_the_preamble_never_reaches_the_prompt(self):
        source = (
            "\\documentclass[a4paper,10pt]{article}\n"
            "\\usepackage{hyperref}\n"
            "\\begin{document}\n"
            "\\section{Experience}\n"
            "\\end{document}\n"
        )

        text = _extract_tex_source(source.encode())

        assert text == "\\section{Experience}"

    def test_comments_are_stripped_but_escaped_percents_survive(self):
        source = (
            "\\begin{document}\n"
            "% a note to self\n"
            "\\item Cut latency by 50\\% % measured\n"
            "\\end{document}\n"
        )

        text = _extract_tex_source(source.encode())

        assert "a note to self" not in text
        assert "measured" not in text
        assert "50\\%" in text

    def test_a_fragment_without_a_document_environment_passes_through(self):
        """People paste a single section, not a compilable file."""
        text = _extract_tex_source(b"\\section{Projects}\n\\item Built a thing\n")

        assert text == "\\section{Projects}\n\\item Built a thing"

    def test_binary_bytes_renamed_tex_are_rejected(self):
        with pytest.raises(DocumentValidationError, match="PDF, DOC, DOCX, or TEX"):
            _extract_tex_source(b"%PDF-1.4\n\x80\xff binary")
