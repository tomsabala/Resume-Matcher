"""AI-powered resume enrichment endpoints."""

import asyncio
import copy
import json
import logging
import re
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from app.ai_limits import MAX_ITEM_WORKERS, PromptSizeError, require_source_size
from app.ai_budget import (
    AIOperationDeadlineExceeded,
    AIOperationRoute,
    remaining_timeout,
)
from app.config_cache import get_content_language
from app.database import DatabaseBusyError, db
from app.llm import complete_json
from app.prompts.enrichment import (
    ANALYZE_RESUME_PROMPT,
    ENHANCE_DESCRIPTION_PROMPT,
    REGENERATE_ITEM_PROMPT,
    REGENERATE_SKILLS_PROMPT,
)
from app.prompts.templates import get_language_name
from app.schemas.document import (
    Bullet,
    Entry,
    ResumeDocument,
    Section,
    SectionKind,
    TagGroup,
    migrate_document,
)
from app.services.document_diff import diff_value_lists
from app.schemas.enrichment import (
    AnalysisResponse,
    AnswerInput,
    ApplyEnhancementsRequest,
    EnhancedDescription,
    EnhanceRequest,
    EnhancementItemError,
    EnhancementPreview,
    EnrichmentItem,
    EnrichmentQuestion,
    RegenerateItemError,
    RegenerateItemInput,
    RegenerateRequest,
    RegenerateResponse,
    RegeneratedItem,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    route_class=AIOperationRoute, prefix="/enrichment", tags=["Enrichment"]
)


def _validate_text_replacements(
    result: dict[str, Any],
    field_names: tuple[str, ...],
) -> dict[str, Any]:
    """Require a non-empty replacement list without coercing invalid leaves."""
    present_fields = [name for name in field_names if name in result]
    if not present_fields:
        raise ValueError(f"LLM response is missing '{field_names[0]}'")
    for field in present_fields:
        replacements = result[field]
        if isinstance(replacements, list) and replacements and all(
            isinstance(item, str) and item.strip() for item in replacements
        ):
            return {
                **result,
                field_names[0]: [item.strip() for item in replacements],
            }
    raise ValueError(
        f"LLM response fields {present_fields!r} must contain non-empty text lists"
    )


def _validate_enhancement_result(result: dict[str, Any]) -> dict[str, Any]:
    """Validate enhanced bullets, including the legacy response field name."""
    return _validate_text_replacements(
        result,
        ("additional_bullets", "enhanced_description"),
    )


def _validate_regenerated_item_result(result: dict[str, Any]) -> dict[str, Any]:
    """Validate regenerated experience or project bullets."""
    return _validate_text_replacements(result, ("new_bullets",))


def _validate_regenerated_skills_result(result: dict[str, Any]) -> dict[str, Any]:
    """Validate regenerated skill names."""
    return _validate_text_replacements(result, ("new_skills",))


def _validate_analysis_result(result: dict[str, Any]) -> dict[str, Any]:
    """Require the explicit enrichment-analysis contract; empty lists are valid."""
    if "items_to_enrich" not in result or "questions" not in result:
        raise ValueError("LLM analysis response is missing required list fields")
    return AnalysisResponse.model_validate(result).model_dump()


def _split_item_id(item_id: str) -> tuple[str, str] | None:
    """Parse an item id of the form ``<section_key>:<entry_id>``."""
    if not isinstance(item_id, str) or ":" not in item_id:
        return None
    section_key, entry_id = item_id.split(":", 1)
    if not section_key or not entry_id:
        return None
    return section_key, entry_id


def _find_entry(
    document: ResumeDocument, item_id: str
) -> tuple[Section, Entry] | None:
    """Resolve ``<section_key>:<entry_id>`` to its live section and entry.

    Ids are stable for the entry's life, so an entry reordered between
    preview and apply still resolves to the same content — the positional
    ``exp_0`` scheme silently retargeted a different job.
    """
    parsed = _split_item_id(item_id)
    if parsed is None:
        return None
    section_key, entry_id = parsed
    section = document.section(section_key)
    if section is None or section.kind is not SectionKind.ENTRIES:
        return None
    entry = next((e for e in section.entries if e.id == entry_id), None)
    return (section, entry) if entry is not None else None


