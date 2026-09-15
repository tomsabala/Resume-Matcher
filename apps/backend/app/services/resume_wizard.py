"""Service helpers for the adaptive resume wizard.

The wizard is driven by the document itself: which questions exist, which
section a turn targets and how an answer is merged all come from the document's
sections and their ``kind``. Nothing here knows a built-in section list.
"""

import json
import re
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    ValidationError,
    field_validator,
)

from app.config_cache import get_content_language
from app.llm import _scrub_secrets, complete_json
from app.prompts.resume_wizard import RESUME_WIZARD_TURN_PROMPT
from app.prompts.schema import describe_document_schema
from app.prompts.templates import get_language_name
from app.schemas.document import (
    Bullet,
    Contact,
    Entry,
    EntryLink,
    Header,
    ResumeDocument,
    Section,
    SectionKind,
    TagGroup,
    slugify_key,
)
from app.schemas.resume_wizard import (
    FIXED_WIZARD_SECTIONS,
    ResumeWizardHistoryEntry,
    ResumeWizardProgress,
    ResumeWizardQuestion,
    ResumeWizardState,
    section_token,
    token_section_key,
)
from app.services.improver import _sanitize_user_input
from app.services.resume_wizard_copy import (
    section_empty_warning,
    section_question,
    wizard_copy,
)

RESUME_WIZARD_MAX_QUESTIONS = 15
_PROGRESS_BASELINE = 8
_MAX_QUESTION_CHARS = 2000

# The scaffold a fresh draft starts from, so the wizard has something to ask
# about. Headings are data like any other section's; the translation keys are the
# existing built-in ones, so a finalized wizard resume localizes exactly like a
# migrated one. The model may add further sections at any time.
_STARTER_SECTIONS: tuple[tuple[str, str, str, SectionKind, str], ...] = (
    ("summary", "Summary", "resume.sections.summary", SectionKind.TEXT, "main"),
    (
        "experience",
        "Experience",
        "resume.sections.experience",
        SectionKind.ENTRIES,
        "main",
    ),
    ("education", "Education", "resume.sections.education", SectionKind.ENTRIES, "main"),
    ("projects", "Projects", "resume.sections.projects", SectionKind.ENTRIES, "main"),
    (
        "skills",
        "Skills & Awards",
        "resume.sections.skills",
        SectionKind.GROUPS,
        "side",
    ),
)

_CONTACT_KINDS = frozenset(
    {"email", "phone", "website", "github", "linkedin", "location", "other"}
)


class _ResumeWizardAIEnvelope(BaseModel):
    """Require resume data; omitted or null guidance uses safe defaults."""

    model_config = ConfigDict(strict=True)

    resume_data: dict[str, Any]
    next_question: dict[str, Any] | None = None
    inferred_skills: list[str] = Field(default_factory=list)
    is_complete: StrictBool = False

    @field_validator("inferred_skills", mode="before")
    @classmethod
    def _default_null_skills(cls, value: Any) -> Any:
        return [] if value is None else value

    @field_validator("is_complete", mode="before")
    @classmethod
    def _default_null_completion(cls, value: Any) -> Any:
        return False if value is None else value


# The keyword ("my name", "name") may be lower- or upper-cased, but the captured
# name must start uppercase — so we case the keyword explicitly with [Mm]/[Nn]
# instead of re.IGNORECASE (which would let the [A-Z] capture match lowercase
# words and produce false positives like "domain name facebook is" -> "facebook is").
_INTRO_NAME_PATTERNS = (
    re.compile(r"\bI(?:'| a)m\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?)"),
    re.compile(r"\b[Mm]y name is\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?)"),
    re.compile(r"\b[Nn]ame(?:'s| is)?\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?)"),
)


def build_starter_document() -> ResumeDocument:
    """The empty-but-shaped document a new wizard draft starts from."""
    return ResumeDocument(
        sections=[
            Section(
                key=key,
                heading=heading,
                headingI18nKey=i18n_key,
                kind=kind,
                column=column,  # type: ignore[arg-type]
            )
            for key, heading, i18n_key, kind, column in _STARTER_SECTIONS
        ]
    )


