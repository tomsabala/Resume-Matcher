"""Interview preparation generation service."""

from typing import Any

from app.llm import (
    complete_json,
    get_llm_config,
    get_model_name,
    get_safe_max_tokens,
)
from app.prompts import INTERVIEW_PREP_PROMPT, OUTPUT_LANGUAGE
from app.schemas import InterviewPrepData
from app.services.prompt_bounds import (
    JOB_DESCRIPTION_PROMPT_CHAR_LIMIT,
    serialize_resume_data_for_prompt,
    truncate_text_for_prompt,
)


async def generate_interview_prep(
    resume_data: dict[str, Any],
    job_description: str,
) -> InterviewPrepData:
    """Generate structured interview preparation for a tailored resume."""
    prompt = INTERVIEW_PREP_PROMPT.format(
        job_description=truncate_text_for_prompt(
            job_description,
            JOB_DESCRIPTION_PROMPT_CHAR_LIMIT,
        ),
        resume_data=serialize_resume_data_for_prompt(resume_data),
        output_language=OUTPUT_LANGUAGE,
    )
    config = get_llm_config()
    max_tokens = get_safe_max_tokens(
        get_model_name(config),
        requested=8192,
        config=config,
    )

    result = await complete_json(
        prompt=prompt,
        system_prompt=(
            "You are a career interview coach. Output truthful, resume-grounded "
            "interview preparation as JSON only."
        ),
        max_tokens=max_tokens,
        schema_type="interview_prep",
    )

    return InterviewPrepData.model_validate(result)
