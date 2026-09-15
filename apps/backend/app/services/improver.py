"""Resume improvement service using LLM."""

import copy
import json
import logging
import re
from typing import Any

from app.llm import complete_json
from app.prompts import (
    CRITICAL_TRUTHFULNESS_RULES,
    DEFAULT_IMPROVE_PROMPT_ID,
    DIFF_IMPROVE_PROMPT,
    DIFF_STRATEGY_INSTRUCTIONS,
    EXTRACT_KEYWORDS_PROMPT,
    IMPROVE_RESUME_PROMPTS,
    SKILL_TARGET_PLAN_PROMPT,
    get_language_name,
)
from app.prompts.schema import describe_editable_paths
from app.prompts.templates import IMPROVE_SCHEMA_EXAMPLE
from app.schemas.document import ResumeDocument, SectionKind, migrate_document
from app.schemas.models import ImproveDiffResult, ResumeChange
from app.services.document_walk import (
    document_text_fragments,
    iter_entries,
    skill_list_paths,
    skill_values,
)
from app.services.parser import has_meaningful_resume_content

logger = logging.getLogger(__name__)

# LLM-011: Prompt injection patterns to sanitize
_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"disregard\s+(all\s+)?above",
    r"forget\s+(everything|all)",
    r"new\s+instructions?:",
    r"system\s*:",
    r"<\s*/?\s*system\s*>",
    r"\[\s*INST\s*\]",
    r"\[\s*/\s*INST\s*\]",
]


def _validate_string_list_field(
    result: dict[str, Any],
    field: str,
) -> list[str]:
    """Return a normalized required list of non-empty strings."""
    value = result.get(field)
    if not isinstance(value, list):
        raise ValueError(f"LLM response requires a '{field}' list")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"LLM response field '{field}' must contain text")
    return [item.strip() for item in value]


def _validate_keyword_result(result: dict[str, Any]) -> dict[str, Any]:
    """Validate keyword fields consumed by tailoring while allowing sparse output."""
    validated = dict(result)
    for field in ("required_skills", "preferred_skills", "keywords"):
        validated[field] = _validate_string_list_field(result, field)
    for field in (
        "experience_requirements",
        "education_requirements",
        "key_responsibilities",
    ):
        if field in result:
            validated[field] = _validate_string_list_field(result, field)
    return validated


def _validate_diff_result(result: dict[str, Any]) -> dict[str, Any]:
    """Validate an explicit diff result, including a legitimate empty list."""
    if "changes" not in result:
        raise ValueError("LLM diff response is missing 'changes'")
    return ImproveDiffResult.model_validate(result).model_dump()


def _validate_skill_plan_result(result: dict[str, Any]) -> dict[str, Any]:
    """Validate an explicit skill-target plan without coercing invalid leaves."""
    raw_targets = result.get("target_skills")
    if not isinstance(raw_targets, list):
        raise ValueError("LLM skill plan requires a 'target_skills' list")

    normalized: list[dict[str, str]] = []
    for target in raw_targets:
        if isinstance(target, str):
            skill = target.strip()
            reason = ""
        elif isinstance(target, dict):
            raw_skill = target.get("skill")
            raw_reason = target.get("reason", "")
            if not isinstance(raw_skill, str) or not isinstance(raw_reason, str):
                raise ValueError("Skill targets require text skill and reason fields")
            skill = raw_skill.strip()
            reason = raw_reason.strip()
        else:
            raise ValueError("Skill targets must be strings or objects")
        if not skill:
            raise ValueError("Skill targets cannot be blank")
        normalized.append({"skill": skill, "reason": reason})

    raw_notes = result.get("strategy_notes", "")
    if not isinstance(raw_notes, str):
        raise ValueError("Skill plan strategy_notes must be text")

    return {
        **result,
        "target_skills": normalized,
        "strategy_notes": raw_notes.strip(),
    }


def _validate_resume_result(result: dict[str, Any]) -> dict[str, Any]:
    """Validate schema and reject a structurally valid but empty resume."""
    validated = ResumeDocument.model_validate(result).model_dump(mode="json")
    if not has_meaningful_resume_content(validated):
        raise ValueError("LLM returned an empty structured resume")
    return validated


def _sanitize_user_input(text: str) -> str:
    """LLM-011: Sanitize user input to prevent prompt injection.

    Removes or redacts common injection patterns that could manipulate LLM behavior.
    """
    sanitized = text
    for pattern in _INJECTION_PATTERNS:
        sanitized = re.sub(pattern, "[REDACTED]", sanitized, flags=re.IGNORECASE)
    return sanitized