def section_is_empty(section: Section) -> bool:
    """True when a section has no content for its kind yet."""
    if section.kind is SectionKind.TEXT:
        return not section.text.strip()
    if section.kind is SectionKind.ENTRIES:
        return not section.entries
    if section.kind is SectionKind.TAGS:
        return not section.tags
    return not any(group.values for group in section.groups)


def section_prompt(section: str, language: str = "en", heading: str = "") -> str:
    """Deterministic fallback question text for a wizard target."""
    if section in FIXED_WIZARD_SECTIONS:
        return wizard_copy(language, section)
    if heading.strip():
        return section_question(language, heading.strip())
    return wizard_copy(language, "next")


def valid_section(section: str, doc: ResumeDocument) -> str:
    """Clamp a target to a fixed step or a section this document has."""
    if section in FIXED_WIZARD_SECTIONS:
        return section
    key = token_section_key(section)
    if key and doc.section(key) is not None:
        return section
    return "review"


def section_heading(doc: ResumeDocument, target: str) -> str:
    """The heading of the section a target token addresses ("" for steps)."""
    section = doc.section(token_section_key(target))
    return section.heading if section is not None else ""


def build_initial_wizard_state() -> ResumeWizardState:
    """Build the first state shown to a user entering the wizard."""
    language = get_content_language()
    return ResumeWizardState(
        step="intro",
        resume_data=build_starter_document(),
        current_question=ResumeWizardQuestion(
            text=section_prompt("intro", language), section="intro"
        ),
        progress=ResumeWizardProgress(current=0, total=_PROGRESS_BASELINE),
    )


def extract_intro_name(answer: str) -> str:
    """Extract a likely user name from the intro answer."""
    for pattern in _INTRO_NAME_PATTERNS:
        match = pattern.search(answer)
        if match:
            return match.group(1).strip().rstrip(".")
    return ""


def merge_unique_skills(existing: list[str], inferred: list[str]) -> list[str]:
    """Merge short values while preserving first-seen casing and order."""
    merged: list[str] = []
    seen: set[str] = set()
    for item in [*existing, *inferred]:
        skill = item.strip()
        key = skill.casefold()
        if skill and key not in seen:
            merged.append(skill)
            seen.add(key)
    return merged


def build_review_warnings(doc: ResumeDocument, language: str = "en") -> list[str]:
    """Deterministic, gentle notes about useful resume facts that are missing."""
    warnings: list[str] = []
    # Name is the one HARD requirement for finalize (the request 422s without it),
    # so surface it at review rather than letting the user hit a generic failure.
    if not doc.header.name.strip():
        warnings.append(wizard_copy(language, "warning_name"))
    if not any(contact.value.strip() for contact in doc.header.contacts):
        warnings.append(wizard_copy(language, "warning_contact"))
    for section in doc.sections:
        if section.visible and section_is_empty(section):
            warnings.append(section_empty_warning(language, section.heading))
    return warnings


def compute_progress(asked_count: int, is_complete: bool) -> ResumeWizardProgress:
    """Server-side progress so the bar never trusts the model."""
    total = min(
        RESUME_WIZARD_MAX_QUESTIONS,
        max(_PROGRESS_BASELINE, asked_count + (0 if is_complete else 2)),
    )
    return ResumeWizardProgress(current=min(asked_count, total), total=total)


