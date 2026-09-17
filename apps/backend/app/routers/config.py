"""LLM configuration endpoints."""

import json
import logging
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.config import settings
from app.llm import check_llm_health, LLMConfig, resolve_api_key
from app.schemas import (
    LLMConfigRequest,
    LLMConfigResponse,
    FeatureConfigRequest,
    FeatureConfigResponse,
    FeaturePromptsRequest,
    FeaturePromptsResponse,
    LanguageConfigRequest,
    LanguageConfigResponse,
    PromptConfigRequest,
    PromptConfigResponse,
    PromptOption,
    ApiKeyProviderStatus,
    ApiKeyStatusResponse,
    ApiKeysUpdateRequest,
    ApiKeysUpdateResponse,
    ResetDatabaseRequest,
)
from app.prompts import (
    DEFAULT_IMPROVE_PROMPT_ID,
    IMPROVE_PROMPT_OPTIONS,
    validate_prompt_placeholders,
)
from app.prompts.templates import COVER_LETTER_PROMPT, OUTREACH_MESSAGE_PROMPT
from app.config import (
    get_api_keys_from_config,
    get_config_path,
    save_api_keys_to_config,
    delete_api_key_from_config,
    clear_all_api_keys,
    load_config_file,
)
from app.config_cache import invalidate_config_cache
from app.database import db
from app.deps import WorkspaceId

# Providers that cannot function without an explicit endpoint. Mirrors
# `requiresBaseUrl` in apps/frontend/lib/api/config.ts (M-05) — the UI guard
# alone left the .env-driven setup path able to persist an unusable config.
PROVIDERS_REQUIRING_BASE_URL: frozenset[str] = frozenset({"azure_foundry"})


def _effective_api_base(stored: dict) -> str | None:
    """Resolve the base URL the LLM layer will actually use.

    ``stored.get("api_base", default)`` returns None when the key is PRESENT
    with a null value — which is exactly what an explicit "clear the field"
    writes. That made validation (which fell back to the env var) disagree with
    config construction (which did not): saving with LLM_API_BASE set passed
    the required-base-URL check and then handed api_base=None to LiteLLM.
    Every site resolves through here so they cannot drift again.
    """
    return stored.get("api_base") or settings.llm_api_base or None

router = APIRouter(prefix="/config", tags=["Configuration"])


def _get_config_path() -> Path:
    """Get path to config storage file."""
    return get_config_path()


def _load_config(workspace_id: str) -> dict:
    """Load one workspace's merged config view, keys included.

    ``config.json`` (the instance default) with that workspace's overrides
    applied and its decrypted API keys injected, so ``resolve_api_key`` works.
    """
    return load_config_file(workspace_id)


# The keys each write endpoint owns. Only these are persisted, so saving the
# feature toggles does not also freeze the tenant's current provider and model
# as overrides of an instance default they never chose.
_LLM_KEYS = ("provider", "model", "api_base", "reasoning_effort")
_FEATURE_KEYS = (
    "enable_cover_letter",
    "enable_outreach_message",
    "enable_interview_prep",
)
_LANGUAGE_KEYS = ("ui_language", "content_language")
_PROMPT_KEYS = ("default_prompt_id",)
_FEATURE_PROMPT_KEYS = ("cover_letter_prompt", "outreach_message_prompt")


async def _save_overrides(
    workspace_id: str, stored: dict, keys: tuple[str, ...]
) -> None:
    """Persist this endpoint's keys as the workspace's own overrides.

    ``config.json`` is written only by the operator out of band and by the
    startup migrations; a tenant's save goes to its own rows so it cannot
    rewrite the instance default every other tenant inherits.
    """
    for key in keys:
        if key in stored:
            await db.set_workspace_setting(workspace_id, key, stored[key])
    invalidate_config_cache(workspace_id)


def _mask_api_key(key: str) -> str:
    """Mask API key for display."""
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return key[:4] + "*" * (len(key) - 8) + key[-4:]


