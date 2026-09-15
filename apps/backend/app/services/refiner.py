"""Multi-pass resume refinement service.

This module provides functionality to refine an initially tailored resume through
multiple passes:
1. Keyword injection - add missing JD keywords where supported by master resume
2. AI phrase removal - replace AI-generated buzzwords with simpler alternatives
3. Master alignment validation - ensure no fabricated content was added
"""

import copy
import json
import logging
import re
from functools import lru_cache
from typing import Any

from pydantic import ValidationError

from app.ai_budget import AIOperationDeadlineExceeded
from app.ai_limits import PromptSizeError
from app.llm import complete_json
from app.prompts.refinement import (
    AI_PHRASE_BLACKLIST,
    AI_PHRASE_REPLACEMENTS,
    KEYWORD_INJECTION_PROMPT,
)
from app.prompts.schema import describe_document_schema
from app.schemas.document import ResumeDocument, SectionKind, migrate_document
from app.schemas.refinement import (
    AlignmentReport,
    AlignmentViolation,
    KeywordGapAnalysis,
    RefinementConfig,
    RefinementResult,
)
from app.services.document_walk import (
    document_text_fragments,
    iter_entries,
    skill_values,
)
from app.services.resume_preservation import finalize_ai_resume

logger = logging.getLogger(__name__)

# LLM-012: Job description truncation limits
MAX_JD_LENGTH = 2000
MIN_TRUNCATION_WARNING_LENGTH = 1500
# Han (including supplementary planes), Kana, and Hangul syllables/Jamo.
_CJK_CHAR_CLASS = (
    r"[\u1100-\u11ff\u3040-\u30ff\u3130-\u318f\u31f0-\u31ff"
    r"\u3400-\u9fff\ua960-\ua97f\uac00-\ud7ff\uf900-\ufaff"
    r"\uff66-\uffdc\U0001b000-\U0001b16f\U00020000-\U0003ffff]"
)
_CJK_RE = re.compile(_CJK_CHAR_CLASS)


def _keyword_in_text(keyword: str, text: str) -> bool:
    """Check for a CJK substring or a bounded non-CJK term in text.

    Han, Kana, and Hangul characters may adjoin Latin skills without whitespace,
    so they also form boundaries for adjacent Latin terms. Other word characters
    retain boundaries so 'python' does not match 'pythonic' and 'java' does not
    match 'javascript'.
    """
    normalized_keyword = keyword.strip().lower()
    if not normalized_keyword:
        return False
    normalized_text = text.lower()
    if _CJK_RE.search(normalized_keyword):
        return normalized_keyword in normalized_text
    escaped = re.escape(normalized_keyword)
    pattern = (
        rf"(?:(?<!\w)|(?<={_CJK_CHAR_CLASS}))"
        rf"{escaped}"
        rf"(?:(?!\w)|(?={_CJK_CHAR_CLASS}))"
    )
    return bool(re.search(pattern, normalized_text))


def count_retained_keywords(keywords: list[str], resume: dict[str, Any]) -> int:
    """Count refinement keywords still present in the finalized resume."""
    text = _extract_all_text(resume)
    return sum(_keyword_in_text(keyword, text) for keyword in keywords)


def _normalize_skill_key(skill: str) -> str:
    """Normalize a skill for case-insensitive comparisons."""
    return re.sub(r"\s+", " ", skill.strip()).casefold()


def _extract_jd_skill_keys(
    job_keywords: dict[str, Any],
    job_description: str,
) -> set[str]:
    """Extract normalized required/preferred skills present in the raw JD."""
    keys: set[str] = set()
    for field in ("required_skills", "preferred_skills"):
        values = job_keywords.get(field, [])
        if not isinstance(values, list):
            continue
        for value in values:
            if (
                isinstance(value, str)
                and value.strip()
                and _keyword_in_text(value, job_description)
            ):
                keys.add(_normalize_skill_key(value))
    return keys


