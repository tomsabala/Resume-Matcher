"""Generic traversal of a v2 resume document.

Every consumer that used to enumerate the six built-in sections walks the
document through these helpers instead. Nothing here mentions a section name.

Functions come in two flavours:

* model-level (``ResumeDocument``) — preferred, used by services;
* dict-level (``sections_of``, ``entries_of``…) — for the AI apply path, which
  mutates the JSON payload in place before re-validating it.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from app.schemas.document import Entry, ResumeDocument, Section, SectionKind

__all__ = [
    "iter_sections",
    "iter_entries",
    "entry_paths",
    "section_path",
    "skill_list_paths",
    "skill_values",
    "document_text_fragments",
    "sections_of",
    "entries_of",
    "bullet_texts",
]


def iter_sections(
    document: ResumeDocument, kind: SectionKind | None = None
) -> Iterator[Section]:
    """Yield sections, optionally filtered to one kind."""
    for section in document.sections:
        if kind is None or section.kind is kind:
            yield section


def iter_entries(document: ResumeDocument) -> Iterator[tuple[Section, int, Entry]]:
    """Yield ``(section, index, entry)`` for every entry in the document."""
    for section in iter_sections(document, SectionKind.ENTRIES):
        for index, entry in enumerate(section.entries):
            yield section, index, entry


def section_path(section: Section) -> str:
    """Root change path of a section, e.g. ``sections.military_service``."""
    return f"sections.{section.key}"


def entry_paths(section: Section, index: int) -> dict[str, str]:
    """Change paths for one entry's editable fields."""
    base = f"{section_path(section)}.entries[{index}]"
    return {"summary": f"{base}.summary", "bullets": f"{base}.bullets"}


def skill_list_paths(document: ResumeDocument) -> set[str]:
    """Paths of every flat list of short values ("skills").

    Both ``GROUPS`` group values and ``TAGS`` lists qualify: the product's
    skill operations (add_skill, reorder, keyword coverage) target short
    labelled terms, and which section holds them is the user's choice.
    """
    paths: set[str] = set()
    for section in document.sections:
        if section.kind is SectionKind.TAGS:
            paths.add(f"{section_path(section)}.tags")
        elif section.kind is SectionKind.GROUPS:
            for index, _ in enumerate(section.groups):
                paths.add(f"{section_path(section)}.groups[{index}].values")
    return paths


def skill_values(document: ResumeDocument) -> list[str]:
    """Every short value across ``TAGS`` and ``GROUPS`` sections, in order."""
    values: list[str] = []
    for section in document.sections:
        if section.kind is SectionKind.TAGS:
            values.extend(section.tags)
        elif section.kind is SectionKind.GROUPS:
            for group in section.groups:
                values.extend(group.values)
    return values


def document_text_fragments(document: ResumeDocument) -> Iterator[str]:
    """Every user-authored string in the document body (header excluded).

    Used for "does this phrase already appear in the resume" checks, which
    must not be satisfied by structural keys or ids.
    """
    for section in document.sections:
        yield section.heading
        if section.kind is SectionKind.TEXT:
            yield section.text
        elif section.kind is SectionKind.ENTRIES:
            for entry in section.entries:
                yield from (entry.title, entry.subtitle, entry.meta, entry.period)
                yield entry.summary
                for bullet in entry.bullets:
                    yield bullet.text
        elif section.kind is SectionKind.TAGS:
            yield from section.tags
        else:
            for group in section.groups:
                yield group.label
                yield from group.values


# -- dict-level helpers (AI apply path mutates raw JSON) --------------------


def sections_of(payload: Any) -> list[dict[str, Any]]:
    """Section dicts of a raw document payload; ``[]`` when malformed."""
    if not isinstance(payload, dict):
        return []
    sections = payload.get("sections")
    if not isinstance(sections, list):
        return []
    return [section for section in sections if isinstance(section, dict)]


def entries_of(section: dict[str, Any]) -> list[dict[str, Any]]:
    """Entry dicts of a raw section payload."""
    entries = section.get("entries")
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, dict)]


def bullet_texts(entry: dict[str, Any]) -> list[str]:
    """Bullet texts of a raw entry payload."""
    bullets = entry.get("bullets")
    if not isinstance(bullets, list):
        return []
    return [
        str(bullet.get("text", ""))
        for bullet in bullets
        if isinstance(bullet, dict)
    ]