def _get_prompt_options() -> list[PromptOption]:
    """Return available prompt options for resume tailoring."""
    return [PromptOption(**option) for option in IMPROVE_PROMPT_OPTIONS]


async def _log_llm_health_check(config: LLMConfig) -> None:
    """Run a best-effort health check and log outcome without affecting API responses."""
    try:
        health = await check_llm_health(config)
        if not health.get("healthy", False):
            logging.warning(
                "LLM config saved but health check failed",
                extra={"provider": config.provider, "model": config.model},
            )
    except Exception:
        logging.exception(
            "LLM config saved but health check raised exception",
            extra={"provider": config.provider, "model": config.model},
        )


@router.get("/llm-api-key", response_model=LLMConfigResponse)
async def get_llm_config_endpoint(workspace_id: WorkspaceId) -> LLMConfigResponse:
    """Get current LLM configuration (API key masked)."""
    stored = _load_config(workspace_id)

    provider = stored.get("provider", settings.llm_provider)
    reasoning_effort = stored.get("reasoning_effort", settings.reasoning_effort)
    return LLMConfigResponse(
        provider=provider,
        model=stored.get("model", settings.llm_model),
        api_key=_mask_api_key(resolve_api_key(stored, provider)),
        api_base=_effective_api_base(stored),
        reasoning_effort=reasoning_effort or None,
    )


@router.put("/llm-api-key", response_model=LLMConfigResponse)
async def update_llm_config(
    request: LLMConfigRequest,
    background_tasks: BackgroundTasks,
    workspace_id: WorkspaceId,
) -> LLMConfigResponse:
    """Update LLM configuration.

    Saves the configuration and returns it (API key masked).

    Note: We intentionally do NOT hard-fail the update based on a live health check.
    Users may configure proxies/aggregators or temporarily unavailable endpoints and
    still need to persist the configuration. Connectivity can be verified via
    `/config/llm-test` and the System Status panel.
    """
    stored = _load_config(workspace_id)

    # Update only provided fields
    if request.provider is not None:
        stored["provider"] = request.provider
    if request.model is not None:
        stored["model"] = request.model
    # NOTE: API keys are NOT written here anymore. They live in the encrypted
    # per-provider store (PUT /config/api-keys). Writing the legacy single
    # ``api_key`` slot here is what caused providers to overwrite each other and
    # shadow the per-provider map in resolve_api_key. request.api_key is ignored
    # for persistence (kept in the schema only for response masking/back-compat).
    # api_base: distinguish "omitted" (leave unchanged) from "present but
    # blank/null" (explicit clear). The frontend sends api_base: null/"" when
    # the Base URL field is cleared; treating that as "don't change" left a
    # stale override in config.json (issue #760). Normalize blank → None so an
    # empty string also never reaches LiteLLM as a bogus endpoint.
    if "api_base" in request.model_fields_set:
        cleaned = (request.api_base or "").strip()
        stored["api_base"] = cleaned or None
    if request.reasoning_effort is not None:
        # Persist empty string on clear so the gpt-5 auto-migration doesn't
        # re-fire on next get_llm_config() call.
        stored["reasoning_effort"] = request.reasoning_effort

    # Build normalized config for response and background health check
    resolved_provider = stored.get("provider", settings.llm_provider)

    # M-05: `requiresBaseUrl` was enforced in the settings UI only, so the
    # .env-driven path could persist a provider that cannot work without an
    # endpoint. Fail at save time with a field name instead of surfacing an
    # opaque LiteLLM error on the user's first generation.
    if resolved_provider in PROVIDERS_REQUIRING_BASE_URL and not (
        _effective_api_base(stored)
    ):
        # Structured detail using the same {code, field, missing} shape as
        # update_feature_prompts below, so the UI has one schema to read for
        # every validation error out of this router.
        raise HTTPException(
            status_code=422,
            detail={
                "code": "missing_base_url",
                "field": "api_base",
                "missing": ["api_base"],
            },
        )
    raw_re = stored.get("reasoning_effort", settings.reasoning_effort)
    resolved_reasoning_effort = raw_re if raw_re else None
    test_config = LLMConfig(
        provider=resolved_provider,
        model=stored.get("model", settings.llm_model),
        api_key=resolve_api_key(stored, resolved_provider),
        api_base=_effective_api_base(stored),
        reasoning_effort=resolved_reasoning_effort,
    )

    # Save config regardless of health check outcome (see docstring).
    await _save_overrides(workspace_id, stored, _LLM_KEYS)

    # Best-effort health check for server-side logs/diagnostics (do not block response).
    background_tasks.add_task(_log_llm_health_check, test_config)

    return LLMConfigResponse(
        provider=test_config.provider,
        model=test_config.model,
        api_key=_mask_api_key(test_config.api_key),
        api_base=test_config.api_base,
        reasoning_effort=test_config.reasoning_effort,
    )


