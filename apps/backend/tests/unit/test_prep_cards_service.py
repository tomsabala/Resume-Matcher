from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from app.services.prep_cards import (
    answer_prep_card,
    critique_prep_answer,
    generate_prep_cards,
)


SAMPLE_RESUME = {
    "personalInfo": {"name": "Jane Doe"},
    "summary": "Backend engineer",
    "workExperience": [],
    "additional": {"technicalSkills": ["Python", "FastAPI"]},
}


@contextmanager
def _patched_llm_token_helpers(max_tokens: int = 4096):
    config = object()
    with patch(
        "app.services.prep_cards.get_llm_config",
        return_value=config,
    ) as mock_get_llm_config, patch(
        "app.services.prep_cards.get_model_name",
        return_value="openai/small-output-model",
    ) as mock_get_model_name, patch(
        "app.services.prep_cards.get_safe_max_tokens",
        return_value=max_tokens,
    ) as mock_get_safe_max_tokens:
        yield mock_get_llm_config, mock_get_model_name, mock_get_safe_max_tokens


@contextmanager
def _patched_complete_json(payload):
    with patch(
        "app.services.prep_cards.complete_json",
        new_callable=AsyncMock,
    ) as mock_complete:
        mock_complete.return_value = payload
        yield mock_complete


@pytest.mark.asyncio
async def test_generate_uses_its_own_schema_type_and_token_budget():
    """``interview_prep`` keys llm.py's truncation detector; these must not reuse it."""
    payload = {"proposals": [{"question": "What is WAL?", "explanation": "Durability."}]}
    with _patched_complete_json(payload) as mock_complete, _patched_llm_token_helpers() as (
        mock_get_llm_config,
        _,
        mock_get_safe_max_tokens,
    ):
        result = await generate_prep_cards(
            category="technical",
            resume_data=SAMPLE_RESUME,
            job_description=None,
            count=8,
            output_language="English",
        )

    assert [p.question for p in result] == ["What is WAL?"]
    assert mock_complete.await_args.kwargs["schema_type"] == "prep_card_generate"
    assert mock_complete.await_args.kwargs["max_tokens"] == 4096
    mock_get_safe_max_tokens.assert_called_once_with(
        "openai/small-output-model",
        requested=4096,
        config=mock_get_llm_config.return_value,
    )


@pytest.mark.asyncio
async def test_generate_forces_the_requested_category_over_the_models_echo():
    payload = {
        "proposals": [
            {"question": "Why this role?", "category": "technical"},
            {"question": "Tell me about the gap.", "category": "technical"},
        ]
    }
    with _patched_complete_json(payload), _patched_llm_token_helpers():
        result = await generate_prep_cards(
            category="personal",
            resume_data=SAMPLE_RESUME,
            job_description=None,
            count=8,
            output_language="English",
        )

    assert [p.category.value for p in result] == ["personal", "personal"]


@pytest.mark.asyncio
async def test_generate_truncates_to_the_requested_count():
    payload = {"proposals": [{"question": f"Q{i}"} for i in range(10)]}
    with _patched_complete_json(payload), _patched_llm_token_helpers():
        result = await generate_prep_cards(
            category="technical",
            resume_data=SAMPLE_RESUME,
            job_description=None,
            count=3,
            output_language="English",
        )

    assert len(result) == 3


@pytest.mark.asyncio
async def test_generate_says_so_when_there_is_no_job_description():
    payload = {"proposals": []}
    with _patched_complete_json(payload) as mock_complete, _patched_llm_token_helpers():
        await generate_prep_cards(
            category="technical",
            resume_data=SAMPLE_RESUME,
            job_description=None,
            count=4,
            output_language="English",
        )

    prompt = mock_complete.await_args.kwargs["prompt"]
    assert "No specific job description was provided" in prompt


@pytest.mark.asyncio
async def test_generate_bounds_oversized_prompt_inputs():
    payload = {"proposals": []}
    with _patched_complete_json(payload) as mock_complete, _patched_llm_token_helpers():
        large_resume = {
            **SAMPLE_RESUME,
            "summary": "Backend engineer " + ("with API delivery evidence. " * 3000),
        }
        await generate_prep_cards(
            category="technical",
            resume_data=large_resume,
            job_description="Need FastAPI. " + ("Detailed requirement. " * 1500),
            count=4,
            output_language="English",
        )

    prompt = mock_complete.await_args.kwargs["prompt"]
    assert len(prompt) < 50_000
    assert "content truncated for prompt length" in prompt
    assert "do not infer or invent omitted details" in prompt