# ---------------------------------------------------------------------------
# Diff-based improvement: path resolution, applier, verifier, LLM generator
# ---------------------------------------------------------------------------

# Section keys are user-authored slugs, so the grammar must accept digits and
# hyphens as well as letters/underscores.
_PATH_SEGMENT_RE = re.compile(r"([A-Za-z0-9_-]+)(?:\[(\d+)\])?")

# Never editable by the AI. The header is the user's identity; entry identity
# fields (who/where/when) must survive tailoring untouched, and structural
# fields would let a "change" silently retype or reorder the document.
_BLOCKED_PATH_PREFIXES = frozenset({"header", "schemaVersion"})
_BLOCKED_FIELD_NAMES = frozenset(
    {
        "id",
        "key",
        "kind",
        "heading",
        "headingI18nKey",
        "visible",
        "column",
        "title",
        "subtitle",
        "meta",
        "period",
        "links",
        "label",
        "style",
    }
)

_METRIC_RE = re.compile(r"\d+%|\d+x|\$\d+")


def build_allowed_paths(document: ResumeDocument) -> list[re.Pattern[str]]:
    """Editable change paths for this exact document, one pattern per section.

    This is what makes user-created sections AI-editable: the allowlist is a
    function of the document's sections and their kinds, not a fixed list of
    six built-in names. Content is editable; identity is not (see
    ``_BLOCKED_FIELD_NAMES``).
    """
    patterns: list[re.Pattern[str]] = []
    for section in document.sections:
        key = re.escape(section.key)
        if section.kind is SectionKind.TEXT:
            patterns.append(re.compile(rf"^sections\.{key}\.text$"))
        elif section.kind is SectionKind.ENTRIES:
            patterns.append(
                re.compile(
                    rf"^sections\.{key}\.entries\[\d+\]\."
                    rf"(summary|bullets|bullets\[\d+\]\.text)$"
                )
            )
        elif section.kind is SectionKind.TAGS:
            patterns.append(re.compile(rf"^sections\.{key}\.tags$"))
        else:
            patterns.append(re.compile(rf"^sections\.{key}\.groups\[\d+\]\.values$"))
    return patterns


def _is_path_allowed(path: str, allowed: list[re.Pattern[str]]) -> bool:
    """Check a path against this document's generated allowlist."""
    return any(pattern.match(path) for pattern in allowed)


def _is_path_blocked(path: str) -> bool:
    """Check if a path targets identity or structure rather than content."""
    for prefix in _BLOCKED_PATH_PREFIXES:
        if path == prefix or path.startswith(prefix + ".") or path.startswith(prefix + "["):
            return True

    leaf = re.sub(r"\[\d+\]$", "", path.split(".")[-1])
    return leaf in _BLOCKED_FIELD_NAMES


def _descend(current: Any, key: str, index_str: str | None) -> tuple[Any, bool]:
    """Take one path segment.

    Mapping keys index a dict as usual. A **list** node is addressed by the
    ``key`` field of its items, which is how ``sections.<section_key>`` works:
    section order is user-editable, so a positional path would silently retarget
    whenever the user reorders the document.
    """
    if isinstance(current, list):
        match = next(
            (
                item
                for item in current
                if isinstance(item, dict) and item.get("key") == key
            ),
            None,
        )
        if match is None:
            return None, False
        current = match
    elif isinstance(current, dict):
        if key not in current:
            return None, False
        current = current[key]
    else:
        return None, False

    if index_str is not None:
        index = int(index_str)
        if not isinstance(current, list) or index < 0 or index >= len(current):
            return None, False
        current = current[index]
    return current, True


def _resolve_path(data: dict[str, Any], path: str) -> tuple[Any, bool]:
    """Resolve a dot+bracket path to a value in the document.

    Returns:
        (value, success). On failure returns (None, False).
    """
    current: Any = data
    for segment_match in _PATH_SEGMENT_RE.finditer(path):
        current, ok = _descend(current, segment_match.group(1), segment_match.group(2))
        if not ok:
            return None, False
    return current, True