@router.post("/llm-test")
async def test_llm_connection(
    workspace_id: WorkspaceId, request: LLMConfigRequest | None = None
) -> dict:
    """Test LLM connection with provided or stored configuration.

    If request body is provided, tests with those values (for pre-save testing).
    Otherwise, tests with the currently saved configuration.
    """
    stored = _load_config(workspace_id)

    # Build config: use request values if provided, otherwise fall back to stored/default
    test_provider = (
        request.provider
        if request and request.provider
        else stored.get("provider", settings.llm_provider)
    )
    config = LLMConfig(
        provider=test_provider,
        model=(
            request.model
            if request and request.model
            else stored.get("model", settings.llm_model)
        ),
        api_key=(
            request.api_key
            if request and request.api_key
            else resolve_api_key(stored, test_provider)
        ),
        api_base=(
            request.api_base
            if request and request.api_base is not None
            else _effective_api_base(stored)
        ),
        reasoning_effort=(
            (request.reasoning_effort or None)
            if request and request.reasoning_effort is not None
            else (stored.get("reasoning_effort") or settings.reasoning_effort) or None
        ),
    )

    test_prompt = "Hi"
    return await check_llm_health(config, include_details=True, test_prompt=test_prompt)


@router.get("/features", response_model=FeatureConfigResponse)
async def get_feature_config(workspace_id: WorkspaceId) -> FeatureConfigResponse:
    """Get current feature configuration."""
    stored = _load_config(workspace_id)

    return FeatureConfigResponse(
        enable_cover_letter=stored.get("enable_cover_letter", False),
        enable_outreach_message=stored.get("enable_outreach_message", False),
        enable_interview_prep=stored.get("enable_interview_prep", False),
    )


@router.put("/features", response_model=FeatureConfigResponse)
async def update_feature_config(
    request: FeatureConfigRequest, workspace_id: WorkspaceId
) -> FeatureConfigResponse:
    """Update feature configuration."""
    stored = _load_config(workspace_id)

    # Update only provided fields
    if request.enable_cover_letter is not None:
        stored["enable_cover_letter"] = request.enable_cover_letter
    if request.enable_outreach_message is not None:
        stored["enable_outreach_message"] = request.enable_outreach_message
    if request.enable_interview_prep is not None:
        stored["enable_interview_prep"] = request.enable_interview_prep

    # Save config
    await _save_overrides(workspace_id, stored, _FEATURE_KEYS)

    return FeatureConfigResponse(
        enable_cover_letter=stored.get("enable_cover_letter", False),
        enable_outreach_message=stored.get("enable_outreach_message", False),
        enable_interview_prep=stored.get("enable_interview_prep", False),
    )


# Supported languages for i18n
SUPPORTED_LANGUAGES = ["en", "es", "zh", "ja", "pt", "fr", "ko"]


@router.get("/language", response_model=LanguageConfigResponse)
async def get_language_config(workspace_id: WorkspaceId) -> LanguageConfigResponse:
    """Get current language configuration."""
    stored = _load_config(workspace_id)

    # Support legacy single 'language' field migration
    legacy_language = stored.get("language", "en")

    return LanguageConfigResponse(
        ui_language=stored.get("ui_language", legacy_language),
        content_language=stored.get("content_language", legacy_language),
        supported_languages=SUPPORTED_LANGUAGES,
    )