@pytest.mark.asyncio
async def test_generate_rejects_malformed_llm_json():
    with _patched_complete_json({"questions": ["wrong key"]}), _patched_llm_token_helpers():
        with pytest.raises(ValidationError):
            await generate_prep_cards(
                category="technical",
                resume_data=SAMPLE_RESUME,
                job_description=None,
                count=4,
                output_language="English",
            )


@pytest.mark.asyncio
async def test_answer_uses_its_own_schema_type_and_token_budget():
    payload = {"answer": "A log.", "explanation": "Because…", "examples": ["One"]}
    with _patched_complete_json(payload) as mock_complete, _patched_llm_token_helpers(
        2048
    ) as (mock_get_llm_config, _, mock_get_safe_max_tokens):
        result = await answer_prep_card(
            category="technical",
            question="What is WAL?",
            resume_data=SAMPLE_RESUME,
            job_description="Need SQLite",
            output_language="English",
        )

    assert result.answer == "A log."
    assert mock_complete.await_args.kwargs["schema_type"] == "prep_card_answer"
    assert mock_complete.await_args.kwargs["max_tokens"] == 2048
    mock_get_safe_max_tokens.assert_called_once_with(
        "openai/small-output-model",
        requested=2048,
        config=mock_get_llm_config.return_value,
    )


@pytest.mark.asyncio
async def test_answer_rejects_malformed_llm_json():
    with _patched_complete_json({"answer": "A log."}), _patched_llm_token_helpers(2048):
        with pytest.raises(ValidationError):
            await answer_prep_card(
                category="technical",
                question="What is WAL?",
                resume_data=SAMPLE_RESUME,
                job_description=None,
                output_language="English",
            )


@pytest.mark.asyncio
async def test_critique_uses_its_own_schema_type_and_token_budget():
    payload = {
        "score": 4,
        "strengths": ["Clear"],
        "gaps": ["Short"],
        "suggested_rewrite": "Try this.",
    }
    with _patched_complete_json(payload) as mock_complete, _patched_llm_token_helpers(
        2048
    ) as (mock_get_llm_config, _, mock_get_safe_max_tokens):
        result = await critique_prep_answer(
            question="Why us?",
            my_answer="Because I like the product.",
            model_answer=None,
            resume_data=SAMPLE_RESUME,
            output_language="English",
        )

    assert result.score == 4
    assert mock_complete.await_args.kwargs["schema_type"] == "prep_card_critique"
    assert mock_complete.await_args.kwargs["max_tokens"] == 2048
    mock_get_safe_max_tokens.assert_called_once_with(
        "openai/small-output-model",
        requested=2048,
        config=mock_get_llm_config.return_value,
    )


@pytest.mark.asyncio
async def test_critique_rejects_an_out_of_range_score():
    payload = {"score": 9, "strengths": [], "gaps": [], "suggested_rewrite": "x"}
    with _patched_complete_json(payload), _patched_llm_token_helpers(2048):
        with pytest.raises(ValidationError):
            await critique_prep_answer(
                question="Why us?",
                my_answer="Because.",
                model_answer=None,
                resume_data=SAMPLE_RESUME,
                output_language="English",
            )


@pytest.mark.asyncio
async def test_oversized_job_description_is_refused_before_the_provider_call():
    with _patched_complete_json({"proposals": []}) as mock_complete, _patched_llm_token_helpers():
        with pytest.raises(ValueError):
            await generate_prep_cards(
                category="technical",
                resume_data=SAMPLE_RESUME,
                job_description="x" * 100_001,
                count=4,
                output_language="English",
            )
    mock_complete.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["Hebrew", "English"])
async def test_generation_language_reaches_both_the_prompt_and_the_system_prompt(
    language: str,
) -> None:
    """The workspace's content language must reach the model, not just the API."""
    with _patched_complete_json({"proposals": []}) as mock_complete, (
        _patched_llm_token_helpers()
    ):
        await generate_prep_cards(
            category="technical",
            resume_data=SAMPLE_RESUME,
            job_description=None,
            count=3,
            output_language=language,
        )

    kwargs = mock_complete.await_args.kwargs
    assert f"Write in {language}." in kwargs["prompt"]
    assert f"Write all output in {language}." in kwargs["system_prompt"]
    if language != "Hebrew":
        assert "Hebrew" not in kwargs["prompt"]
        assert "Hebrew" not in kwargs["system_prompt"]