def _find_value_list(
    document: ResumeDocument, item_id: str
) -> tuple[Section, TagGroup | None] | None:
    """Resolve ``<key>:#tags`` or ``<key>:#group:<index>`` to its value list.

    Returns the owning section and, for a grouped list, the group; ``None``
    for the group means the section's own ``tags``.
    """
    parsed = _split_item_id(item_id)
    if parsed is None:
        return None
    section_key, selector = parsed
    section = document.section(section_key)
    if section is None:
        return None
    if selector == "#tags" and section.kind is SectionKind.TAGS:
        return section, None
    if selector.startswith("#group:") and section.kind is SectionKind.GROUPS:
        try:
            index = int(selector.removeprefix("#group:"))
        except ValueError:
            return None
        if 0 <= index < len(section.groups):
            return section, section.groups[index]
    return None


def _extract_item_from_resume(processed_data: dict, item_id: str) -> dict:
    """Derive item details from resume data using the item_id pattern.

    Avoids a redundant LLM analysis call when the frontend already knows
    which item each answer belongs to.
    """
    found = _find_entry(migrate_document(processed_data), item_id)
    if found is None:
        return {}
    section, entry = found
    return {
        "item_id": item_id,
        "item_type": "entry",
        "section_heading": section.heading or section.key,
        "title": entry.title,
        "subtitle": entry.subtitle,
        "current_description": [bullet.text for bullet in entry.bullets],
    }