@router.put("/language", response_model=LanguageConfigResponse)
async def update_language_config(
    request: LanguageConfigRequest,
    workspace_id: WorkspaceId,
) -> LanguageConfigResponse:
    """Update language configuration."""
    stored = _load_config(workspace_id)

    # Validate and update UI language
    if request.ui_language is not None:
        if request.ui_language not in SUPPORTED_LANGUAGES:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported UI language: {request.ui_language}. Supported: {SUPPORTED_LANGUAGES}",
            )
        stored["ui_language"] = request.ui_language

    # Validate and update content language
    if request.content_language is not None:
        if request.content_language not in SUPPORTED_LANGUAGES:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported content language: {request.content_language}. Supported: {SUPPORTED_LANGUAGES}",
            )
        stored["content_language"] = request.content_language

    # Save config
    await _save_overrides(workspace_id, stored, _LANGUAGE_KEYS)

    # Support legacy single 'language' field migration
    legacy_language = stored.get("language", "en")

    return LanguageConfigResponse(
        ui_language=stored.get("ui_language", legacy_language),
        content_language=stored.get("content_language", legacy_language),
        supported_languages=SUPPORTED_LANGUAGES,
    )


@router.get("/prompts", response_model=PromptConfigResponse)
async def get_prompt_config(workspace_id: WorkspaceId) -> PromptConfigResponse:
    """Get current prompt configuration for resume tailoring."""
    stored = _load_config(workspace_id)
    options = _get_prompt_options()
    option_ids = {option.id for option in options}
    default_prompt_id = stored.get("default_prompt_id", DEFAULT_IMPROVE_PROMPT_ID)
    if default_prompt_id not in option_ids:
        default_prompt_id = DEFAULT_IMPROVE_PROMPT_ID

    return PromptConfigResponse(
        default_prompt_id=default_prompt_id,
        prompt_options=options,
    )


@router.put("/prompts", response_model=PromptConfigResponse)
async def update_prompt_config(
    request: PromptConfigRequest,
    workspace_id: WorkspaceId,
) -> PromptConfigResponse:
    """Update prompt configuration for resume tailoring."""
    stored = _load_config(workspace_id)
    options = _get_prompt_options()
    option_ids = {option.id for option in options}

    if request.default_prompt_id is not None:
        if request.default_prompt_id not in option_ids:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Unsupported prompt id: "
                    f"{request.default_prompt_id}. Supported: {sorted(option_ids)}"
                ),
            )
        stored["default_prompt_id"] = request.default_prompt_id

    await _save_overrides(workspace_id, stored, _PROMPT_KEYS)

    default_prompt_id = stored.get("default_prompt_id", DEFAULT_IMPROVE_PROMPT_ID)
    if default_prompt_id not in option_ids:
        default_prompt_id = DEFAULT_IMPROVE_PROMPT_ID

    return PromptConfigResponse(
        default_prompt_id=default_prompt_id,
        prompt_options=options,
    )


@router.get("/feature-prompts", response_model=FeaturePromptsResponse)
async def get_feature_prompts(workspace_id: WorkspaceId) -> FeaturePromptsResponse:
    """Get custom feature prompts (cover letter, outreach message).

    Empty strings mean "use default". The ``*_default`` fields expose the
    built-in prompts so the UI can show them as placeholder text without
    duplicating the content client-side.
    """
    stored = _load_config(workspace_id)
    return FeaturePromptsResponse(
        cover_letter_prompt=stored.get("cover_letter_prompt", "") or "",
        outreach_message_prompt=stored.get("outreach_message_prompt", "") or "",
        cover_letter_default=COVER_LETTER_PROMPT,
        outreach_message_default=OUTREACH_MESSAGE_PROMPT,
    )


