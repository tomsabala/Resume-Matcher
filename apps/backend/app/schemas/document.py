"""The resume document contract (schema version 2).

Sections, their headings, their order and their shapes are **data**, not code.
Nothing in the application enumerates resume sections: consumers switch on
:class:`SectionKind` and iterate ``document.sections``.

Three deliberate departures from the v1 ``ResumeData`` model, each removing a
bug class:

1. :attr:`Entry.summary` *and* :attr:`Entry.bullets` coexist. V1 had only
   ``description: list[str]``, so a paragraph plus bullets on one entry was
   unrepresentable.
2. ``bullets: list[Bullet]`` replaces the parallel ``description`` /
   ``descriptionStyles`` arrays, whose index alignment had to be enforced in
   four places and could silently desync.
3. Order is list order. ``SectionMeta.order`` is gone, so there is no
   reindexing to get wrong.

``extra="forbid"`` is the point of the whole exercise: v1 models inherited
Pydantic's default ``extra='ignore'``, so every write silently discarded
sections the code did not know about.
"""

from __future__ import annotations

import logging
import re
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 2

# Keys the v1 projection assigns to the six built-in sections. They are stable
# identifiers used in change paths, not display text.
LEGACY_SECTION_KEYS = ("summary", "experience", "education", "projects", "skills")

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def new_id() -> str:
    """Fresh stable identifier for a section, entry or contact."""
    return uuid4().hex


def slugify_key(value: str, *, taken: set[str] | None = None) -> str:
    """Slug for a section key, unique within ``taken`` when supplied."""
    base = _SLUG_RE.sub("_", value.strip().lower()).strip("_") or "section"
    if taken is None or base not in taken:
        return base
    suffix = 2
    while f"{base}_{suffix}" in taken:
        suffix += 1
    return f"{base}_{suffix}"


class SectionKind(str, Enum):
    """The shape of a section's content.

    Every renderer, editor, AI allowlist and diff rule dispatches on this and
    nothing else — adding a section to a resume never requires code.
    """

    TEXT = "text"  # one prose block (summary / about me)
    ENTRIES = "entries"  # list[Entry] (experience, education, military service…)
    TAGS = "tags"  # flat list[str] (spoken languages)
    GROUPS = "groups"  # list[TagGroup] (labelled skill groups)


class Bullet(BaseModel):
    """One bullet (or unbulleted paragraph row) under an entry."""

    model_config = ConfigDict(extra="forbid")

    text: str = ""
    style: Literal["bullet", "plain"] = "bullet"


class EntryLink(BaseModel):
    """An external link attached to an entry (project repo, live site…)."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["github", "website", "linkedin", "other"] = "other"
    url: str = ""


class Entry(BaseModel):
    """One row of an ``ENTRIES`` section.

    The field names are deliberately generic: ``title``/``subtitle`` mean job
    title/company for experience, institution/degree for education, project
    name/role for projects, and role/unit for military service.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    title: str = ""
    subtitle: str = ""
    meta: str = ""  # location or other free metadata
    period: str = ""  # "2023 -- May 2026"; stored verbatim, never parsed
    links: list[EntryLink] = Field(default_factory=list)
    summary: str = ""  # the paragraph above the bullets
    bullets: list[Bullet] = Field(default_factory=list)


class TagGroup(BaseModel):
    """A labelled list of short values ("Cloud / Data: AWS, GCP, …")."""

    model_config = ConfigDict(extra="forbid")

    label: str = ""
    values: list[str] = Field(default_factory=list)