async def refine_resume(
    initial_tailored: dict[str, Any],
    master_resume: dict[str, Any],
    job_description: str,
    job_keywords: dict[str, Any],
    config: RefinementConfig | None = None,
) -> RefinementResult:
    """Multi-pass refinement of an initially tailored resume.

    Args:
        initial_tailored: Output from improve_resume() first pass
        master_resume: Original master resume data (source of truth)
        job_description: Raw job description text
        job_keywords: Extracted job keywords
        config: Refinement configuration

    Returns:
        RefinementResult with refined data and analysis
    """
    if config is None:
        config = RefinementConfig()

    current = _deep_copy(initial_tailored)
    passes = 0
    attempts = 0
    alignment_fixed = 0
    ai_phrases_found: list[str] = []
    keyword_analysis: KeywordGapAnalysis | None = None
    alignment: AlignmentReport | None = None

    # Pass 1: Keyword injection (if enabled)
    if config.enable_keyword_injection:
        keyword_analysis = analyze_keyword_gaps(job_keywords, current, master_resume)
        if keyword_analysis.injectable_keywords:
            logger.info(
                "Injecting %d keywords: %s",
                len(keyword_analysis.injectable_keywords),
                keyword_analysis.injectable_keywords,
            )
            attempts += 1
            before = _deep_copy(current)
            try:
                candidate = await inject_keywords(
                    current,
                    keyword_analysis.injectable_keywords,
                    master_resume,
                    job_description,
                )
                current = finalize_ai_resume(initial_tailored, candidate)
                if current != before:
                    passes += 1
            except (AIOperationDeadlineExceeded, PromptSizeError):
                raise
            except Exception as e:
                logger.warning("Keyword injection failed: %s", e)
                current = before

    # The keyword writer is the last whole-resume author. Re-apply the source
    # contract immediately after it so later deterministic cleanup and
    # alignment can still remove disallowed content.
    current = finalize_ai_resume(initial_tailored, current)

    # Pass 2: AI phrase removal and polish (local, no LLM call)
    if config.enable_ai_phrase_removal:
        attempts += 1
        before = _deep_copy(current)
        current, removed = remove_ai_phrases(current, job_description)
        ai_phrases_found.extend(removed)
        if current != before:
            logger.info("Removed %d AI phrases: %s", len(removed), removed)
            passes += 1

    # Pass 3: Master alignment validation
    # LLM-008: Alignment validation is MANDATORY - not optional fallback
    if config.enable_master_alignment_check:
        attempts += 1
        alignment = validate_master_alignment(
            current,
            master_resume,
            allowed_new_skills=_extract_jd_skill_keys(
                job_keywords,
                job_description,
            ),
        )
        if not alignment.is_aligned:
            # Count critical violations
            critical_violations = [
                v for v in alignment.violations if v.severity == "critical"
            ]
            logger.warning(
                "Alignment violations found: %d total, %d critical",
                len(alignment.violations),
                len(critical_violations),
            )

            before = _deep_copy(current)
            current = fix_alignment_violations(current, alignment.violations)
            if current != before:
                passes += 1
            after = validate_master_alignment(
                current,
                master_resume,
                allowed_new_skills=_extract_jd_skill_keys(
                    job_keywords, job_description
                ),
            )
            remaining = {
                (v.field_path, v.violation_type, v.value)
                for v in after.violations
                if v.severity == "critical"
            }
            alignment_fixed = sum(
                (v.field_path, v.violation_type, v.value) not in remaining
                for v in critical_violations
            )

    # Calculate final match percentage
    final_match = calculate_keyword_match(current, job_keywords)

    return RefinementResult(
        refined_data=current,
        passes_completed=passes,
        passes_attempted=attempts,
        keywords_applied=[
            keyword
            for keyword in (
                keyword_analysis.injectable_keywords if keyword_analysis else []
            )
            if _keyword_in_text(keyword, _extract_all_text(current))
        ],
        alignment_violations_fixed=alignment_fixed,
        keyword_analysis=keyword_analysis,
        alignment_report=alignment,
        ai_phrases_removed=ai_phrases_found,
        final_match_percentage=final_match,
    )


def analyze_keyword_gaps(
    jd_keywords: dict[str, Any],
    tailored: dict[str, Any],
    master: dict[str, Any],
) -> KeywordGapAnalysis:
    """Analyze which JD keywords are missing from the tailored resume.

    Args:
        jd_keywords: Extracted job keywords with required_skills, preferred_skills, etc.
        tailored: Current tailored resume data
        master: Master resume data (source of truth)

    Returns:
        KeywordGapAnalysis with missing, injectable, and non-injectable keywords
    """
    # Extract text content from resumes
    tailored_text = _extract_all_text(tailored).lower()
    master_text = _extract_all_text(master).lower()

    # Get all keywords from JD
    all_jd_keywords: set[str] = set()
    all_jd_keywords.update(jd_keywords.get("required_skills", []))
    all_jd_keywords.update(jd_keywords.get("preferred_skills", []))
    all_jd_keywords.update(jd_keywords.get("keywords", []))

    # Find missing keywords
    missing: list[str] = []
    injectable: list[str] = []
    non_injectable: list[str] = []

    for keyword in all_jd_keywords:
        if not _keyword_in_text(keyword, tailored_text):
            missing.append(keyword)
            if _keyword_in_text(keyword, master_text):
                injectable.append(keyword)
            else:
                non_injectable.append(keyword)

    # Calculate percentages
    total = len(all_jd_keywords) if all_jd_keywords else 1
    current_match = (total - len(missing)) / total * 100
    potential_match = (total - len(non_injectable)) / total * 100

    return KeywordGapAnalysis(
        missing_keywords=missing,
        injectable_keywords=injectable,
        non_injectable_keywords=non_injectable,
        current_match_percentage=current_match,
        potential_match_percentage=potential_match,
    )


