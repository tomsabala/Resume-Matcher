"""A truncated answer is an output-budget problem, not a prompt problem.

A resume parse that stopped mid-object used to be reported as "No JSON found in
response" and retried with the same budget plus a "do not truncate" plea — a
retry that cannot work, and a diagnosis that sent the reader looking for a
parser bug.
"""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.ai_events import clear_ai_failures, recent_ai_failures
from app.llm import (
    LLMConfig,
    MAX_ESCALATED_JSON_MAX_TOKENS,
    TruncatedCompletionError,
    _escalate_token_budget,
    _extract_json,
    complete_json,
)

pytestmark = pytest.mark.unit

_COMPLETE = '{"schemaVersion": 2, "sections": []}'


def _choice(content: str, finish_reason: str = "stop") -> Any:
    """A LiteLLM-shaped choice, with the field the loop now reads."""
    return type(
        "Choice",
        (),
        {
            "message": type("Message", (), {"content": content})(),
            "finish_reason": finish_reason,
        },
    )()


def _response(content: str, finish_reason: str = "stop") -> Any:
    return type("Response", (), {"choices": [_choice(content, finish_reason)]})()


@pytest.fixture(autouse=True)
def _clean_failure_tail() -> Any:
    clear_ai_failures("")
    yield
    clear_ai_failures("")


class TestExtraction:
    def test_an_unclosed_object_is_reported_as_truncation(self):
        cut = '{"header": {"name": "Ada", "contacts": [{"kind": "email"'

        with pytest.raises(TruncatedCompletionError, match="truncated"):
            _extract_json(cut)

    def test_the_message_names_the_depth_and_the_length(self):
        with pytest.raises(TruncatedCompletionError) as caught:
            _extract_json('{"a": {"b": 1')

        message = str(caught.value)
        assert "2 unclosed" in message
        assert str(len('{"a": {"b": 1')) in message

    def test_prose_with_no_object_is_still_a_plain_value_error(self):
        """The two failures need different fixes, so they stay different types."""
        with pytest.raises(ValueError) as caught:
            _extract_json("I am unable to help with that request.")

        assert not isinstance(caught.value, TruncatedCompletionError)


class TestBudgetEscalation:
    def test_the_budget_doubles_within_the_model_limit(self):
        assert _escalate_token_budget("anthropic/claude-opus-5", 8192) == 16384

    def test_escalation_stops_at_our_own_ceiling(self):
        capped = _escalate_token_budget(
            "anthropic/claude-opus-5", MAX_ESCALATED_JSON_MAX_TOKENS
        )
        assert capped == MAX_ESCALATED_JSON_MAX_TOKENS

    def test_a_registry_unknown_model_can_still_escalate(self):
        """FALLBACK_MAX_TOKENS is a guess for models the registry lacks, and a
        truncated answer is evidence the guess was too small."""
        assert _escalate_token_budget("unknown/tiny-model", 4096) == 8192

    def test_a_known_model_limit_still_clamps_the_escalation(self):
        """Doubling past what the provider accepts turns a truncated answer
        into a hard 400."""
        limit = 64000  # claude-opus-4-5's registry output limit
        assert _escalate_token_budget("anthropic/claude-opus-4-5", 40_000) == limit


class TestRetryBehaviour:
    @patch("app.llm.get_router")
    async def test_a_truncated_answer_is_retried_with_a_bigger_budget(
        self, get_router: Any
    ):
        router = AsyncMock()
        router.acompletion = AsyncMock(
            side_effect=[
                _response('{"schemaVersion": 2, "sections": [{"key": "a"', "length"),
                _response(_COMPLETE),
            ]
        )
        config = LLMConfig(provider="anthropic", model="claude-opus-5", api_key="k")
        get_router.return_value = (router, config)

        result = await complete_json("parse this", max_tokens=8192, retries=2)

        assert result == {"schemaVersion": 2, "sections": []}
        budgets = [call.kwargs["max_tokens"] for call in router.acompletion.await_args_list]
        assert budgets == [8192, 16384]

    @patch("app.llm.get_router")
    async def test_a_length_stop_with_no_content_is_truncation_not_emptiness(
        self, get_router: Any
    ):
        """A reasoning model can spend the whole budget before writing a word;
        that is the same budget problem, and the same fix."""
        router = AsyncMock()
        router.acompletion = AsyncMock(
            side_effect=[_response("", "length"), _response(_COMPLETE)]
        )
        config = LLMConfig(provider="anthropic", model="claude-opus-5", api_key="k")
        get_router.return_value = (router, config)

        result = await complete_json("parse this", max_tokens=8192, retries=1)

        assert result == {"schemaVersion": 2, "sections": []}
        budgets = [call.kwargs["max_tokens"] for call in router.acompletion.await_args_list]
        assert budgets == [8192, 16384]

    @patch("app.llm.get_router")
    async def test_a_recovered_retry_records_no_failure(self, get_router: Any):
        router = AsyncMock()
        router.acompletion = AsyncMock(
            side_effect=[_response('{"sections": [', "length"), _response(_COMPLETE)]
        )
        config = LLMConfig(provider="anthropic", model="claude-opus-5", api_key="k")
        get_router.return_value = (router, config)

        await complete_json("parse this", max_tokens=8192, retries=1)

        assert recent_ai_failures("") == []

    @patch("app.llm.get_router")
    async def test_exhausted_retries_raise_truncation_and_record_it(
        self, get_router: Any
    ):
        router = AsyncMock()
        router.acompletion = AsyncMock(
            return_value=_response('{"sections": [{"key": "a"', "length")
        )
        config = LLMConfig(provider="anthropic", model="claude-opus-5", api_key="k")
        get_router.return_value = (router, config)

        with pytest.raises(TruncatedCompletionError):
            await complete_json(
                "parse this", max_tokens=8192, retries=1, schema_type="resume"
            )

        failures = recent_ai_failures("")
        assert len(failures) == 1
        failure = failures[0]
        assert failure.kind == "truncated"
        assert failure.operation == "resume"
        assert failure.attempts == 2
        # The escalated budget, not the caller's original request.
        assert failure.max_tokens == 16384
        assert failure.provider == "anthropic"

    @patch("app.llm.get_router")
    async def test_a_validator_rejection_is_recorded_as_invalid(self, get_router: Any):
        router = AsyncMock()
        router.acompletion = AsyncMock(return_value=_response(_COMPLETE))
        config = LLMConfig(provider="anthropic", model="claude-opus-5", api_key="k")
        get_router.return_value = (router, config)

        def reject(_result: dict[str, Any]) -> dict[str, Any]:
            raise ValueError("LLM returned an empty structured resume.")

        with pytest.raises(ValueError):
            await complete_json(
                "parse this", max_tokens=8192, retries=0, response_validator=reject
            )

        assert [f.kind for f in recent_ai_failures("")] == ["invalid"]
