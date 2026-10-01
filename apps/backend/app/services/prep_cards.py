"""Interview-prep flashcard generation, answering and critique.

Separate from ``app/services/interview_prep.py`` (the per-resume builder tab)
and uses its own ``schema_type`` values: ``llm.py`` keys its truncation
detection on the shape behind ``"interview_prep"``, so reusing that name here
would make every response look truncated.
"""

from typing import Any

from app.ai_limits import MAX_JOB_CHARACTERS, validate_source_size
from app.llm import (
    complete_json,
    get_llm_config,
    get_model_name,
    get_safe_max_tokens,
)
from app.prompts import (
    PREP_CARD_ANSWER_PROMPT,
    PREP_CARD_CRITIQUE_PROMPT,
    PREP_CARD_GENERATE_PROMPT,
)
from app.schemas import (
    PrepCardAnswer,
    PrepCardCategory,
    PrepCardCritique,
    PrepCardGenerateResponse,
    PrepCardProposal,
)
from app.services.prompt_bounds import (
    JOB_DESCRIPTION_PROMPT_CHAR_LIMIT,
    interview_coach_system_prompt,
    serialize_resume_data_for_prompt,
    truncate_text_for_prompt,
)


# What each category means, injected into the generate and answer prompts.
_CATEGORY_INSTRUCTIONS: dict[str, str] = {
    "technical": (
        "Ask technical questions about the technologies, systems and engineering "
        "practices evidenced in the resume. Each question must be answerable from "
        "general engineering knowledge; do not ask the candidate to recall private "
        "details."
    ),
    "personal": (
        "Ask questions about the candidate themselves: their resume, career choices, "
        "projects, gaps, motivations and the stories behind the listed roles. Ground "
        "every question in the resume evidence."
    ),
}

_NO_JOB_CONTEXT = (
    "No specific job description was provided. Ask role-agnostic questions "
    "grounded in the resume."
)


def _category_instruction(category: str) -> str:
    return _CATEGORY_INSTRUCTIONS.get(category, _CATEGORY_INSTRUCTIONS["technical"])


def _job_context(job_description: str | None) -> str:
    """Bound the optional job description, or say there isn't one."""
    if job_description is None:
        return _NO_JOB_CONTEXT
    validate_source_size(job_description, MAX_JOB_CHARACTERS)
    return truncate_text_for_prompt(job_description, JOB_DESCRIPTION_PROMPT_CHAR_LIMIT)


async def generate_prep_cards(
    *,
    category: str,
    resume_data: dict[str, Any],
    job_description: str | None,
    count: int,
    output_language: str,
) -> list[PrepCardProposal]:
    """Propose ``count`` questions for one category. Persists nothing."""
    prompt = PREP_CARD_GENERATE_PROMPT.format(
        output_language=output_language,
        category_instruction=_category_instruction(category),
        count=count,
        resume_data=serialize_resume_data_for_prompt(resume_data),
        job_context=_job_context(job_description),
    )
    config = get_llm_config()
    max_tokens = get_safe_max_tokens(
        get_model_name(config),
        requested=4096,
        config=config,
    )

    result = await complete_json(
        prompt=prompt,
        system_prompt=interview_coach_system_prompt(output_language),
        max_tokens=max_tokens,
        schema_type="prep_card_generate",
    )

    parsed = PrepCardGenerateResponse.model_validate(result)
    # The requested category is authoritative: the model is told which kind of
    # question to ask, but its echo of that choice is never trusted.
    requested = PrepCardCategory(category)
    return [
        proposal.model_copy(update={"category": requested})
        for proposal in parsed.proposals[:count]
    ]


async def answer_prep_card(
    *,
    category: str,
    question: str,
    resume_data: dict[str, Any],
    job_description: str | None,
    output_language: str,
) -> PrepCardAnswer:
    """Author the back of one card: answer, explanation and examples."""
    prompt = PREP_CARD_ANSWER_PROMPT.format(
        output_language=output_language,
        category_instruction=_category_instruction(category),
        question=question,
        resume_data=serialize_resume_data_for_prompt(resume_data),
        job_context=_job_context(job_description),
    )
    config = get_llm_config()
    max_tokens = get_safe_max_tokens(
        get_model_name(config),
        requested=2048,
        config=config,
    )

    result = await complete_json(
        prompt=prompt,
        system_prompt=interview_coach_system_prompt(output_language),
        max_tokens=max_tokens,
        schema_type="prep_card_answer",
    )

    return PrepCardAnswer.model_validate(result)


async def critique_prep_answer(
    *,
    question: str,
    my_answer: str,
    model_answer: str | None,
    resume_data: dict[str, Any],
    output_language: str,
) -> PrepCardCritique:
    """Score and improve the answer the owner wrote themselves."""
    prompt = PREP_CARD_CRITIQUE_PROMPT.format(
        output_language=output_language,
        question=question,
        my_answer=truncate_text_for_prompt(
            my_answer, JOB_DESCRIPTION_PROMPT_CHAR_LIMIT
        ),
        model_answer=model_answer or "",
        resume_data=serialize_resume_data_for_prompt(resume_data),
    )
    config = get_llm_config()
    max_tokens = get_safe_max_tokens(
        get_model_name(config),
        requested=2048,
        config=config,
    )

    result = await complete_json(
        prompt=prompt,
        system_prompt=interview_coach_system_prompt(output_language),
        max_tokens=max_tokens,
        schema_type="prep_card_critique",
    )

    return PrepCardCritique.model_validate(result)