class Section(BaseModel):
    """One resume section. ``kind`` decides which content field is used."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    key: str  # slug, unique per document, used in change paths
    heading: str  # user-authored headline, free text
    # Set only on sections projected from v1 built-ins. The UI renders the
    # translation when the heading still equals its English default, so
    # localisation keeps working without ever turning a user heading into a
    # translation key (which would break `Messages = typeof en`).
    headingI18nKey: str | None = None
    kind: SectionKind
    visible: bool = True
    # Two-column templates partition on this instead of hardcoding which
    # built-in sections may appear in the sidebar.
    column: Literal["main", "side"] = "main"
    text: str = ""  # kind == TEXT
    entries: list[Entry] = Field(default_factory=list)  # kind == ENTRIES
    tags: list[str] = Field(default_factory=list)  # kind == TAGS
    groups: list[TagGroup] = Field(default_factory=list)  # kind == GROUPS


class Contact(BaseModel):
    """One header contact. An empty ``label`` renders icon-only."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    kind: Literal[
        "email", "phone", "website", "github", "linkedin", "location", "other"
    ]
    label: str = ""
    value: str = ""
    url: str = ""  # empty means derive from kind + value


class Header(BaseModel):
    """Name, headline and contacts. Not a section: every template renders it
    outside the section loop."""

    model_config = ConfigDict(extra="forbid")

    name: str = ""
    headline: str = ""
    contacts: list[Contact] = Field(default_factory=list)


class ResumeDocument(BaseModel):
    """A complete resume."""

    model_config = ConfigDict(extra="forbid")

    schemaVersion: Literal[2] = 2
    header: Header = Field(default_factory=Header)
    sections: list[Section] = Field(default_factory=list)

    def section(self, key: str) -> Section | None:
        """Look up a section by key."""
        return next((s for s in self.sections if s.key == key), None)


# ---------------------------------------------------------------------------
# v1 → v2 projection
# ---------------------------------------------------------------------------

# Display defaults and translation keys for the six built-in v1 sections.
_LEGACY_HEADINGS: dict[str, tuple[str, str]] = {
    "summary": ("Summary", "resume.sections.summary"),
    "experience": ("Experience", "resume.sections.experience"),
    "education": ("Education", "resume.sections.education"),
    "projects": ("Projects", "resume.sections.projects"),
    "skills": ("Skills & Awards", "resume.sections.skills"),
}

# v1 sectionMeta ids → v2 section keys.
_LEGACY_KEY_BY_META_ID: dict[str, str] = {
    "summary": "summary",
    "workExperience": "experience",
    "education": "education",
    "personalProjects": "projects",
    "additional": "skills",
}

# v1 additional.* buckets → labelled tag groups, in display order.
_ADDITIONAL_GROUPS: tuple[tuple[str, str], ...] = (
    ("technicalSkills", "Technical Skills"),
    ("languages", "Languages"),
    ("certificationsTraining", "Certifications & Training"),
    ("awards", "Awards"),
)

_CONTACT_ORDER: tuple[tuple[str, str], ...] = (
    ("email", "email"),
    ("phone", "phone"),
    ("location", "location"),
    ("website", "website"),
    ("linkedin", "linkedin"),
    ("github", "github"),
)

# Icon-only in the header, matching the reference LaTeX formatting rules.
_ICON_ONLY_CONTACTS = frozenset({"github", "linkedin"})

_LEGACY_KIND_BY_SECTION_TYPE: dict[str, SectionKind] = {
    "text": SectionKind.TEXT,
    "itemList": SectionKind.ENTRIES,
    "stringList": SectionKind.TAGS,
}


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _bullets(description: Any, styles: Any) -> list[Bullet]:
    """Zip v1's parallel ``description``/``descriptionStyles`` arrays.

    A short (or absent) style array pads with ``"bullet"`` — exactly what the
    v1 aligner did, except the pairing can no longer drift afterwards.
    """
    rows = description if isinstance(description, list) else []
    style_rows = styles if isinstance(styles, list) else []
    bullets: list[Bullet] = []
    for index, row in enumerate(rows):
        text = _text(row)
        if not text:
            continue
        style = style_rows[index] if index < len(style_rows) else "bullet"
        bullets.append(Bullet(text=text, style="plain" if style == "plain" else "bullet"))
    return bullets


def _entry_links(item: dict[str, Any]) -> list[EntryLink]:
    links: list[EntryLink] = []
    for kind in ("github", "website"):
        url = _text(item.get(kind))
        if url:
            links.append(EntryLink(kind=kind, url=url))  # type: ignore[arg-type]
    return links


