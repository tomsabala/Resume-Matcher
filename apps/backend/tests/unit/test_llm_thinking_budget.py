"""Anthropic thinking-budget reconciliation.

Anthropic counts thinking tokens inside ``max_tokens`` and rejects any request
where ``max_tokens <= thinking.budget_tokens``. Several call sites hardcode a
small ``max_tokens`` (the health check uses 64, ``generate_skill_target_plan``
uses 2048), so a configured ``reasoning_effort`` used to make them fail with
``invalid_request_error``.
"""

import pytest

from app.llm import (
    _FALLBACK_THINKING_BUDGETS,
    _anthropic_thinking_budget,
    _reconcile_max_tokens,
    LLMConfig,
)

# Claude 4.5 and earlier receive an explicit thinking budget.
BUDGETED_MODEL = "anthropic/claude-opus-4-5-20251101"
# Claude 4.6+ use adaptive thinking (output_config.effort), with no budget.
ADAPTIVE_MODEL = "anthropic/claude-opus-4-7"


class TestAnthropicThinkingBudget:
    def test_budget_matches_litellm_for_each_effort(self) -> None:
        """Our fallback table must not drift from LiteLLM's own mapping."""
        for effort, expected in _FALLBACK_THINKING_BUDGETS.items():
            assert _anthropic_thinking_budget(BUDGETED_MODEL, effort) == expected, (
                f"LiteLLM's budget for {effort!r} no longer matches the mirrored "
                f"table; update _FALLBACK_THINKING_BUDGETS."
            )

    def test_adaptive_thinking_models_carry_no_budget(self) -> None:
        assert _anthropic_thinking_budget(ADAPTIVE_MODEL, "high") == 0

    def test_no_budget_without_reasoning_effort(self) -> None:
        assert _anthropic_thinking_budget(BUDGETED_MODEL, None) == 0

    def test_non_anthropic_routes_are_untouched(self) -> None:
        assert _anthropic_thinking_budget("openai/gpt-5-nano", "high") == 0
        assert _anthropic_thinking_budget("ollama/gemma3:4b", "high") == 0


class TestReconcileMaxTokens:
    @pytest.mark.parametrize(
        "effort,requested",
        [("minimal", 64), ("low", 64), ("medium", 64), ("high", 64)],
    )
    def test_health_check_budget_is_raised_above_thinking(
        self, effort: str, requested: int
    ) -> None:
        """The 64-token health check must clear the budget for every effort."""
        budget = _anthropic_thinking_budget(BUDGETED_MODEL, effort)
        result = _reconcile_max_tokens(BUDGETED_MODEL, requested, effort)
        assert result > budget, (
            f"max_tokens={result} does not exceed thinking budget {budget}; "
            f"Anthropic would reject this request"
        )

    def test_equal_to_budget_is_still_raised(self) -> None:
        """2048 == the medium budget: Anthropic requires strictly greater."""
        assert _anthropic_thinking_budget(BUDGETED_MODEL, "medium") == 2048
        assert _reconcile_max_tokens(BUDGETED_MODEL, 2048, "medium") > 2048

    def test_requested_headroom_is_preserved(self) -> None:
        """The caller's budget survives as answer room on top of thinking."""
        budget = _anthropic_thinking_budget(BUDGETED_MODEL, "medium")
        assert _reconcile_max_tokens(BUDGETED_MODEL, 64, "medium") == budget + 64

    def test_ample_budget_is_left_alone(self) -> None:
        assert _reconcile_max_tokens(BUDGETED_MODEL, 8192, "medium") == 8192

    def test_adaptive_model_is_left_alone(self) -> None:
        assert _reconcile_max_tokens(ADAPTIVE_MODEL, 64, "high") == 64

    def test_non_anthropic_is_left_alone(self) -> None:
        assert _reconcile_max_tokens("openai/gpt-5-nano", 64, "high") == 64

    def test_result_is_clamped_to_model_output_limit(self) -> None:
        """Reconciliation must not exceed what the model can actually emit."""
        config = LLMConfig(
            provider="anthropic", model="claude-opus-4-5-20251101", api_key="sk-test"
        )
        result = _reconcile_max_tokens(BUDGETED_MODEL, 4096, "high", config)
        assert result > 4096
        import litellm

        limit = litellm.get_model_info(model=BUDGETED_MODEL)["max_output_tokens"]
        assert result <= limit