def _set_at_path(data: dict[str, Any], path: str, value: Any) -> bool:
    """Set a value at the given path. Returns True on success."""
    segments = list(_PATH_SEGMENT_RE.finditer(path))
    if not segments:
        return False

    current: Any = data
    for seg in segments[:-1]:
        current, ok = _descend(current, seg.group(1), seg.group(2))
        if not ok:
            return False

    last = segments[-1]
    key = last.group(1)
    index_str = last.group(2)

    if index_str is not None:
        container, ok = _descend(current, key, None)
        index = int(index_str)
        if not ok or not isinstance(container, list) or index < 0 or index >= len(container):
            return False
        container[index] = value
    else:
        if not isinstance(current, dict):
            return False
        current[key] = value

    return True


def _verify_original_matches(actual: Any, expected: str | list[str] | None) -> bool:
    """Verify that the original text from the diff matches the actual value."""
    if expected is None:
        return True  # no original provided (e.g. append) — nothing to verify
    if not isinstance(expected, str):
        return False  # a non-str original on a text action is malformed — reject
    if not isinstance(actual, str):
        return False
    return actual.strip().casefold() == expected.strip().casefold()


def apply_diffs(
    original: dict[str, Any],
    changes: list[ResumeChange],
    allowed_skill_targets: list[dict[str, Any] | str] | None = None,
) -> tuple[dict[str, Any], list[ResumeChange], list[ResumeChange]]:
    """Apply verified diffs to the original document.

    Each change goes through 4 gates:
    1. Path is editable for *this* document (allowlist generated per section)
    2. Path does not target identity or structure
    3. Path resolves to an actual value in the original
    4. Original text matches (for replace actions)

    For reorder: validates the new list contains exactly the same items.

    Args:
        original: The original document (``ResumeDocument``-shaped dict)
        changes: List of changes from the LLM
        allowed_skill_targets: Verified skill targets allowed for add_skill actions

    Returns:
        (result_dict, applied_changes, rejected_changes)
    """
    result = copy.deepcopy(original)
    applied: list[ResumeChange] = []
    rejected: list[ResumeChange] = []
    allowed_skill_keys = _build_allowed_skill_target_keys(allowed_skill_targets)
    document = migrate_document(original)
    allowed_paths = build_allowed_paths(document)
    skill_paths = skill_list_paths(document)

    for change in changes:
        path = change.path
        action = change.action

        # Gate 1: Path must be editable in this document
        if not _is_path_allowed(path, allowed_paths):
            logger.info("Diff rejected (not in allowed list): %s", path)
            rejected.append(change)
            continue

        # Gate 2: Path must not be blocked
        if _is_path_blocked(path):
            logger.info("Diff rejected (blocked path): %s", path)
            rejected.append(change)
            continue

        # Gate 3: Path must resolve to a real value
        actual_value, resolved = _resolve_path(result, path)
        if not resolved:
            logger.info("Diff rejected (path not found): %s", path)
            rejected.append(change)
            continue

        if action == "replace":
            # `replace` rewrites one text leaf. A list-valued path (``bullets``,
            # ``tags``, ``values``) is only reachable by `append`/`reorder`/
            # `add_skill`; letting `replace` through would swap the list for a
            # bare string and make the document fail its own schema on the very
            # next read.
            if isinstance(actual_value, list):
                logger.info("Diff rejected (replace targets a list): %s", path)
                rejected.append(change)
                continue

            # Gate 4: Original text must match what's actually there
            if not _verify_original_matches(actual_value, change.original):
                logger.info(
                    "Diff rejected (original mismatch): path=%s expected=%r actual=%r",
                    path,
                    change.original,
                    actual_value,
                )
                rejected.append(change)
                continue

            # Replace must use a string value (not list)
            if not isinstance(change.value, str):
                logger.info("Diff rejected (replace with non-string value): %s", path)
                rejected.append(change)
                continue

            if not _set_at_path(result, path, change.value):
                rejected.append(change)
                continue
            applied.append(change)

        elif action == "append":
            # Only bullets may be appended. A short value (skill, language,
            # award) must come through `add_skill`, which is gated on the
            # verified target plan — otherwise `append` would be an
            # unverified back door into the same lists.
            if not path.endswith(".bullets"):
                logger.info("Diff rejected (append outside a bullet list): %s", path)
                rejected.append(change)
                continue
            if not isinstance(actual_value, list):
                logger.info("Diff rejected (append to non-list): %s", path)
                rejected.append(change)
                continue
            if not isinstance(change.value, str) or not change.value.strip():
                logger.info("Diff rejected (append non-string or empty value): %s", path)
                rejected.append(change)
                continue
            actual_value.append({"text": change.value, "style": "bullet"})
            applied.append(change)

        elif action == "reorder":
            if not isinstance(actual_value, list) or not isinstance(change.value, list):
                rejected.append(change)
                continue
            orig_set = sorted(s.casefold() for s in actual_value if isinstance(s, str))
            new_set = sorted(s.casefold() for s in change.value if isinstance(s, str))
            reordered: list[str] = []
            if orig_set == new_set:
                # Pure permutation: map the new order back to original casing.
                casefold_to_originals: dict[str, list[str]] = {}
                for item in actual_value:
                    if isinstance(item, str):
                        casefold_to_originals.setdefault(item.casefold(), []).append(item)
                for item in change.value:
                    if isinstance(item, str):
                        originals = casefold_to_originals.get(item.casefold(), [])
                        reordered.append(originals.pop(0) if originals else item)
            else:
                # Salvage (issue #736): the LLM folded new/removed items into a
                # reorder. Rather than dropping the whole change, apply the SAFE
                # subset *in the requested order*: walk the proposed list, placing
                # each existing item where the model put it (so prioritized JD
                # skills stay near the top) and — for the skills list only —
                # inserting new items that pass the SAME verified gate as
                # add_skill. Originals the model omitted are appended at the end
                # so a real item is never silently lost. Lists with no verifier
                # (a "Languages" tag list, say) drop new items entirely, to
                # avoid fabrication.
                casefold_to_originals: dict[str, list[str]] = {}
                for item in actual_value:
                    if isinstance(item, str):
                        casefold_to_originals.setdefault(item.casefold(), []).append(item)
                original_cfs = set(casefold_to_originals)
                is_skills = path in skill_paths
                added_new: set[str] = set()
                for item in change.value:
                    if not isinstance(item, str):
                        continue
                    cf = item.casefold()
                    if cf in original_cfs:
                        bucket = casefold_to_originals[cf]
                        if bucket:  # place original in requested position (dupes preserved)
                            reordered.append(bucket.pop(0))
                        # else: a duplicate of an already-placed original — skip
                    elif is_skills and cf not in added_new:
                        skill = item.strip()
                        if skill and _normalize_skill_key(skill) in allowed_skill_keys:
                            reordered.append(skill)  # verified new skill, requested position
                            added_new.add(cf)
                        else:
                            logger.info("Reorder salvage dropped unverified skill: %s", skill)
                    # else: non-skills new item → dropped (no verifier to ground it)
                for item in actual_value:  # append any originals the model omitted
                    if isinstance(item, str):
                        bucket = casefold_to_originals[item.casefold()]
                        if bucket:
                            reordered.append(bucket.pop(0))
                logger.info("Diff reorder salvaged (item-set mismatch): %s", path)
            if not _set_at_path(result, path, reordered):
                rejected.append(change)
                continue
            applied.append(change)

        elif action == "add_skill":
            if path not in skill_paths:
                logger.info("Diff rejected (add_skill outside a skill list): %s", path)
                rejected.append(change)
                continue
            if not isinstance(actual_value, list):
                logger.info("Diff rejected (add_skill to non-list): %s", path)
                rejected.append(change)
                continue
            if not isinstance(change.value, str) or not change.value.strip():
                logger.info("Diff rejected (add_skill empty/non-string): %s", path)
                rejected.append(change)
                continue
            new_skill = change.value.strip()
            existing = {
                item.casefold()
                for item in actual_value
                if isinstance(item, str)
            }
            if new_skill.casefold() in existing:
                logger.info("Diff rejected (duplicate skill): %s", new_skill)
                rejected.append(change)
                continue
            if _normalize_skill_key(new_skill) not in allowed_skill_keys:
                logger.info("Diff rejected (skill not in verified targets): %s", new_skill)
                rejected.append(change)
                continue
            actual_value.append(new_skill)
            applied.append(change)

        else:
            logger.info("Diff rejected (unknown action): %s", action)
            rejected.append(change)

    return result, applied, rejected


