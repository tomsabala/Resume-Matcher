"""LLM-facing descriptions of the resume document contract (schema version 2).

Prompts must never hardcode which sections a resume has: headings, order and
shapes are pure data. These helpers turn a concrete ``ResumeDocument`` into the
two blocks every AI path needs — the JSON shape the model must produce, and the
exact set of paths it is allowed to change.
"""

from __future__ import annotations

from app.prompts.templates import RESUME_SCHEMA_EXAMPLE
from app.schemas.document import ResumeDocument, Section, SectionKind

# The generic shape, independent of any particular document.
_SHAPE = """RESUME DOCUMENT SHAPE (schemaVersion 2):
- Top level: "schemaVersion" (always 2), "header", "sections".
- "header": "name", "headline", "contacts". Each contact is "kind", "label",
  "value", "url"; contact "kind" is one of email, phone, website, github,
  linkedin, location, other. The header is NOT a section.
- "sections" is an ORDERED list. Display order IS list order; there is no order
  field and no section metadata anywhere else.
- Every section has: "key", "heading", "kind", "visible", "column", plus the one
  content field its "kind" selects.
  - "key": lowercase snake_case slug, unique in the document; the stable
    identifier used in change paths. Never translate it.
  - "heading": the section's display title, free text in the resume's language.
  - "kind": one of text, entries, tags, groups.
  - "column": main or side (two-column templates partition on this).
  - "visible": true unless the section is deliberately hidden from the PDF.
- kind "text": "text" holds one prose block.
- kind "entries": "entries" holds a list of rows, each with "title", "subtitle",
  "meta", "period", "links", "summary", "bullets".
  - "title"/"subtitle" are generic: job title/company for experience,
    institution/degree for education, project/role for projects, role/unit for
    military service.
  - "meta" is location or other short free metadata.
  - "period" is free text copied verbatim and never reparsed or reformatted.
  - "links" is a list of "kind" (github, website, linkedin, other) plus "url".
  - "summary" is the optional paragraph above the bullets.
  - "bullets" is a list of "text" plus "style"; style is "bullet" for a normal
    bullet row and "plain" for a row that renders without a marker. Style is a
    property of the bullet, never a separate parallel array.
- kind "tags": "tags" holds a flat list of short strings.
- kind "groups": "groups" holds a list of "label" plus "values" (short strings).
- The content fields a section's kind does not use stay empty ("" or [])."""

_CONTENT_FIELD_BY_KIND: dict[SectionKind, str] = {
    SectionKind.TEXT: "text",
    SectionKind.ENTRIES: "entries",
    SectionKind.TAGS: "tags",
    SectionKind.GROUPS: "groups",
}

_OFF_LIMITS = """OFF LIMITS - never target these:
- anything under "header" (name, headline, contacts)
- any entry's "title", "subtitle", "meta", "period" or "links"
- any section's "key", "heading", "kind", "visible" or "column"
- adding or removing sections, entries, bullets, groups or tags is not a path
  change; only the paths listed above may be targeted"""


def _section_line(section: Section) -> str:
    """One enumerated section: its key, heading and kind."""
    return (
        f'- key "{section.key}" | heading "{section.heading}" '
        f"| kind {section.kind.value}"
        f"{'' if section.visible else ' | hidden from the PDF'}"
    )


def describe_document_schema(doc: ResumeDocument | None) -> str:
    """Describe the document shape the model must produce.

    ``doc`` enumerates the sections that actually exist so the model targets the
    real document. Pass ``None`` on the initial parsing path, where there is no
    prior document: the generic shape is then followed by a concrete example.
    """
    if doc is None:
        return (
            f"{_SHAPE}\n\n"
            "EXAMPLE DOCUMENT (shape reference only - the sections a real "
            "resume has are whatever its source contains):\n"
            f"{RESUME_SCHEMA_EXAMPLE}"
        )
    if not doc.sections:
        return (
            f"{_SHAPE}\n\n"
            "SECTIONS IN THIS DOCUMENT: none yet. Add sections as the content "
            "requires, choosing each one's kind from its content."
        )
    lines = "\n".join(_section_line(section) for section in doc.sections)
    return (
        f"{_SHAPE}\n\n"
        "SECTIONS IN THIS DOCUMENT (in order - keep these keys and kinds "
        f"exactly):\n{lines}"
    )


def _paths_for_section(section: Section) -> list[str]:
    """The editable path patterns a single section exposes, from its kind."""
    key, heading = section.key, section.heading
    if section.kind is SectionKind.TEXT:
        return [f'- "sections.{key}.text" - the "{heading}" prose block']
    if section.kind is SectionKind.ENTRIES:
        return [
            f'- "sections.{key}.entries[i].summary" - the paragraph above entry '
            f'i\'s bullets in "{heading}"',
            f'- "sections.{key}.entries[i].bullets[j].text" - one bullet in '
            f'"{heading}" (i = entry index, j = bullet index)',
        ]
    if section.kind is SectionKind.TAGS:
        return [
            f'- "sections.{key}.tags" - the "{heading}" list of short values '
            "(reorder, or add one verified value)"
        ]
    return [
        f'- "sections.{key}.groups[i].values" - the values of group i in '
        f'"{heading}" (reorder, or add one verified value)'
    ]


def describe_editable_paths(doc: ResumeDocument) -> str:
    """List the exact paths the AI may target, per section, from its kind."""
    lines: list[str] = []
    for section in doc.sections:
        lines.extend(_paths_for_section(section))
    if not lines:
        return f"PATHS you can target: none - this resume has no sections.\n\n{_OFF_LIMITS}"
    body = "\n".join(lines)
    return f"PATHS you can target:\n{body}\n\n{_OFF_LIMITS}"
