"""A changed model registry must not enable unsupported GPT-5 sampling."""

from typing import Any
from unittest.mock import patch

import pytest

from app.llm import _supports_temperature


@pytest.mark.parametrize("reasoning_capability", [None, "true", 1])
def test_unknown_reasoning_capability_omits_flexible_sampling(
    reasoning_capability: Any,
) -> None:
    model_info = {
        "supported_openai_params": ["temperature"],
        "supports_reasoning": reasoning_capability,
        "supports_none_reasoning_effort": True,
    }
    with patch("app.llm.litellm.get_model_info", return_value=model_info):
        assert not _supports_temperature("gpt-5.1", 0.7, reasoning_effort=None)
        assert _supports_temperature("gpt-5.1", 1.0, reasoning_effort=None)


def test_thinking_models_get_no_sampling_temperature() -> None:
    """A reasoning model sent a reasoning_effort has thinking turned on, and
    Anthropic then rejects any temperature but 1. Real failure this pins:
    ``claude-opus-5`` + ``reasoning_effort="minimal"`` + ``temperature=0.1``
    returned 400 and every upload reported "AI parsing failed".
    """
    model_info = {
        "supported_openai_params": ["temperature", "reasoning_effort"],
        "supports_reasoning": True,
    }
    with patch("app.llm.litellm.get_model_info", return_value=model_info):
        assert not _supports_temperature(
            "claude-sonnet-4-5", 0.1, reasoning_effort="minimal"
        )
        # No effort configured means no thinking block, so sampling is fine.
        assert _supports_temperature("claude-sonnet-4-5", 0.1, reasoning_effort=None)


@pytest.mark.parametrize(
    "model_name", ["claude-opus-4-1", "claude-opus-4-5", "claude-opus-5", "anthropic/claude-opus-6"]
)
def test_opus_4_and_later_never_receive_a_temperature(model_name: str) -> None:
    """Anthropic deprecated the parameter across the Opus line from 4 on.
    Real failure this pins: ``claude-opus-5`` with no reasoning effort at all
    answered 400 "`temperature` is deprecated for this model." and every
    upload reported "AI parsing failed". Matching the major version rather
    than a name list keeps the next Opus working on release day.
    """
    model_info = {
        "supported_openai_params": ["temperature"],
        "supports_reasoning": True,
    }
    with patch("app.llm.litellm.get_model_info", return_value=model_info):
        assert not _supports_temperature(model_name, 0.1, reasoning_effort=None)
        assert not _supports_temperature(model_name, 1.0, reasoning_effort=None)


def test_opus_3_keeps_its_temperature() -> None:
    """The deprecation starts at Opus 4; the older model still accepts it."""
    model_info = {
        "supported_openai_params": ["temperature"],
        "supports_reasoning": False,
    }
    with patch("app.llm.litellm.get_model_info", return_value=model_info):
        assert _supports_temperature("claude-3-opus-20240229", 0.1, reasoning_effort=None)


def test_non_reasoning_models_keep_their_temperature() -> None:
    """The effort only matters for models that can actually think."""
    model_info = {
        "supported_openai_params": ["temperature"],
        "supports_reasoning": False,
    }
    with patch("app.llm.litellm.get_model_info", return_value=model_info):
        assert _supports_temperature(
            "claude-3-5-haiku-latest", 0.1, reasoning_effort="minimal"
        )