def _header_from_personal_info(raw: dict[str, Any]) -> Header:
    info = raw.get("personalInfo")
    info = info if isinstance(info, dict) else {}
    contacts: list[Contact] = []
    for field, kind in _CONTACT_ORDER:
        value = _text(info.get(field))
        if not value:
            continue
        contacts.append(
            Contact(
                kind=kind,  # type: ignore[arg-type]
                label="" if kind in _ICON_ONLY_CONTACTS else value,
                value=value,
            )
        )
    return Header(
        name=_text(info.get("name")),
        headline=_text(info.get("title")),
        contacts=contacts,
    )


def _summary_section(raw: dict[str, Any]) -> Section | None:
    text = _text(raw.get("summary"))
    if not text:
        return None
    heading, i18n_key = _LEGACY_HEADINGS["summary"]
    return Section(
        key="summary",
        heading=heading,
        headingI18nKey=i18n_key,
        kind=SectionKind.TEXT,
        text=text,
    )


def _experience_section(raw: dict[str, Any]) -> Section | None:
    rows = raw.get("workExperience")
    if not isinstance(rows, list) or not rows:
        return None
    heading, i18n_key = _LEGACY_HEADINGS["experience"]
    return Section(
        key="experience",
        heading=heading,
        headingI18nKey=i18n_key,
        kind=SectionKind.ENTRIES,
        entries=[
            Entry(
                title=_text(item.get("title")),
                subtitle=_text(item.get("company")),
                meta=_text(item.get("location")),
                period=_text(item.get("years")),
                bullets=_bullets(item.get("description"), item.get("descriptionStyles")),
            )
            for item in rows
            if isinstance(item, dict)
        ],
    )


def _education_section(raw: dict[str, Any]) -> Section | None:
    rows = raw.get("education")
    if not isinstance(rows, list) or not rows:
        return None
    heading, i18n_key = _LEGACY_HEADINGS["education"]
    return Section(
        key="education",
        heading=heading,
        headingI18nKey=i18n_key,
        kind=SectionKind.ENTRIES,
        entries=[
            Entry(
                title=_text(item.get("institution")),
                subtitle=_text(item.get("degree")),
                period=_text(item.get("years")),
                # v1 education carried a scalar description, not bullet rows.
                summary=_text(item.get("description")),
            )
            for item in rows
            if isinstance(item, dict)
        ],
    )


def _projects_section(raw: dict[str, Any]) -> Section | None:
    rows = raw.get("personalProjects")
    if not isinstance(rows, list) or not rows:
        return None
    heading, i18n_key = _LEGACY_HEADINGS["projects"]
    return Section(
        key="projects",
        heading=heading,
        headingI18nKey=i18n_key,
        kind=SectionKind.ENTRIES,
        entries=[
            Entry(
                title=_text(item.get("name")),
                subtitle=_text(item.get("role")),
                period=_text(item.get("years")),
                links=_entry_links(item),
                bullets=_bullets(item.get("description"), item.get("descriptionStyles")),
            )
            for item in rows
            if isinstance(item, dict)
        ],
    )


def _skills_section(raw: dict[str, Any]) -> Section | None:
    additional = raw.get("additional")
    additional = additional if isinstance(additional, dict) else {}
    groups = [
        TagGroup(label=label, values=[_text(v) for v in additional[field] if _text(v)])
        for field, label in _ADDITIONAL_GROUPS
        if isinstance(additional.get(field), list) and additional[field]
    ]
    groups = [group for group in groups if group.values]
    if not groups:
        return None
    heading, i18n_key = _LEGACY_HEADINGS["skills"]
    return Section(
        key="skills",
        heading=heading,
        headingI18nKey=i18n_key,
        kind=SectionKind.GROUPS,
        groups=groups,
    )