def _count_description_words(data: dict[str, Any]) -> int:
    """Count words in every prose field of the document.

    Prose is what tailoring rewrites: ``TEXT`` sections, entry summaries and
    bullet text. Identity fields and short tag values are excluded, so the
    inflation check in :func:`verify_diff_result` measures what the AI touched.
    """
    document = migrate_document(data)
    total = 0
    for section in document.sections:
        if section.kind is SectionKind.TEXT:
            total += len(section.text.split())
        elif section.kind is SectionKind.ENTRIES:
            for entry in section.entries:
                total += len(entry.summary.split())
                total += sum(len(bullet.text.split()) for bullet in entry.bullets)
    return total


def verify_diff_result(
    original: dict[str, Any],
    result: dict[str, Any],
    applied_changes: list[ResumeChange],
    job_keywords: dict[str, Any],
) -> list[str]:
    """Local quality checks on the diff result. Returns list of warnings.

    All checks are local (zero LLM cost). Warnings are informational —
    they don't block the response.
    """
    warnings: list[str] = []

    # Check 1: No empty result
    if not applied_changes:
        warnings.append("No changes were applied — resume returned unchanged")
        return warnings

    before = migrate_document(original)
    after = migrate_document(result)

    # Check 2: Entry counts preserved, per section
    after_by_key = {section.key: section for section in after.sections}
    for section in before.sections:
        if section.kind is not SectionKind.ENTRIES:
            continue
        result_section = after_by_key.get(section.key)
        result_count = len(result_section.entries) if result_section else 0
        if len(section.entries) != result_count:
            warnings.append(
                f"Section count changed: {section.heading} "
                f"({len(section.entries)} → {result_count})"
            )

    # Check 3: Entry identity unchanged. Identity is (title, subtitle) for
    # every kind of entry — who/where, never rewritten by tailoring.
    for section in before.sections:
        result_section = after_by_key.get(section.key)
        if section.kind is not SectionKind.ENTRIES or result_section is None:
            continue
        for index, (before_entry, after_entry) in enumerate(
            zip(section.entries, result_section.entries)
        ):
            for field in ("title", "subtitle"):
                original_value = getattr(before_entry, field).strip()
                new_value = getattr(after_entry, field).strip()
                if original_value and original_value != new_value:
                    warnings.append(
                        f"Identity field changed: sections.{section.key}"
                        f".entries[{index}].{field} "
                        f"('{original_value}' → '{new_value}')"
                    )

    # Check 4: Word count ratio
    orig_words = _count_description_words(original)
    result_words = _count_description_words(result)
    if orig_words > 0 and result_words > orig_words * 1.8:
        warnings.append(
            f"Word count increased significantly: "
            f"{orig_words} → {result_words} ({result_words / orig_words:.1f}x)"
        )

    # Check 5: Invented metrics (covers both replace and append)
    for change in applied_changes:
        if change.action in ("replace", "append") and isinstance(change.value, str):
            new_metrics = set(_METRIC_RE.findall(change.value))
            # For append, original is None — any metric is potentially invented
            original_text = change.original or ""
            old_metrics = set(_METRIC_RE.findall(original_text))
            invented = new_metrics - old_metrics
            if invented:
                warnings.append(
                    f"Possible invented metric in {change.path}: "
                    f"{', '.join(invented)} (not in original)"
                )

    return warnings