@router.put("/feature-prompts", response_model=FeaturePromptsResponse)
async def update_feature_prompts(
    request: FeaturePromptsRequest,
    workspace_id: WorkspaceId,
) -> FeaturePromptsResponse:
    """Update custom feature prompts.

    Non-empty prompts are validated for the three required placeholders
    (``{job_description}``, ``{resume_data}``, ``{output_language}``).
    Missing placeholders return a 422 with a structured detail so the UI
    can list exactly which ones are absent. Empty strings clear the
    override — persisted as ``""`` so runtime resolution falls back to the
    built-in default.
    """
    stored = _load_config(workspace_id)

    if request.cover_letter_prompt is not None:
        prompt = request.cover_letter_prompt.strip()
        if prompt:
            missing = validate_prompt_placeholders(prompt)
            if missing:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "missing_placeholders",
                        "field": "cover_letter_prompt",
                        "missing": missing,
                    },
                )
        stored["cover_letter_prompt"] = prompt

    if request.outreach_message_prompt is not None:
        prompt = request.outreach_message_prompt.strip()
        if prompt:
            missing = validate_prompt_placeholders(prompt)
            if missing:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "missing_placeholders",
                        "field": "outreach_message_prompt",
                        "missing": missing,
                    },
                )
        stored["outreach_message_prompt"] = prompt

    await _save_overrides(workspace_id, stored, _FEATURE_PROMPT_KEYS)

    return FeaturePromptsResponse(
        cover_letter_prompt=stored.get("cover_letter_prompt", "") or "",
        outreach_message_prompt=stored.get("outreach_message_prompt", "") or "",
        cover_letter_default=COVER_LETTER_PROMPT,
        outreach_message_default=OUTREACH_MESSAGE_PROMPT,
    )


# Supported API key providers (key-store names). ``openai_compatible`` and
# ``ollama`` are included so secured local servers can store a key; they keep
# their env-fallback skip in resolve_api_key.
SUPPORTED_PROVIDERS = [
    "openai",
    "azure_foundry",
    "anthropic",
    "google",
    "openrouter",
    "deepseek",
    "groq",
    "openai_compatible",
    "ollama",
]


def _mask_key_short(key: str | None) -> str | None:
    """Mask API key showing only last 4 characters."""
    if not key:
        return None
    if len(key) <= 4:
        return "*" * len(key)
    return "..." + key[-4:]


@router.get("/api-keys", response_model=ApiKeyStatusResponse)
async def get_api_keys_status(workspace_id: WorkspaceId) -> ApiKeyStatusResponse:
    """Get status of all configured API keys (masked).

    Returns the configuration status for each supported provider.
    API keys are masked to show only the last 4 characters.
    """
    stored_keys = get_api_keys_from_config(workspace_id)

    providers = []
    for provider in SUPPORTED_PROVIDERS:
        key = stored_keys.get(provider)
        providers.append(
            ApiKeyProviderStatus(
                provider=provider,
                configured=bool(key),
                masked_key=_mask_key_short(key),
            )
        )

    return ApiKeyStatusResponse(providers=providers)