def remove_ai_phrases(
    data: dict[str, Any],
    job_description: str = "",
) -> tuple[dict[str, Any], list[str]]:
    """Remove AI-generated phrases from resume content.

    This is a local operation that doesn't require an LLM call.
    It performs case-insensitive replacement of blacklisted phrases.
    Phrases that appear in the job description are protected from removal.

    Args:
        data: Resume data dictionary
        job_description: Job description text; phrases found here are skipped

    Returns:
        Tuple of (cleaned data, list of removed phrases)
    """
    # Build set of JD-protected phrases
    jd_lower = job_description.lower()
    jd_protected: set[str] = set()
    for phrase in AI_PHRASE_BLACKLIST:
        if phrase.lower() in jd_lower:
            jd_protected.add(phrase.lower())

    if jd_protected:
        logger.info("JD-protected phrases (skipping removal): %s", jd_protected)

    # Use a set to avoid duplicate tracking
    removed: set[str] = set()

    def clean_text(text: str) -> str:
        cleaned = text
        for phrase in AI_PHRASE_BLACKLIST:
            # Skip phrases that appear in the job description
            if phrase.lower() in jd_protected:
                continue
            if phrase.lower() in cleaned.lower():
                removed.add(phrase)
                replacement = AI_PHRASE_REPLACEMENTS.get(phrase.lower(), "")
                # Case-insensitive replacement
                pattern = re.compile(re.escape(phrase), re.IGNORECASE)
                cleaned = pattern.sub(replacement, cleaned)
        return cleaned

    def clean_recursive(obj: Any) -> Any:
        if isinstance(obj, str):
            return clean_text(obj)
        elif isinstance(obj, list):
            return [clean_recursive(item) for item in obj]
        elif isinstance(obj, dict):
            return {k: clean_recursive(v) for k, v in obj.items()}
        return obj

    cleaned_data = clean_recursive(data)
    return cleaned_data, list(removed)


def validate_master_alignment(
    tailored: dict[str, Any],
    master: dict[str, Any],
    allowed_new_skills: set[str] | None = None,
) -> AlignmentReport:
    """Verify tailored resume doesn't contain fabricated content.

    Checks that all skills, certifications, and work experience companies
    in the tailored resume exist in the master resume.

    Args:
        tailored: Tailored resume data
        master: Master resume data (source of truth)

    Returns:
        AlignmentReport with violations and confidence score
    """
    violations: list[AlignmentViolation] = []
    tailored_document = migrate_document(tailored)
    master_document = migrate_document(master)

    # Check short values (skills, certifications, languages, awards — whatever
    # the user's TAGS/GROUPS sections hold). Any value present in the tailored
    # document but not the master is a candidate fabrication.
    tailored_values = {
        value.lower() for value in skill_values(tailored_document) if value
    }
    master_values = {value.lower() for value in skill_values(master_document) if value}
    allowed_skills = {
        _normalize_skill_key(skill)
        for skill in (allowed_new_skills or set())
        if isinstance(skill, str) and skill.strip()
    }
    master_full_text = _extract_all_text(master).lower()

    for value in tailored_values - master_values:
        if _normalize_skill_key(value) in allowed_skills:
            continue
        # Substring/containment ("Python" in "Python 3.x") or a mention
        # anywhere in the master's prose downgrades this to a variant.
        has_substring_match = any(
            value in other or other in value for other in master_values if other
        )
        grounded = has_substring_match or _keyword_in_text(value, master_full_text)
        violations.append(
            AlignmentViolation(
                field_path="sections.values",
                violation_type="skill_variant" if grounded else "fabricated_skill",
                value=value,
                severity="info" if grounded else "critical",
            )
        )

    # Check entry identity: tailoring may rewrite prose, never invent an
    # employer, institution or project.
    master_subtitles = {
        entry.subtitle.lower()
        for _, _, entry in iter_entries(master_document)
        if entry.subtitle
    }
    for section, _, entry in iter_entries(tailored_document):
        subtitle = entry.subtitle.lower()
        if subtitle and subtitle not in master_subtitles:
            violations.append(
                AlignmentViolation(
                    field_path=f"sections.{section.key}.entries",
                    violation_type="fabricated_company",
                    value=subtitle,
                    severity="critical",
                )
            )

    is_aligned = len([v for v in violations if v.severity == "critical"]) == 0
    confidence = 1.0 - (len(violations) * 0.1)  # Decrease confidence per violation

    return AlignmentReport(
        is_aligned=is_aligned,
        violations=violations,
        confidence_score=max(0.0, confidence),
    )