async def generate_resume_diffs(
    original_resume: str,
    job_description: str,
    job_keywords: dict[str, Any],
    language: str = "en",
    prompt_id: str | None = None,
    original_resume_data: dict[str, Any] | None = None,
    skill_targets: list[dict[str, Any]] | None = None,
) -> ImproveDiffResult:
    """Generate targeted resume diffs via LLM.

    Instead of asking the LLM for the full resume, asks for a list of
    targeted changes. Each change specifies a path, action, and new value.

    Args:
        original_resume: Resume content (markdown)
        job_description: Target job description
        job_keywords: Extracted job keywords
        language: Output language code (en, es, zh, ja)
        prompt_id: Strategy id (nudge/keywords/full)
        original_resume_data: Structured resume JSON
        skill_targets: Verified skill targets from the planning pass

    Returns:
        ImproveDiffResult with list of changes and strategy notes
    """
    keywords_str = _prepare_keywords_for_prompt(job_keywords)
    output_language = get_language_name(language)

    selected_id = prompt_id or DEFAULT_IMPROVE_PROMPT_ID
    if selected_id not in DIFF_STRATEGY_INSTRUCTIONS:
        logger.warning(
            "Unknown prompt_id '%s'; using default diff strategy.",
            selected_id,
        )
    strategy_instruction = DIFF_STRATEGY_INSTRUCTIONS.get(
        selected_id, DIFF_STRATEGY_INSTRUCTIONS[DEFAULT_IMPROVE_PROMPT_ID]
    )

    # LLM-011: Sanitize job description
    sanitized_jd = _sanitize_user_input(job_description)

    # Use structured JSON if available with month precision, else markdown
    if original_resume_data is not None:
        if _has_month_in_dates(original_resume_data):
            resume_input = json.dumps(original_resume_data)
        else:
            resume_input = original_resume
    else:
        resume_input = original_resume

    prompt = DIFF_IMPROVE_PROMPT.format(
        strategy_instruction=strategy_instruction,
        output_language=output_language,
        job_keywords=keywords_str,
        skill_targets=_prepare_skill_targets_for_prompt(skill_targets),
        job_description=sanitized_jd,
        original_resume=resume_input,
        # The model is told the real paths of this document's sections, so a
        # user-created section is a first-class edit target.
        editable_paths=describe_editable_paths(migrate_document(original_resume_data)),
    )

    result = await complete_json(
        prompt=prompt,
        system_prompt="You are an expert resume editor. Output only valid JSON with targeted changes.",
        max_tokens=4096,
        schema_type="diff",
        response_validator=_validate_diff_result,
    )

    return ImproveDiffResult.model_validate(_validate_diff_result(result))


