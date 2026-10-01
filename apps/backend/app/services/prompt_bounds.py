"""Shared bounds for prompt inputs.

Resumes and job descriptions are user-supplied and unbounded; every service
that feeds them to an LLM must clamp them first, and must say so in the prompt
so the model does not invent what was cut. Extracted from
``app/services/interview_prep.py`` when a second consumer appeared.
"""

import json
from typing import Any

JOB_DESCRIPTION_PROMPT_CHAR_LIMIT = 12_000
RESUME_DATA_PROMPT_CHAR_LIMIT = 30_000
# Both notices are injected *inside* the serialized resume the model is told to
# ground on, so a generated card can echo them verbatim. They stay English —
# they are machine metadata, not content — and the ``[system`` prefix is what
# says so, in whatever language the output is written in.
TRUNCATION_NOTICE = (
    "[system: content truncated for prompt length. Use only the visible "
    "evidence; do not infer or invent omitted details.]"
)


def interview_coach_system_prompt(output_language: str) -> str:
    """System prompt shared by the interview-prep and prep-card services."""
    return (
        "You are a career interview coach. Output truthful, resume-grounded "
        f"interview preparation as JSON only. Write all output in {output_language}."
    )


def truncate_text_for_prompt(value: str, max_chars: int) -> str:
    """Bound unstructured prompt input while making omissions explicit."""
    if len(value) <= max_chars:
        return value
    return f"{value[:max_chars].rstrip()}\n\n{TRUNCATION_NOTICE}"


def truncate_json_value(
    value: Any,
    *,
    max_string_chars: int,
    max_list_items: int,
) -> Any:
    if isinstance(value, str):
        return truncate_text_for_prompt(value, max_string_chars)
    if isinstance(value, list):
        truncated = [
            truncate_json_value(
                item,
                max_string_chars=max_string_chars,
                max_list_items=max_list_items,
            )
            for item in value[:max_list_items]
        ]
        if len(value) > max_list_items:
            truncated.append(
                {
                    "_prompt_truncation_notice": (
                        f"[system: {len(value) - max_list_items} additional items "
                        "omitted. Do not infer omitted details.]"
                    )
                }
            )
        return truncated
    if isinstance(value, dict):
        return {
            key: truncate_json_value(
                item,
                max_string_chars=max_string_chars,
                max_list_items=max_list_items,
            )
            for key, item in value.items()
        }
    return value


def serialize_resume_data_for_prompt(resume_data: dict[str, Any]) -> str:
    """Serialize a resume to JSON small enough to prompt with."""
    resume_json = json.dumps(resume_data, ensure_ascii=False)
    if len(resume_json) <= RESUME_DATA_PROMPT_CHAR_LIMIT:
        return resume_json

    for max_string_chars, max_list_items in ((2_000, 30), (1_000, 20), (500, 10)):
        bounded = truncate_json_value(
            resume_data,
            max_string_chars=max_string_chars,
            max_list_items=max_list_items,
        )
        bounded_json = json.dumps(bounded, ensure_ascii=False)
        if len(bounded_json) <= RESUME_DATA_PROMPT_CHAR_LIMIT:
            return bounded_json

    compact_snapshot = json.dumps(
        truncate_json_value(resume_data, max_string_chars=250, max_list_items=5),
        ensure_ascii=False,
    )
    return json.dumps(
        {
            "_prompt_truncation_notice": TRUNCATION_NOTICE,
            "limited_resume_snapshot": truncate_text_for_prompt(
                compact_snapshot,
                RESUME_DATA_PROMPT_CHAR_LIMIT - 500,
            ),
        },
        ensure_ascii=False,
    )