def _prepare_job_description(job_description: str) -> tuple[str, bool]:
    """LLM-012: Prepare job description for prompt, with truncation warning.

    Returns:
        Tuple of (truncated_text, was_truncated)
    """
    was_truncated = len(job_description) > MAX_JD_LENGTH

    if was_truncated:
        logger.warning(
            "Job description truncated from %d to %d characters",
            len(job_description),
            MAX_JD_LENGTH,
        )

    return job_description[:MAX_JD_LENGTH], was_truncated


def _validate_resume_structure(data: dict[str, Any]) -> bool:
    """LLM-014: Validate the document survives keyword injection.

    Returns:
        True if structure is valid, False otherwise.
    """
    try:
        ResumeDocument.model_validate(data)
    except ValidationError as error:
        logger.warning("Resume structure invalid after injection: %s", error)
        return False
    return True


def _restore_bullet_styles(
    original: dict[str, Any], improved: dict[str, Any]
) -> dict[str, Any]:
    """Restore per-bullet styles the LLM dropped (H-04).

    Style is a property of the bullet now, so it can no longer *desync* from
    its text — but a model rewriting a bullet can still return it with the
    default style and silently turn a user's plain paragraph row into a
    bulleted one. Rows are matched by index within their entry, which is the
    same contract the editor uses.
    """
    source = migrate_document(original)
    result = migrate_document(improved)
    source_by_key = {section.key: section for section in source.sections}

    for section in result.sections:
        origin = source_by_key.get(section.key)
        if origin is None or section.kind is not SectionKind.ENTRIES:
            continue
        for index, entry in enumerate(section.entries):
            if index >= len(origin.entries):
                continue
            origin_bullets = origin.entries[index].bullets
            for row, bullet in enumerate(entry.bullets):
                if row < len(origin_bullets):
                    bullet.style = origin_bullets[row].style
    return result.model_dump(mode="json")


async def inject_keywords(
    tailored: dict[str, Any],
    keywords_to_inject: list[str],
    master: dict[str, Any],
    job_description: str,
) -> dict[str, Any]:
    """Use LLM to inject missing keywords into appropriate sections.

    Args:
        tailored: Current tailored resume
        keywords_to_inject: Keywords that are in master but missing from tailored
        master: Master resume (source of truth)
        job_description: Job description for context

    Returns:
        Updated resume data with keywords injected

    LLM-012: Truncates job description with warning.
    LLM-014: Validates result structure before returning.
    """
    # LLM-012: Prepare job description with truncation handling
    truncated_jd, was_truncated = _prepare_job_description(job_description)
    if was_truncated:
        logger.info(
            "Job description was truncated for keyword injection (original: %d chars)",
            len(job_description),
        )

    document = migrate_document(tailored)
    prompt = KEYWORD_INJECTION_PROMPT.format(
        keywords_to_inject=json.dumps(keywords_to_inject),
        current_resume=json.dumps(tailored),
        master_resume=json.dumps(master),
        job_description=truncated_jd,
        document_schema=describe_document_schema(document),
    )

    populated = {
        section.key
        for section in document.sections
        if section.kind is SectionKind.ENTRIES and section.entries
    }

    def validate_writer_result(result: dict[str, Any]) -> dict[str, Any]:
        if not _validate_resume_structure(result):
            raise ValueError("Keyword injection corrupted resume structure")
        returned = migrate_document(result)
        for key in populated:
            section = returned.section(key)
            if section is None or not section.entries:
                raise ValueError(f"Keyword injection omitted populated {key}")
        return result

    try:
        result = await complete_json(
            prompt=prompt,
            system_prompt=(
                "You are a resume editor. Inject keywords naturally without adding "
                "fabricated content. Return only valid JSON matching the input schema."
            ),
            max_tokens=8192,
            response_validator=validate_writer_result,
        )

        # LLM-014: Validate the result maintains required structure
        if not isinstance(result, dict):
            logger.warning("Keyword injection returned non-dict: %s", type(result))
            return tailored

        if not _validate_resume_structure(result):
            logger.warning(
                "Keyword injection corrupted resume structure, using original"
            )
            return tailored

        # H-04: the prompt asks the model to preserve bullet styles, but a
        # prompt is not a guarantee. Restore them locally, matching the
        # defence-in-depth pattern the improve pipeline already uses for
        # dates, skills and the header.
        return _restore_bullet_styles(tailored, result)

    except (AIOperationDeadlineExceeded, PromptSizeError):
        raise
    except Exception as e:
        logger.warning("Keyword injection failed: %s", e)
        return tailored