async def extract_job_keywords(job_description: str) -> dict[str, Any]:
    """Extract keywords and requirements from job description.

    Args:
        job_description: Raw job description text

    Returns:
        Structured keywords and requirements
    """
    # LLM-011: Sanitize job description before using in prompt
    sanitized_jd = _sanitize_user_input(job_description)
    prompt = EXTRACT_KEYWORDS_PROMPT.format(job_description=sanitized_jd)

    result = await complete_json(
        prompt=prompt,
        system_prompt="You are an expert job description analyzer.",
        schema_type="keywords",
        response_validator=_validate_keyword_result,
    )
    return _validate_keyword_result(result)


MONTH_PATTERN = re.compile(
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\b",
    re.IGNORECASE,
)


def _has_month_in_dates(data: dict[str, Any]) -> bool:
    """Check whether any entry's period includes a month name."""
    document = migrate_document(data)
    return any(
        MONTH_PATTERN.search(entry.period) for _, _, entry in iter_entries(document)
    )


def _prepare_keywords_for_prompt(job_keywords: dict[str, Any]) -> str:
    """Format job keywords as a focused, readable list for the LLM prompt.

    Extracts only actionable fields (skills and keywords) and drops
    informational fields that add noise without helping the LLM tailor.
    """
    sections: list[str] = []

    required = job_keywords.get("required_skills", [])
    if required:
        sections.append("Required skills to emphasize:\n- " + "\n- ".join(str(s) for s in required))

    preferred = job_keywords.get("preferred_skills", [])
    if preferred:
        sections.append(
            "Preferred skills (include only if resume supports them):\n- "
            + "\n- ".join(str(s) for s in preferred)
        )

    keywords = job_keywords.get("keywords", [])
    if keywords:
        sections.append("Additional keywords to weave in naturally:\n- " + "\n- ".join(str(k) for k in keywords))

    return "\n\n".join(sections) if sections else "No specific keywords extracted."


def _normalize_skill_key(skill: str) -> str:
    """Normalize a skill for case-insensitive comparison."""
    return re.sub(r"\s+", " ", skill.strip()).casefold()


def _extract_skill_index(items: Any) -> dict[str, str]:
    """Build a normalized skill index from a string list."""
    if not isinstance(items, list):
        return {}
    index: dict[str, str] = {}
    for item in items:
        if not isinstance(item, str):
            continue
        skill = item.strip()
        if skill:
            index.setdefault(_normalize_skill_key(skill), skill)
    return index


def _skill_mentioned_in_text(skill: str, text: str) -> bool:
    """Return True when a skill phrase appears as a whole term in text."""
    escaped = re.escape(skill.strip().lower())
    if not escaped:
        return False
    return bool(re.search(rf"(?<!\w){escaped}(?!\w)", text.lower()))


def _build_allowed_skill_target_keys(
    allowed_skill_targets: list[dict[str, Any] | str] | None,
) -> set[str]:
    """Build normalized keys for skills approved by the planning verifier."""
    keys: set[str] = set()
    for target in allowed_skill_targets or []:
        if isinstance(target, str):
            skill = target
        elif isinstance(target, dict):
            skill = str(target.get("skill", ""))
        else:
            continue
        if skill.strip():
            keys.add(_normalize_skill_key(skill))
    return keys