# ---------------------------------------------------------------------------
# Tolerant coercion of the model's document
# ---------------------------------------------------------------------------


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _short_values(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _coerce_bullets(value: Any) -> list[Bullet]:
    bullets: list[Bullet] = []
    if not isinstance(value, list):
        return bullets
    for item in value:
        if isinstance(item, str):
            text, style = item.strip(), "bullet"
        elif isinstance(item, dict):
            text = _text(item.get("text"))
            style = "plain" if item.get("style") == "plain" else "bullet"
        else:
            continue
        if text:
            bullets.append(Bullet(text=text, style=style))  # type: ignore[arg-type]
    return bullets


def _coerce_links(value: Any) -> list[EntryLink]:
    links: list[EntryLink] = []
    if not isinstance(value, list):
        return links
    for item in value:
        if not isinstance(item, dict):
            continue
        url = _text(item.get("url"))
        if not url:
            continue
        kind = _text(item.get("kind"))
        links.append(
            EntryLink(
                kind=kind if kind in {"github", "website", "linkedin"} else "other",  # type: ignore[arg-type]
                url=url,
            )
        )
    return links


def _coerce_entries(value: Any) -> list[Entry]:
    entries: list[Entry] = []
    if not isinstance(value, list):
        return entries
    for item in value:
        if not isinstance(item, dict):
            continue
        fields: dict[str, Any] = {
            "title": _text(item.get("title")),
            "subtitle": _text(item.get("subtitle")),
            "meta": _text(item.get("meta")),
            "period": _text(item.get("period")),
            "links": _coerce_links(item.get("links")),
            "summary": _text(item.get("summary")),
            "bullets": _coerce_bullets(item.get("bullets")),
        }
        # An omitted id is add intent: the model cannot invent a stable one, so
        # the default factory allocates it.
        entry_id = _text(item.get("id"))
        if entry_id:
            fields["id"] = entry_id
        entries.append(Entry(**fields))
    return entries


def _coerce_groups(value: Any) -> list[TagGroup]:
    groups: list[TagGroup] = []
    if not isinstance(value, list):
        return groups
    for item in value:
        if isinstance(item, dict):
            groups.append(
                TagGroup(
                    label=_text(item.get("label")),
                    values=_short_values(item.get("values")),
                )
            )
    return groups


def _coerce_contacts(value: Any) -> list[Contact]:
    contacts: list[Contact] = []
    if not isinstance(value, list):
        return contacts
    for item in value:
        if not isinstance(item, dict):
            continue
        contact_value = _text(item.get("value"))
        if not contact_value:
            continue
        kind = _text(item.get("kind"))
        contacts.append(
            Contact(
                kind=kind if kind in _CONTACT_KINDS else "other",  # type: ignore[arg-type]
                label=_text(item.get("label")),
                value=contact_value,
                url=_text(item.get("url")),
            )
        )
    return contacts


def _coerce_kind(value: Any, raw: dict[str, Any]) -> SectionKind:
    kind = _text(value).lower()
    if kind in {member.value for member in SectionKind}:
        return SectionKind(kind)
    # No usable kind: infer it from whichever content field carries data.
    if isinstance(raw.get("entries"), list) and raw["entries"]:
        return SectionKind.ENTRIES
    if isinstance(raw.get("groups"), list) and raw["groups"]:
        return SectionKind.GROUPS
    if isinstance(raw.get("tags"), list) and raw["tags"]:
        return SectionKind.TAGS
    return SectionKind.TEXT


def _coerce_section(raw: dict[str, Any]) -> Section | None:
    heading = _text(raw.get("heading"))
    key = _text(raw.get("key")).lower()
    if not key and not heading:
        return None
    kind = _coerce_kind(raw.get("kind"), raw)
    return Section(
        key=slugify_key(key or heading),
        heading=heading or key.replace("_", " ").title(),
        kind=kind,
        visible=raw.get("visible") is not False,
        column="side" if _text(raw.get("column")) == "side" else "main",
        text=_text(raw.get("text")),
        entries=_coerce_entries(raw.get("entries")),
        tags=_short_values(raw.get("tags")),
        groups=_coerce_groups(raw.get("groups")),
    )


def normalize_wizard_document(raw: dict[str, Any]) -> ResumeDocument:
    """Read the model's document tolerantly.

    The contract forbids extra fields, so a strict validation would turn any
    model sloppiness into a failed turn. This keeps the fields the contract
    defines, coerces loose shapes (a bare bullet string, a missing ``kind``) and
    drops the rest. Ids the model did not echo are allocated by the schema, and
    ``headingI18nKey`` is never taken from the model — a translation key is not
    the model's to invent.
    """
    header_raw = raw.get("header")
    header_raw = header_raw if isinstance(header_raw, dict) else {}
    sections: list[Section] = []
    taken: set[str] = set()
    for item in raw.get("sections") or []:
        if not isinstance(item, dict):
            continue
        section = _coerce_section(item)
        if section is None or section.key in taken:
            continue
        taken.add(section.key)
        sections.append(section)
    return ResumeDocument(
        header=Header(
            name=_text(header_raw.get("name")),
            headline=_text(header_raw.get("headline")),
            contacts=_coerce_contacts(header_raw.get("contacts")),
        ),
        sections=sections,
    )


# ---------------------------------------------------------------------------
# Merging one turn into the draft
# ---------------------------------------------------------------------------


def _entry_signature(entry: Entry) -> tuple[str, str, str]:
    return (
        entry.title.casefold(),
        entry.subtitle.casefold(),
        entry.period.casefold(),
    )


def _merge_entries(existing: list[Entry], updated: list[Entry]) -> list[Entry]:
    """Merge echoed entries by stable id, appending the ones declared as new.

    A partial reply (the model echoes only the role the user just described)
    must never erase earlier entries. Entries echoing a known id replace that
    entry in place; an unknown id means the model did not echo one, so a unique
    content-signature match still counts as an edit and anything else is new.
    """
    known_ids = {entry.id for entry in existing}
    # A same-length echo where no id is recognisable is a full positional echo:
    # matching by signature alone would duplicate every entry whose identity
    # fields the user just corrected. Ambiguous for a single entry, where a
    # genuinely new entry looks identical, so only trust it for longer lists.
    if (
        len(existing) > 1
        and len(updated) == len(existing)
        and all(entry.id not in known_ids for entry in updated)
    ):
        for old, new in zip(existing, updated):
            new.id = old.id
        return list(updated)

    result = list(existing)
    position_by_id = {entry.id: index for index, entry in enumerate(result)}
    positions_by_signature: dict[tuple[str, str, str], list[int]] = {}
    for index, entry in enumerate(result):
        positions_by_signature.setdefault(_entry_signature(entry), []).append(index)

    for entry in updated:
        position = position_by_id.pop(entry.id, None)
        if position is None:
            candidates = positions_by_signature.get(_entry_signature(entry), [])
            position = candidates[0] if len(candidates) == 1 else None
        if position is None:
            result.append(entry)
            continue
        previous = positions_by_signature.get(_entry_signature(result[position]))
        if previous is not None and position in previous:
            previous.remove(position)
        entry.id = result[position].id
        result[position] = entry
    return result


def _merge_groups(existing: list[TagGroup], updated: list[TagGroup]) -> list[TagGroup]:
    """Union group values by label, keeping existing labels and order."""
    result = [group.model_copy(deep=True) for group in existing]
    position_by_label = {
        group.label.casefold(): index for index, group in enumerate(result)
    }
    for group in updated:
        if not group.values:
            continue
        position = position_by_label.get(group.label.casefold())
        if position is None:
            result.append(
                TagGroup(label=group.label, values=merge_unique_skills([], group.values))
            )
            position_by_label[group.label.casefold()] = len(result) - 1
            continue
        result[position].values = merge_unique_skills(
            result[position].values, group.values
        )
    return result


def _merge_header(target: Header, updated: Header) -> None:
    """Fill header fields the model supplied, never blanking existing ones."""
    if updated.name:
        target.name = updated.name
    if updated.headline:
        target.headline = updated.headline
    for contact in updated.contacts:
        same_kind = next(
            (
                existing
                for existing in target.contacts
                if existing.kind == contact.kind and contact.kind != "other"
            ),
            None,
        )
        if same_kind is not None:
            same_kind.label = contact.label or same_kind.label
            same_kind.value = contact.value
            same_kind.url = contact.url or same_kind.url
            continue
        if any(
            existing.value.casefold() == contact.value.casefold()
            for existing in target.contacts
        ):
            continue
        target.contacts.append(contact)


def _merge_section_content(
    target: Section, updated: Section, inferred_skills: list[str]
) -> None:
    """Merge the model's content into one section, dispatching on its kind."""
    if target.kind is SectionKind.TEXT:
        if updated.text:
            target.text = updated.text
        return
    if target.kind is SectionKind.ENTRIES:
        if updated.entries:
            target.entries = _merge_entries(target.entries, updated.entries)
        return
    if target.kind is SectionKind.TAGS:
        target.tags = merge_unique_skills(
            target.tags, [*updated.tags, *inferred_skills]
        )
        return
    target.groups = _merge_groups(target.groups, updated.groups)
    if not inferred_skills:
        return
    # Inferred skills belong with the group the model just wrote to; failing
    # that, the first existing group, or a new unlabelled one.
    label = updated.groups[0].label.casefold() if updated.groups else None
    position = next(
        (
            index
            for index, group in enumerate(target.groups)
            if group.label.casefold() == label
        ),
        0 if target.groups else None,
    )
    if position is None:
        target.groups.append(TagGroup(values=merge_unique_skills([], inferred_skills)))
        return
    target.groups[position].values = merge_unique_skills(
        target.groups[position].values, inferred_skills
    )


def _merge_turn(
    *,
    existing: ResumeDocument,
    updated: ResumeDocument,
    section: str,
    inferred_skills: list[str],
) -> ResumeDocument:
    """Merge model output ONLY into the active target, never clobbering the rest."""
    merged = existing.model_copy(deep=True)

    if section in {"intro", "contact"}:
        _merge_header(merged.header, updated.header)
    else:
        key = token_section_key(section)
        target = merged.section(key)
        source = updated.section(key)
        if target is not None and source is not None:
            _merge_section_content(target, source, inferred_skills)

    # A section the model introduced is how the user's own sections come into
    # existence: append it, content and all. Existing sections stay untouched.
    known = {item.key for item in merged.sections}
    for candidate in updated.sections:
        if candidate.key in known or section_is_empty(candidate):
            continue
        known.add(candidate.key)
        merged.sections.append(candidate)
    return merged


# ---------------------------------------------------------------------------
# Turn orchestration
# ---------------------------------------------------------------------------


def _next_gap_section(doc: ResumeDocument) -> str:
    """Pick the next obviously-empty target, else review."""
    if not doc.header.name.strip():
        return "intro"
    if not doc.header.contacts:
        return "contact"
    for section in doc.sections:
        if section.visible and section_is_empty(section):
            return section_token(section.key)
    return "review"


def _fallback_question(doc: ResumeDocument, language: str) -> ResumeWizardQuestion:
    gap = _next_gap_section(doc)
    return ResumeWizardQuestion(
        text=section_prompt(gap, language, section_heading(doc, gap)), section=gap
    )


def _next_question(
    candidate: dict[str, Any] | None,
    doc: ResumeDocument,
    language: str,
) -> ResumeWizardQuestion:
    """Use the model's next_question, or fall back to the next empty target."""
    if isinstance(candidate, dict):
        text = candidate.get("text")
        section = candidate.get("section")
        if isinstance(text, str) and text.strip() and isinstance(section, str):
            return ResumeWizardQuestion(
                text=text.strip()[:_MAX_QUESTION_CHARS],
                section=valid_section(section, doc),
            )
    return _fallback_question(doc, language)


def _section_tokens(doc: ResumeDocument) -> str:
    tokens = [*FIXED_WIZARD_SECTIONS, *(section_token(s.key) for s in doc.sections)]
    return ", ".join(tokens)


def _describe_target(doc: ResumeDocument, section: str) -> str:
    """The LLM-facing description of what this turn is allowed to change."""
    if section == "intro":
        return 'the header: "name" and "headline" (and sections the answer clearly starts)'
    if section == "contact":
        return 'the header "contacts" list'
    if section == "review":
        return "the review step - do NOT change resume_data"
    target = doc.section(token_section_key(section))
    if target is None:
        return "the review step - do NOT change resume_data"
    return (
        f'the section with key "{target.key}" (token "{section}", '
        f'heading "{target.heading}", kind {target.kind.value})'
    )


async def run_ai_turn(
    state: ResumeWizardState,
    answer_text: str,
    *,
    skip: bool,
) -> ResumeWizardState:
    """Run one adaptive AI turn (answer or skip) and validate the result."""
    section = state.current_question.section
    language = get_content_language()
    document = state.resume_data
    resume_json = json.dumps(document.model_dump(mode="json"), ensure_ascii=False)
    prompt_answer = (
        "(The user skipped this question. Do NOT modify resume_data. "
        "Ask the next most useful question for a different section.)"
        if skip
        # Strip prompt-injection patterns AND redact credential-like tokens
        # (sk-…/AIza…/Bearer …) before the answer reaches the LLM.
        else _scrub_secrets(_sanitize_user_input(answer_text))
    )
    prompt = RESUME_WIZARD_TURN_PROMPT.format(
        output_language=get_language_name(language),
        current_target=_describe_target(document, section),
        document_schema=describe_document_schema(document),
        section_tokens=_section_tokens(document),
        resume_json=resume_json,
        answer_text=prompt_answer,
    )
    result = await complete_json(prompt, max_tokens=8192, schema_type="resume")
    try:
        envelope = _ResumeWizardAIEnvelope.model_validate(result)
    except ValidationError as error:
        raise ValueError("Resume wizard received an invalid response.") from error

    inferred = envelope.inferred_skills

    if skip:
        data = document.model_copy(deep=True)
    else:
        data = _merge_turn(
            existing=document,
            updated=normalize_wizard_document(envelope.resume_data),
            section=section,
            inferred_skills=inferred,
        )

    if section == "intro" and not data.header.name.strip():
        fallback = extract_intro_name(answer_text)
        if fallback:
            data.header.name = fallback

    asked_count = state.asked_count + 1
    # `is_complete` is a SUGGESTION to surface "Review & finish" — the step stays
    # "question" and never auto-finalizes. The client decides when to call /review.
    is_complete = envelope.is_complete or asked_count >= RESUME_WIZARD_MAX_QUESTIONS

    history = list(state.history)
    history.append(
        ResumeWizardHistoryEntry(
            question=state.current_question.text,
            answer="" if skip else answer_text,
            section=section,
            resume_data_before=document,
        )
    )

    return ResumeWizardState(
        step="question",
        resume_data=data,
        current_question=_next_question(envelope.next_question, data, language),
        history=history,
        asked_count=asked_count,
        inferred_skills=inferred,
        is_complete=is_complete,
        progress=compute_progress(asked_count, is_complete),
        warnings=[],
    )


def apply_back(state: ResumeWizardState) -> ResumeWizardState:
    """Deterministically restore the previous question + draft snapshot."""
    if not state.history:
        return state.model_copy(deep=True)
    history = list(state.history)
    last = history.pop()
    asked_count = max(0, state.asked_count - 1)
    # Derive step from the restored question itself, not just the count, so a
    # restored non-intro question never renders under the intro step (which hides
    # the question-step actions).
    return ResumeWizardState(
        step="intro" if last.section == "intro" else "question",
        resume_data=last.resume_data_before,
        current_question=ResumeWizardQuestion(text=last.question, section=last.section),
        history=history,
        asked_count=asked_count,
        inferred_skills=[],
        is_complete=False,
        progress=compute_progress(asked_count, False),
        warnings=[],
    )


def apply_review(state: ResumeWizardState) -> ResumeWizardState:
    """Move to the review step (no LLM call) and compute gentle warnings."""
    language = get_content_language()
    next_state = state.model_copy(deep=True)
    next_state.step = "review"
    next_state.current_question = ResumeWizardQuestion(
        text=section_prompt("review", language), section="review"
    )
    next_state.warnings = build_review_warnings(next_state.resume_data, language)
    return next_state