@router.post("/api-keys", response_model=ApiKeysUpdateResponse)
async def update_api_keys(
    request: ApiKeysUpdateRequest, workspace_id: WorkspaceId
) -> ApiKeysUpdateResponse:
    """Update API keys for one or more providers.

    Only updates the providers that are explicitly set in the request.
    Empty strings will clear the key for that provider.
    """
    stored_keys = get_api_keys_from_config(workspace_id)
    updated = []

    # Update each provider if provided in request
    if request.openai is not None:
        if request.openai:
            stored_keys["openai"] = request.openai
        elif "openai" in stored_keys:
            del stored_keys["openai"]
        updated.append("openai")

    if request.azure_foundry is not None:
        if request.azure_foundry:
            stored_keys["azure_foundry"] = request.azure_foundry
        elif "azure_foundry" in stored_keys:
            del stored_keys["azure_foundry"]
        updated.append("azure_foundry")

    if request.anthropic is not None:
        if request.anthropic:
            stored_keys["anthropic"] = request.anthropic
        elif "anthropic" in stored_keys:
            del stored_keys["anthropic"]
        updated.append("anthropic")

    if request.google is not None:
        if request.google:
            stored_keys["google"] = request.google
        elif "google" in stored_keys:
            del stored_keys["google"]
        updated.append("google")

    if request.openrouter is not None:
        if request.openrouter:
            stored_keys["openrouter"] = request.openrouter
        elif "openrouter" in stored_keys:
            del stored_keys["openrouter"]
        updated.append("openrouter")

    if request.deepseek is not None:
        if request.deepseek:
            stored_keys["deepseek"] = request.deepseek
        elif "deepseek" in stored_keys:
            del stored_keys["deepseek"]
        updated.append("deepseek")

    if request.groq is not None:
        if request.groq:
            stored_keys["groq"] = request.groq
        elif "groq" in stored_keys:
            del stored_keys["groq"]
        updated.append("groq")

    if request.openai_compatible is not None:
        if request.openai_compatible:
            stored_keys["openai_compatible"] = request.openai_compatible
        elif "openai_compatible" in stored_keys:
            del stored_keys["openai_compatible"]
        updated.append("openai_compatible")

    if request.ollama is not None:
        if request.ollama:
            stored_keys["ollama"] = request.ollama
        elif "ollama" in stored_keys:
            del stored_keys["ollama"]
        updated.append("ollama")

    save_api_keys_to_config(stored_keys, workspace_id)
    invalidate_config_cache(workspace_id)

    return ApiKeysUpdateResponse(
        message=f"Updated {len(updated)} API key(s)",
        updated_providers=updated,
    )


@router.delete("/api-keys")
async def delete_all_api_keys(
    workspace_id: WorkspaceId, confirm: str | None = None
) -> dict:
    """Clear all configured API keys.

    This is a destructive operation. Requires confirmation token.

    Args:
        confirm: Must be "CLEAR_ALL_KEYS" to execute

    Returns:
        Success message

    Note:
        Identity arrives from the upstream gateway, and this clears only the
        calling workspace's keys — another tenant's stay untouched.
    """
    if confirm != "CLEAR_ALL_KEYS":
        raise HTTPException(
            status_code=400,
            detail="Confirmation required. Pass confirm=CLEAR_ALL_KEYS query parameter.",
        )
    clear_all_api_keys(workspace_id)
    invalidate_config_cache(workspace_id)
    return {"message": "All API keys have been cleared"}


@router.delete("/api-keys/{provider}")
async def delete_api_key(provider: str, workspace_id: WorkspaceId) -> dict:
    """Delete API key for a specific provider.

    Args:
        provider: The provider name (openai, anthropic, google, openrouter, deepseek)

    Returns:
        Success message
    """
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported provider: {provider}. Supported: {SUPPORTED_PROVIDERS}",
        )

    delete_api_key_from_config(provider, workspace_id)
    invalidate_config_cache(workspace_id)

    return {"message": f"API key for {provider} has been removed"}


@router.post("/reset")
async def reset_database_endpoint(
    request: ResetDatabaseRequest, workspace_id: WorkspaceId
) -> dict:
    """Reset this workspace's data.

    WARNING: This action is irreversible. It truncates the workspace's
    resumes, version history, jobs, improvements, preview data and tracker
    cards. Its API keys and setting overrides are deliberately preserved.

    Requires confirmation token for safety.

    Args:
        request: Request body containing confirmation token

    Returns:
        Success message

    Note:
        Identity arrives from the upstream gateway, and this acts only on the
        calling workspace — another tenant's data is out of reach.
    """
    if request.confirm != "RESET_ALL_DATA":
        raise HTTPException(
            status_code=400,
            detail="Confirmation required. Pass confirm=RESET_ALL_DATA in request body.",
        )
    await db.reset_workspace(workspace_id)
    return {"message": "Database and all data have been reset successfully"}