def fix_alignment_violations(
    tailored: dict[str, Any],
    violations: list[AlignmentViolation],
) -> dict[str, Any]:
    """Remove or correct alignment violations.

    This is a local operation that removes fabricated content.

    Args:
        tailored: Tailored resume data
        violations: List of alignment violations to fix

    Returns:
        Fixed resume data
    """
    document = migrate_document(tailored)
    fabricated_values = {
        violation.value.lower()
        for violation in violations
        if violation.severity == "critical"
        and violation.violation_type in ("fabricated_skill", "fabricated_cert")
    }
    fabricated_subtitles = {
        violation.value.lower()
        for violation in violations
        if violation.severity == "critical"
        and violation.violation_type == "fabricated_company"
    }
    if not fabricated_values and not fabricated_subtitles:
        return _deep_copy(tailored)

    for section in document.sections:
        if section.kind is SectionKind.TAGS:
            section.tags = [
                value for value in section.tags if value.lower() not in fabricated_values
            ]
        elif section.kind is SectionKind.GROUPS:
            for group in section.groups:
                group.values = [
                    value
                    for value in group.values
                    if value.lower() not in fabricated_values
                ]
        elif section.kind is SectionKind.ENTRIES and fabricated_subtitles:
            kept = [
                entry
                for entry in section.entries
                if entry.subtitle.lower() not in fabricated_subtitles
            ]
            if len(kept) != len(section.entries):
                # SVC-002: an invented employer/institution is removed outright.
                logger.error(
                    "Critical: removed %d fabricated entries from %s",
                    len(section.entries) - len(kept),
                    section.key,
                )
            section.entries = kept

    return document.model_dump(mode="json")


def calculate_keyword_match(
    resume: dict[str, Any],
    jd_keywords: dict[str, Any],
) -> float:
    """Calculate keyword match percentage.

    Args:
        resume: Resume data dictionary
        jd_keywords: Extracted job keywords

    Returns:
        Match percentage (0.0 to 100.0)
    """
    resume_text = _extract_all_text(resume).lower()

    all_keywords: set[str] = set()
    all_keywords.update(jd_keywords.get("required_skills", []))
    all_keywords.update(jd_keywords.get("preferred_skills", []))
    all_keywords.update(jd_keywords.get("keywords", []))

    # SVC-009: Return 0% if no keywords (not 100% - that's misleading)
    if not all_keywords:
        logger.warning("No keywords found in job description")
        return 0.0

    # SVC-010: Use word boundary matching instead of substring
    matched = sum(1 for kw in all_keywords if _keyword_in_text(kw, resume_text))
    return (matched / len(all_keywords)) * 100


def _extract_all_text(data: dict[str, Any]) -> str:
    """Extract all text content from resume data for keyword matching.

    SVC-011: Uses caching to avoid repeated extraction on same resume data.

    Args:
        data: Resume data dictionary

    Returns:
        Concatenated text from all resume sections
    """
    # Create a cache key from the data
    data_json = json.dumps(data, sort_keys=True, default=str)
    return _extract_all_text_cached(data_json)


@lru_cache(maxsize=100)
def _extract_all_text_cached(data_json: str) -> str:
    """Cached implementation of text extraction.

    SVC-011: LRU cache avoids re-extracting text from the same resume
    multiple times during a single refinement pass.
    """
    parts = list(document_text_fragments(migrate_document(json.loads(data_json))))
    return " ".join(part for part in parts if part)


def _deep_copy(data: dict[str, Any]) -> dict[str, Any]:
    """Create a deep copy of a dictionary.

    Uses copy.deepcopy for reliability. JSON serialization is avoided
    because it can't handle all Python types and loses type information.
    """
    return copy.deepcopy(data)