def _extract_jd_skill_index(
    job_keywords: dict[str, Any],
    job_description: str | None = None,
) -> dict[str, str]:
    """Build a normalized index of explicit JD skills."""
    index: dict[str, str] = {}
    for field in ("required_skills", "preferred_skills"):
        values = job_keywords.get(field, [])
        if not isinstance(values, list):
            continue
        for value in values:
            if not isinstance(value, str):
                continue
            skill = value.strip()
            if skill and (
                job_description is None
                or _skill_mentioned_in_text(skill, job_description)
            ):
                index.setdefault(_normalize_skill_key(skill), skill)
    return index


def _skill_present_in_resume_text(skill: str, resume_data: dict[str, Any]) -> bool:
    """Return True when a skill phrase already appears in the resume's prose.

    Only user-authored text counts: matching against the raw JSON would let a
    structural key (``"links"``, a section slug, an id) ground a fabricated
    skill.
    """
    text = "\n".join(document_text_fragments(migrate_document(resume_data)))
    return _skill_mentioned_in_text(skill, text)


def verify_skill_target_plan(
    raw_plan: dict[str, Any],
    original_resume_data: dict[str, Any],
    job_keywords: dict[str, Any],
    job_description: str | None = None,
) -> dict[str, list[dict[str, str]] | str]:
    """Filter and classify LLM-proposed skill targets before diff generation.

    Existing resume skills are accepted as low-risk targets. Required and
    preferred JD skills are accepted as explicit JD-added targets for user
    review. Other skills are accepted only when they already appear in the
    resume text.
    """
    original_skills = _extract_skill_index(
        skill_values(migrate_document(original_resume_data))
    )
    jd_skills = _extract_jd_skill_index(job_keywords, job_description)
    raw_targets = raw_plan.get("target_skills", [])
    accepted: list[dict[str, str]] = []
    rejected: list[dict[str, str]] = []
    seen: set[str] = set()

    if not isinstance(raw_targets, list):
        raw_targets = []

    for target in raw_targets:
        if isinstance(target, str):
            skill = target.strip()
            reason = ""
        elif isinstance(target, dict):
            skill = str(target.get("skill", "")).strip()
            reason = str(target.get("reason", "")).strip()
        else:
            continue

        skill_key = _normalize_skill_key(skill)
        if not skill or skill_key in seen:
            continue
        seen.add(skill_key)

        if skill_key in original_skills:
            accepted.append(
                {
                    "skill": original_skills[skill_key],
                    "source": "existing",
                    "reason": reason or "Already present in resume skills",
                }
            )
        elif skill_key in jd_skills:
            # JD-required/preferred skills are accepted as targets so the résumé
            # can be tailored to actually pass ATS/recruiter screening — adding
            # relevant JD skills is the product's purpose. (Truly unsupported
            # skills — neither in the JD nor the résumé — are still rejected
            # below.) The user reviews additions in the diff preview before save.
            accepted.append(
                {
                    "skill": jd_skills[skill_key],
                    "source": "jd_added",
                    "reason": reason or "Required or preferred by the job description",
                }
            )
        elif _skill_present_in_resume_text(skill, original_resume_data):
            accepted.append(
                {
                    "skill": skill,
                    "source": "supported_by_resume",
                    "reason": reason or "Appears in the existing resume content",
                }
            )
        else:
            rejected.append(
                {
                    "skill": skill,
                    "source": "unsupported",
                    "reason": reason or "Not found in resume or job keywords",
                }
            )

    return {
        "accepted": accepted,
        "rejected": rejected,
        "strategy_notes": str(raw_plan.get("strategy_notes", "")),
    }


async def generate_skill_target_plan(
    original_resume_data: dict[str, Any],
    job_description: str,
    job_keywords: dict[str, Any],
    language: str = "en",
) -> dict[str, Any]:
    """Ask the LLM for a compact skill target plan before editing diffs."""
    output_language = get_language_name(language)
    existing_skills = skill_values(migrate_document(original_resume_data))
    sanitized_jd = _sanitize_user_input(job_description)
    prompt = SKILL_TARGET_PLAN_PROMPT.format(
        output_language=output_language,
        existing_skills=json.dumps(existing_skills, ensure_ascii=False),
        job_keywords=_prepare_keywords_for_prompt(job_keywords),
        job_description=sanitized_jd,
        original_resume=json.dumps(original_resume_data, ensure_ascii=False),
    )

    result = await complete_json(
        prompt=prompt,
        system_prompt=(
            "You are a resume skill planning agent. Output only valid JSON with "
            "target_skills and strategy_notes."
        ),
        max_tokens=2048,
        schema_type="diff",
        response_validator=_validate_skill_plan_result,
    )
    return _validate_skill_plan_result(result)