def _custom_section(
    legacy_key: str, key: str, payload: dict[str, Any]
) -> Section | None:
    kind = _LEGACY_KIND_BY_SECTION_TYPE.get(str(payload.get("sectionType")))
    if kind is None:
        return None
    # Until sectionMeta supplies a display name, the authored key *is* the
    # best heading available — v1 users typed it.
    section = Section(key=key, heading=legacy_key, kind=kind)
    if kind is SectionKind.TEXT:
        section.text = _text(payload.get("text"))
    elif kind is SectionKind.TAGS:
        section.tags = [_text(v) for v in (payload.get("strings") or []) if _text(v)]
    else:
        section.entries = [
            Entry(
                title=_text(item.get("title")),
                subtitle=_text(item.get("subtitle")),
                meta=_text(item.get("location")),
                period=_text(item.get("years")),
                bullets=_bullets(item.get("description"), item.get("descriptionStyles")),
            )
            for item in (payload.get("items") or [])
            if isinstance(item, dict)
        ]
    return section


def _apply_section_meta(
    sections: list[Section], raw: dict[str, Any], aliases: dict[str, str]
) -> list[Section]:
    """Apply v1 ``sectionMeta`` headings, visibility and order.

    ``aliases`` maps a v1 meta id (built-in id, or a custom section's authored
    key) to the projected v2 key.

    Meta rows whose key matches no projected section are dropped: v1 injected
    ``DEFAULT_SECTION_META`` lazily and independently of the data, so a meta
    row routinely referenced a section with nothing in it. Creating an empty
    section for it would put a blank heading on the user's PDF.
    """
    meta_rows = raw.get("sectionMeta")
    if not isinstance(meta_rows, list) or not meta_rows:
        return sections

    by_key = {section.key: section for section in sections}
    ordered: list[tuple[int, Section]] = []
    seen: set[str] = set()
    for index, meta in enumerate(meta_rows):
        if not isinstance(meta, dict):
            continue
        meta_id = str(meta.get("id") or meta.get("key") or "")
        key = aliases.get(meta_id, meta_id)
        section = by_key.get(key)
        if section is None or key in seen:
            continue
        seen.add(key)
        display_name = _text(meta.get("displayName"))
        if display_name:
            section.heading = display_name
        if meta.get("isVisible") is False:
            section.visible = False
        order = meta.get("order")
        ordered.append((order if isinstance(order, int) else index, section))

    remaining = [section for section in sections if section.key not in seen]
    ordered.sort(key=lambda pair: pair[0])
    return [section for _, section in ordered] + remaining


def migrate_document(raw: Any) -> ResumeDocument:
    """Project stored resume content onto the v2 document.

    Already-v2 payloads are validated and returned. Anything else is read as a
    v1 ``ResumeData`` dict; unknown/garbage input yields an empty document
    rather than raising, because this runs on every read path.
    """
    if isinstance(raw, ResumeDocument):
        return raw
    if not isinstance(raw, dict):
        return ResumeDocument()
    if raw.get("schemaVersion") == SCHEMA_VERSION:
        return ResumeDocument.model_validate(raw)

    sections: list[Section] = []
    for build in (
        _summary_section,
        _experience_section,
        _education_section,
        _projects_section,
        _skills_section,
    ):
        section = build(raw)
        if section is not None:
            sections.append(section)

    aliases = dict(_LEGACY_KEY_BY_META_ID)
    custom = raw.get("customSections")
    if isinstance(custom, dict):
        taken = {section.key for section in sections}
        for legacy_key, payload in custom.items():
            if not isinstance(payload, dict):
                continue
            key = slugify_key(str(legacy_key), taken=taken)
            section = _custom_section(str(legacy_key), key, payload)
            if section is None:
                logger.warning(
                    "Dropping custom section %r with unknown type %r",
                    legacy_key,
                    payload.get("sectionType"),
                )
                continue
            taken.add(section.key)
            aliases[str(legacy_key)] = section.key
            sections.append(section)

    return ResumeDocument(
        header=_header_from_personal_info(raw),
        sections=_apply_section_meta(sections, raw, aliases),
    )