@router.post("/analyze/{resume_id}", response_model=AnalysisResponse)
async def analyze_resume(resume_id: str) -> AnalysisResponse:
    """Analyze a resume to identify items that need enrichment.

    Uses AI to examine Experience and Projects sections for weak,
    vague, or incomplete descriptions and generates clarifying questions.
    """
    # Fetch resume
    resume = await db.get_resume(resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    # Get processed data
    processed_data = resume.get("processed_data")
    if not processed_data:
        raise HTTPException(
            status_code=400,
            detail="Resume has no processed data. Please re-upload the resume.",
        )

    require_source_size(processed_data)

    # Build prompt with content language
    resume_json = json.dumps(processed_data)
    language = get_content_language()
    output_language = get_language_name(language)
    prompt = ANALYZE_RESUME_PROMPT.format(
        resume_json=resume_json,
        output_language=output_language
    )

    try:
        # Call LLM with increased max_tokens for non-English languages
        result = await asyncio.wait_for(
            complete_json(
                prompt,
                max_tokens=8192,
                schema_type="enrichment",
                response_validator=_validate_analysis_result,
            ),
            timeout=remaining_timeout(),
        )
        result = _validate_analysis_result(result)

        # Parse response into schema objects
        items_to_enrich = [
            EnrichmentItem(
                item_id=item.get("item_id", f"item_{i}"),
                item_type=item.get("item_type", "entry"),
                section_heading=item.get("section_heading", ""),
                title=item.get("title", ""),
                subtitle=item.get("subtitle"),
                current_description=item.get("current_description", []),
                weakness_reason=item.get("weakness_reason", ""),
            )
            for i, item in enumerate(result.get("items_to_enrich", []))
        ]

        questions = [
            EnrichmentQuestion(
                question_id=q.get("question_id", f"q_{i}"),
                item_id=q.get("item_id", ""),
                question=q.get("question", ""),
                placeholder=q.get("placeholder", ""),
            )
            for i, q in enumerate(result.get("questions", []))
        ]

        return AnalysisResponse(
            items_to_enrich=items_to_enrich,
            questions=questions,
            analysis_summary=result.get("analysis_summary"),
        )

    except PromptSizeError:
        raise
    except asyncio.TimeoutError:
        logger.error("Resume analysis timed out for resume %s", resume_id)
        raise HTTPException(
            status_code=504,
            detail="Resume analysis timed out. Please try again with a shorter resume or a faster model.",
        )
    except ValueError as e:
        logger.error("Resume analysis failed (content): %s", e)
        raise HTTPException(
            status_code=422,
            detail="The AI returned an unreadable response. Please try again or switch models.",
        )
    except Exception as e:
        logger.error("Resume analysis failed: %s", e)
        raise HTTPException(
            status_code=500,
            detail="Failed to analyze resume. Please try again.",
        )


@router.post("/enhance", response_model=EnhancementPreview)
async def generate_enhancements(request: EnhanceRequest) -> EnhancementPreview:
    """Generate enhanced descriptions from user answers.

    Takes the answers to clarifying questions and uses AI to generate
    improved description bullets for each item.
    """
    # Fetch resume
    resume = await db.get_resume(request.resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    processed_data = resume.get("processed_data")
    if not processed_data:
        raise HTTPException(
            status_code=400,
            detail="Resume has no processed data.",
        )

    require_source_size(processed_data)

    # Group answers by item_id.
    # When all answers carry item_id (from the analysis step), we can skip
    # the expensive re-analysis LLM call and derive item details from the
    # resume's processed_data directly.
    answers_by_item: dict[str, list[AnswerInput]] = {}
    item_details: dict[str, dict] = {}
    # question_id → question dict, populated only in the legacy path
    questions_by_id: dict[str, dict] = {}

    if all(a.item_id for a in request.answers) and all(
        _extract_item_from_resume(processed_data, a.item_id or "")
        for a in request.answers
    ):
        # Fast path — no re-analysis needed
        for answer in request.answers:
            item_id = answer.item_id or ""
            answers_by_item.setdefault(item_id, []).append(answer)
            if item_id not in item_details:
                item_details[item_id] = _extract_item_from_resume(
                    processed_data, item_id
                )
    else:
        # Legacy path — re-analyze to get question-to-item mapping
        resume_json = json.dumps(processed_data)
        language = get_content_language()
        output_language = get_language_name(language)
        analysis_prompt = ANALYZE_RESUME_PROMPT.format(
            resume_json=resume_json,
            output_language=output_language,
        )

        try:
            analysis_result = await asyncio.wait_for(
                complete_json(
                    analysis_prompt,
                    max_tokens=8192,
                    schema_type="enrichment",
                    response_validator=_validate_analysis_result,
                ),
                timeout=remaining_timeout(),
            )
            analysis_result = _validate_analysis_result(analysis_result)
        except PromptSizeError:
            raise
        except asyncio.TimeoutError:
            logger.error("Resume re-analysis timed out for resume %s", request.resume_id)
            raise HTTPException(
                status_code=504,
                detail="Resume analysis timed out. Please try again with a shorter resume or a faster model.",
            )
        except ValueError as e:
            logger.error("Resume re-analysis failed (content): %s", e)
            raise HTTPException(
                status_code=422,
                detail="The AI returned an unreadable response. Please try again or switch models.",
            )
        except Exception as e:
            logger.error("Failed to re-analyze resume: %s", e)
            raise HTTPException(
                status_code=500,
                detail="Failed to process enhancements. Please try again.",
            )

        question_to_item: dict[str, str] = {}
        for q in analysis_result.get("questions", []):
            qid = q.get("question_id", "")
            question_to_item[qid] = q.get("item_id", "")
            questions_by_id[qid] = q

        for item in analysis_result.get("items_to_enrich", []):
            item_id = item.get("item_id", "")
            item_details[item_id] = item

        for answer in request.answers:
            item_id = question_to_item.get(answer.question_id, "")
            if item_id:
                answers_by_item.setdefault(item_id, []).append(answer)

    # Generate enhanced descriptions for each item
    enhancements: list[EnhancedDescription] = []
    errors: list[EnhancementItemError] = []
    first_prompt_error: PromptSizeError | None = None

    for item_id, answers in answers_by_item.items():
        item = item_details.get(item_id, {})
        if not item:
            continue

        # Format answers with their questions for context.
        # In the fast path questions_by_id is empty, so fall back to
        # question_text carried on the AnswerInput itself.
        answers_text = ""
        for answer in answers:
            matching_q = questions_by_id.get(answer.question_id)
            question = (
                matching_q.get("question", "") if matching_q else answer.question_text
            )
            if question:
                answers_text += f"Q: {question}\n"
                answers_text += f"A: {answer.answer}\n\n"
            else:
                answers_text += f"Additional info: {answer.answer}\n\n"

        # Build enhancement prompt with content language
        current_desc = item.get("current_description", [])
        current_desc_text = "\n".join(f"- {d}" for d in current_desc) if current_desc else "(No description)"

        language = get_content_language()
        output_language = get_language_name(language)

        prompt = ENHANCE_DESCRIPTION_PROMPT.format(
            # The prompt wants a human label ("Military Service"), not the
            # machine category.
            item_type=item.get("section_heading") or item.get("item_type", "entry"),
            title=item.get("title", ""),
            subtitle=item.get("subtitle", ""),
            current_description=current_desc_text,
            answers=answers_text.strip(),
            output_language=output_language,
        )

        try:
            result = await complete_json(
                prompt,
                schema_type="diff",
                response_validator=_validate_enhancement_result,
            )
            result = _validate_enhancement_result(result)
            additional_bullets = result["additional_bullets"]

            enhancements.append(
                EnhancedDescription(
                    item_id=item_id,
                    item_type=item.get("item_type", "entry"),
                    section_heading=item.get("section_heading", ""),
                    title=item.get("title", ""),
                    original_description=current_desc,
                    enhanced_description=additional_bullets,  # These are NEW bullets to add
                )
            )
        except AIOperationDeadlineExceeded:
            raise
        except Exception as e:
            logger.warning("Failed to enhance item %s: %s", item_id, e, exc_info=e)
            message = "Failed to enhance this item. Please try again."
            if isinstance(e, PromptSizeError):
                first_prompt_error = first_prompt_error or e
                message = "This item is too large to enhance. Shorten its description or answers."
            errors.append(
                EnhancementItemError(
                    item_id=item_id,
                    item_type=item.get("item_type", "entry"),
                    section_heading=item.get("section_heading", ""),
                    title=item.get("title", ""),
                    subtitle=item.get("subtitle"),
                    message=message,
                )
            )

    if answers_by_item and not enhancements:
        if first_prompt_error is not None:
            raise first_prompt_error
        raise HTTPException(
            status_code=500,
            detail=(
                "Failed to generate enhancements. "
                "Original resume content was preserved."
            ),
        )

    return EnhancementPreview(enhancements=enhancements, errors=errors)


@router.post("/apply/{resume_id}")
async def apply_enhancements(
    resume_id: str, request: ApplyEnhancementsRequest
) -> dict:
    """Apply enhancements to the master resume.

    Updates the resume's Experience and Projects sections with
    the enhanced descriptions.
    """
    # Fetch resume
    resume = await db.get_resume(resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    processed_data = resume.get("processed_data")
    if not processed_data:
        raise HTTPException(
            status_code=400,
            detail="Resume has no processed data.",
        )

    document = migrate_document(processed_data)

    # Apply each enhancement by ADDING new bullets to the existing ones.
    for enhancement in request.enhancements:
        found = _find_entry(document, enhancement.item_id)
        if found is None:
            logger.warning(
                "Could not apply enhancement for unknown item %s",
                enhancement.item_id,
            )
            continue
        _, entry = found
        entry.bullets.extend(
            Bullet(text=text) for text in enhancement.enhanced_description if text.strip()
        )

    updated_data = document.model_dump(mode="json")
    try:
        # Through the version funnel: enrichment used to overwrite the master
        # in place with no snapshot, so a bad enhancement was unrecoverable.
        await db.commit_resume_version(
            resume_id,
            updated_data,
            origin="ai_enrich",
            resume_updates={"content": json.dumps(updated_data, indent=2)},
        )
    except DatabaseBusyError:
        raise
    except Exception as e:
        logger.error(f"Failed to save enhancements to database: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to save enhancements. Please try again.",
        )

    return {
        "message": "Enhancements applied successfully",
        "updated_items": len(request.enhancements),
    }


# ============================================
# AI Regenerate Feature Endpoints
# ============================================


async def _regenerate_experience_or_project(
    item: RegenerateItemInput,
    instruction: str,
    output_language: str,
) -> RegeneratedItem:
    """Regenerate a single experience or project item."""
    current_desc_text = (
        "\n".join(f"- {d}" for d in item.current_content)
        if item.current_content
        else "(No description)"
    )

    prompt = REGENERATE_ITEM_PROMPT.format(
        output_language=output_language,
        item_type=item.item_type,
        title=item.title,
        subtitle=item.subtitle or "",
        current_description=current_desc_text,
        user_instruction=instruction,
    )

    result = await complete_json(
        prompt,
        max_tokens=4096,
        schema_type="diff",
        response_validator=_validate_regenerated_item_result,
    )
    result = _validate_regenerated_item_result(result)
    new_bullets = result["new_bullets"]

    return RegeneratedItem(
        item_id=item.item_id,
        item_type=item.item_type,
        title=item.title,
        subtitle=item.subtitle,
        original_content=item.current_content,
        new_content=new_bullets,
        rows=diff_value_lists(
            item.current_content, new_bullets, path=item.item_id, kind="bullet"
        ),
        diff_summary=str(result.get("change_summary") or ""),
    )


async def _regenerate_skills(
    item: RegenerateItemInput,
    instruction: str,
    output_language: str,
) -> RegeneratedItem:
    """Regenerate the skills section."""
    current_skills_text = ", ".join(item.current_content) if item.current_content else "(No skills)"

    prompt = REGENERATE_SKILLS_PROMPT.format(
        output_language=output_language,
        current_skills=current_skills_text,
        user_instruction=instruction,
    )

    result = await complete_json(
        prompt,
        max_tokens=2048,
        schema_type="diff",
        response_validator=_validate_regenerated_skills_result,
    )
    result = _validate_regenerated_skills_result(result)
    new_skills = result["new_skills"]

    return RegeneratedItem(
        item_id=item.item_id,
        item_type=item.item_type,
        title=item.title,
        subtitle=item.subtitle,
        original_content=item.current_content,
        new_content=new_skills,
        rows=diff_value_lists(
            item.current_content, new_skills, path=item.item_id, kind="tag"
        ),
        diff_summary=str(result.get("change_summary") or ""),
    )


@router.post("/regenerate", response_model=RegenerateResponse)
async def regenerate_items(request: RegenerateRequest) -> RegenerateResponse:
    """Regenerate selected resume items based on user feedback.

    Takes selected items (experience, projects, skills) and a user instruction,
    then uses AI to rewrite the content addressing the user's concerns.
    """
    # Validate resume exists
    resume = await db.get_resume(request.resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    if not request.items:
        raise HTTPException(status_code=400, detail="No items selected for regeneration")

    # Get language name for LLM
    output_language = get_language_name(request.output_language)

    # A bounded collection may queue work, but at most four items call AI.
    semaphore = asyncio.Semaphore(MAX_ITEM_WORKERS)

    async def regenerate_one(item: RegenerateItemInput) -> RegeneratedItem:
        async with semaphore:
            if item.item_type == "values":
                return await _regenerate_skills(
                    item, request.instruction, output_language
                )
            return await _regenerate_experience_or_project(
                item, request.instruction, output_language
            )

    results = await asyncio.gather(
        *(regenerate_one(item) for item in request.items), return_exceptions=True
    )

    regenerated_items: list[RegeneratedItem] = []
    errors: list[RegenerateItemError] = []

    for item, result in zip(request.items, results):
        if isinstance(
            result,
            (asyncio.CancelledError, AIOperationDeadlineExceeded, PromptSizeError),
        ):
            raise result
        if isinstance(result, Exception):
            logger.error(
                "Failed to regenerate item. "
                f"resume_id={request.resume_id} item_id={item.item_id} item_type={item.item_type}",
                exc_info=result,
            )
            errors.append(
                RegenerateItemError(
                    item_id=item.item_id,
                    item_type=item.item_type,
                    title=item.title,
                    subtitle=item.subtitle,
                    message="Failed to regenerate this item. Please try again.",
                )
            )
            continue

        regenerated_items.append(result)

    if not regenerated_items:
        raise HTTPException(
            status_code=500,
            detail="Failed to regenerate content. Please try again.",
        )

    return RegenerateResponse(regenerated_items=regenerated_items, errors=errors)


@router.post("/apply-regenerated/{resume_id}")
async def apply_regenerated_items(
    resume_id: str, regenerated_items: list[RegeneratedItem]
) -> dict:
    """Apply regenerated items to the master resume.

    Updates the resume's Experience, Projects, and Skills sections with
    the regenerated descriptions.
    """
    # Fetch resume
    resume = await db.get_resume(resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    processed_data = resume.get("processed_data")
    if not processed_data:
        raise HTTPException(
            status_code=400,
            detail="Resume has no processed data.",
        )

    document = migrate_document(processed_data)

    def _normalize_lines(value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [text for text in (str(item).strip() for item in value) if text]
        text = str(value).strip()
        return [text] if text else []

    def _lines_equal(left: object, right: object) -> bool:
        return [line.casefold() for line in _normalize_lines(left)] == [
            line.casefold() for line in _normalize_lines(right)
        ]

    apply_failures: list[str] = []

    # Apply each regenerated item (all-or-nothing to avoid corrupting user
    # data). Targets resolve by stable id, so the only remaining check is that
    # the content the user reviewed is still the content on disk.
    for item in regenerated_items:
        entry_target = _find_entry(document, item.item_id)
        if entry_target is not None:
            _, entry = entry_target
            if not _lines_equal(
                [bullet.text for bullet in entry.bullets], item.original_content
            ):
                apply_failures.append(item.item_id)
                continue
            styles = [bullet.style for bullet in entry.bullets]
            entry.bullets = [
                Bullet(
                    text=text,
                    style=styles[index] if index < len(styles) else "bullet",
                )
                for index, text in enumerate(item.new_content)
            ]
            continue

        values_target = _find_value_list(document, item.item_id)
        if values_target is None:
            logger.warning(
                "apply-regenerated: unknown item. resume_id=%s item_id=%s",
                resume_id,
                item.item_id,
            )
            apply_failures.append(item.item_id)
            continue
        section, group = values_target
        current = section.tags if group is None else group.values
        if not _lines_equal(current, item.original_content):
            apply_failures.append(item.item_id)
            continue
        new_values = _normalize_lines(item.new_content)
        if group is None:
            section.tags = new_values
        else:
            group.values = new_values


    if apply_failures:
        logger.warning(
            "apply-regenerated: refusing to apply due to mismatched/missing items. "
            f"resume_id={resume_id} item_ids={apply_failures}"
        )
        raise HTTPException(
            status_code=409,
            detail=(
                "Resume content changed or could not be uniquely matched. "
                "Please regenerate and try again."
            ),
        )

    # Update the resume in database, through the version funnel so a
    # regeneration the user dislikes can be restored away from.
    updated_data = document.model_dump(mode="json")
    try:
        await db.commit_resume_version(
            resume_id,
            updated_data,
            origin="ai_enrich",
            resume_updates={"content": json.dumps(updated_data, indent=2)},
        )
    except DatabaseBusyError:
        raise
    except Exception as e:
        logger.error(f"Failed to save regenerated content to database: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to save changes. Please try again.",
        )

    return {
        "message": "Changes applied successfully",
        "updated_items": len(regenerated_items),
    }
