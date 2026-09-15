"""Structural scorers for the eval harness.

These are **pure, deterministic** functions: given an original resume and a
tailored one, they check invariants that must hold regardless of the exact
wording the LLM produced. They never call an LLM, never touch the network, and
never read from disk — so they run for free in the normal test suite and form
the cheap first line of defence against "a prompt change broke something."

The invariants encoded here mirror the truthfulness / preservation rules the
tailoring pipeline is supposed to honour:

* every section that was populated must survive tailoring,
* the candidate's entry history may be re-worded but not fabricated,
* the JD's keywords should actually appear in the output,
* the result must still validate against ``ResumeDocument``,
* and the candidate's identity (the document ``header``) must be left untouched.

The document is dynamic: which sections exist is the user's choice, so nothing
here may hardcode a section name. Traversal is delegated to
``app.services.document_walk`` (the same helpers the product uses) and content
is judged per :class:`SectionKind`.

All functions take/return concrete types (backend rule: type hints on every
function). The LLM-as-judge layer lives separately in
``tests/evals/test_tailoring_eval.py``.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError

from app.schemas.document import (
    ResumeDocument,
    Section,
    SectionKind,
    migrate_document,
)
from app.services.document_walk import (
    document_text_fragments,
    iter_entries,
    iter_sections,
)
from app.services.parser import has_meaningful_resume_content

# Either a stored/API payload (v1 or v2 shaped) or an already-parsed document.
ResumeInput = dict[str, Any] | ResumeDocument

# Keep the eval implementation independent while covering Han, Kana, and Hangul.
_CJK_CHAR_CLASS = (
    r"[\u1100-\u11ff\u3040-\u30ff\u3130-\u318f\u31f0-\u31ff"
    r"\u3400-\u9fff\ua960-\ua97f\uac00-\ud7ff\uf900-\ufaff"
    r"\uff66-\uffdc\U0001b000-\U0001b16f\U00020000-\U0003ffff]"
)
_CJK_RE = re.compile(_CJK_CHAR_CLASS)


def _section_has_content(section: Section) -> bool:
    """Whether a section carries user-facing content in the field its kind uses.

    Structural fields (id, key, kind, heading, column) never count: a section
    that is only scaffolding is empty, and tailoring is free to leave it so.
    """
    if section.kind is SectionKind.TEXT:
        return bool(section.text.strip())
    if section.kind is SectionKind.ENTRIES:
        return any(
            entry.title.strip()
            or entry.subtitle.strip()
            or entry.summary.strip()
            or any(bullet.text.strip() for bullet in entry.bullets)
            for entry in section.entries
        )
    if section.kind is SectionKind.TAGS:
        return any(value.strip() for value in section.tags)
    return any(value.strip() for group in section.groups for value in group.values)


def _entry_labels(document: ResumeDocument) -> list[str]:
    """Identity label — ``"title — subtitle"`` — of every entry in the document.

    ``(title, subtitle)`` is the document's entry identity: job title/employer
    for experience, institution/degree for education, project name/role for
    projects. Tailoring rewrites bullets and summaries; it never authors a new
    identity.
    """
    labels: list[str] = []
    for _, _, entry in iter_entries(document):
        parts = [part for part in (entry.title.strip(), entry.subtitle.strip()) if part]
        if parts:
            labels.append(" — ".join(parts))
    return labels


def _identity_key(label: str) -> str:
    """Case- and whitespace-insensitive comparison key for an entry label."""
    return " ".join(label.split()).casefold()


def flatten_resume_text(data: ResumeInput) -> str:
    """Flatten an entire resume into one lowercased text blob.

    Used for case-insensitive keyword search across every field — header,
    summary, bullets, skills, custom sections, the lot.
    """
    document = migrate_document(data)
    header = document.header
    fragments: list[str] = [header.name, header.headline]
    for contact in header.contacts:
        fragments.extend((contact.label, contact.value, contact.url))
    fragments.extend(document_text_fragments(document))
    return " ".join(fragment for fragment in fragments if fragment).lower()


def sections_preserved(original: ResumeInput, tailored: ResumeInput) -> bool:
    """No populated section may vanish during tailoring.

    Every section of ``original`` that carried content must still exist in
    ``tailored`` under the same key and still carry content. Sections that were
    empty to begin with are ignored, and the check is identical for built-in
    and user-authored sections — the document has no privileged section names.

    Returns True when every originally-populated section survives, else False.
    """
    tailored_sections = {
        section.key: section for section in iter_sections(migrate_document(tailored))
    }
    for section in iter_sections(migrate_document(original)):
        if not _section_has_content(section):
            continue
        replacement = tailored_sections.get(section.key)
        if replacement is None or not _section_has_content(replacement):
            return False
    return True


def no_fabricated_entries(original: ResumeInput, tailored: ResumeInput) -> list[str]:
    """Detect entry identities that appear in ``tailored`` but not in ``original``.

    Tailoring may re-word bullets but must never invent an employer, school or
    project the candidate never had. Comparison is case-insensitive and
    whitespace-normalized.

    Returns the fabricated identity labels (in the casing they appear in
    ``tailored``). An empty list means the history is truthful.
    """
    original_keys = {
        _identity_key(label) for label in _entry_labels(migrate_document(original))
    }
    fabricated: list[str] = []
    seen: set[str] = set()
    for label in _entry_labels(migrate_document(tailored)):
        key = _identity_key(label)
        if key not in original_keys and key not in seen:
            fabricated.append(label)
            seen.add(key)
    return fabricated


def jd_keywords_present(tailored: ResumeInput, keywords: list[str]) -> float:
    """Fraction (0.0–1.0) of ``keywords`` that appear in the tailored resume.

    Matching is case-insensitive whole-term search over the flattened resume
    text. With an empty ``keywords`` list there is nothing to miss, so the
    score is 1.0.
    """
    if not keywords:
        return 1.0
    haystack = flatten_resume_text(tailored)

    def keyword_present(keyword: str) -> bool:
        normalized = keyword.strip().lower()
        if not normalized:
            return False
        if _CJK_RE.search(normalized):
            return normalized in haystack
        escaped = re.escape(normalized)
        return bool(
            re.search(
                rf"(?:(?<!\w)|(?<={_CJK_CHAR_CLASS}))"
                rf"{escaped}"
                rf"(?:(?!\w)|(?={_CJK_CHAR_CLASS}))",
                haystack,
            )
        )

    hits = sum(
        1
        for kw in keywords
        if keyword_present(kw)
    )
    return hits / len(keywords)


def is_valid_resume(data: ResumeInput) -> bool:
    """Require both valid schema and meaningful resume content.

    Validation is strict (``ResumeDocument`` forbids unknown fields), so a
    payload that is not a v2 document fails here rather than being silently
    projected onto an empty one.
    """
    try:
        document = ResumeDocument.model_validate(data)
    except ValidationError:
        return False
    return has_meaningful_resume_content(document)


def _header_identity(document: ResumeDocument) -> dict[str, Any]:
    """The identity text of a header, without structural ids."""
    header = document.header
    return {
        "name": header.name,
        "headline": header.headline,
        "contacts": [
            {
                "kind": contact.kind,
                "label": contact.label,
                "value": contact.value,
                "url": contact.url,
            }
            for contact in header.contacts
        ],
    }


def header_unchanged(original: ResumeInput, tailored: ResumeInput) -> bool:
    """Return True iff the header's identity text is identical.

    The candidate's identity (name, headline, contact details) must never be
    rewritten by tailoring. Only the ids are ignored: they are structural, not
    content.
    """
    return _header_identity(migrate_document(original)) == _header_identity(
        migrate_document(tailored)
    )