def _prepare_skill_targets_for_prompt(
    skill_targets: list[dict[str, Any]] | None,
) -> str:
    """Format verified skill targets for the diff prompt."""
    if not skill_targets:
        return "No verified skill targets."
    lines: list[str] = []
    for target in skill_targets:
        skill = str(target.get("skill", "")).strip()
        if not skill:
            continue
        source = str(target.get("source", "unknown")).strip() or "unknown"
        reason = str(target.get("reason", "")).strip()
        suffix = f": {reason}" if reason else ""
        lines.append(f"- {skill} ({source}){suffix}")
    return "\n".join(lines) if lines else "No verified skill targets."


async def improve_resume(
    original_resume: str,
    job_description: str,
    job_keywords: dict[str, Any],
    language: str = "en",
    prompt_id: str | None = None,
    original_resume_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Improve resume to better match job description.

    Args:
        original_resume: Original resume content (markdown)
        job_description: Target job description
        job_keywords: Extracted job keywords
        language: Output language code (en, es, zh, ja)
        prompt_id: Which tailor prompt to use
        original_resume_data: Structured resume JSON; used instead of
            markdown when available for higher-fidelity LLM input

    Returns:
        Improved resume data matching ResumeData schema

    LLM-006: Validates the structured result inside the content-retry budget.
    LLM-011: Sanitizes job description to prevent prompt injection.
    """
    keywords_str = _prepare_keywords_for_prompt(job_keywords)
    output_language = get_language_name(language)

    selected_prompt_id = prompt_id or DEFAULT_IMPROVE_PROMPT_ID
    prompt_template = IMPROVE_RESUME_PROMPTS.get(
        selected_prompt_id, IMPROVE_RESUME_PROMPTS[DEFAULT_IMPROVE_PROMPT_ID]
    )
    if selected_prompt_id not in CRITICAL_TRUTHFULNESS_RULES:
        logger.warning(
            "Missing truthfulness rules for prompt '%s'; using default rules.",
            selected_prompt_id,
        )
    truthfulness_rules = CRITICAL_TRUTHFULNESS_RULES.get(
        selected_prompt_id, CRITICAL_TRUTHFULNESS_RULES[DEFAULT_IMPROVE_PROMPT_ID]
    )

    # LLM-011: Sanitize job description to prevent prompt injection
    sanitized_jd = _sanitize_user_input(job_description)

    # Use structured JSON when available for higher-fidelity LLM input,
    # but fall back to raw markdown if the structured data has truncated
    # (year-only) dates — the markdown preserves months from the original PDF.
    if original_resume_data is not None:
        if _has_month_in_dates(original_resume_data):
            resume_input = json.dumps(original_resume_data)
        else:
            logger.info(
                "Structured resume data has year-only dates; using raw markdown "
                "to preserve month precision."
            )
            resume_input = original_resume
    else:
        resume_input = original_resume

    prompt = prompt_template.format(
        job_description=sanitized_jd,
        job_keywords=keywords_str,
        original_resume=resume_input,
        schema=IMPROVE_SCHEMA_EXAMPLE,
        output_language=output_language,
        critical_truthfulness_rules=truthfulness_rules,
    )

    result = await complete_json(
        prompt=prompt,
        system_prompt="You are an expert resume editor. Output only valid JSON.",
        max_tokens=8192,
        response_validator=_validate_resume_result,
    )
    return _validate_resume_result(result)


def generate_improvements(job_keywords: dict[str, Any]) -> list[dict[str, Any]]:
    """Generate improvement suggestions based on job keywords.

    Args:
        job_keywords: Extracted job keywords

    Returns:
        List of improvement suggestions
    """
    improvements = []

    # Generate suggestions based on required skills
    required_skills = job_keywords.get("required_skills", [])
    for skill in required_skills[:3]:  # Top 3 required skills
        improvements.append(
            {
                "suggestion": f"Emphasized '{skill}' to match job requirements",
                "lineNumber": None,
            }
        )

    # Generate suggestions based on key responsibilities
    responsibilities = job_keywords.get("key_responsibilities", [])
    for resp in responsibilities[:2]:  # Top 2 responsibilities
        improvements.append(
            {
                "suggestion": f"Aligned experience with: {resp}",
                "lineNumber": None,
            }
        )

    # Default improvement if none generated
    if not improvements:
        improvements.append(
            {
                "suggestion": "Resume content optimized for better keyword alignment with job description",
                "lineNumber": None,
            }
        )

    return improvements
