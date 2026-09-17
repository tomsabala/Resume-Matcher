"""Health, status and AI-diagnostics endpoints."""

import logging

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.ai_events import AIFailure, clear_ai_failures, recent_ai_failures
from app.database import db
from app.deps import WorkspaceId
from app.llm import check_llm_health, get_llm_config
from app.schemas import HealthResponse, StatusResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Health"])


class AIFailureItem(BaseModel):
    """One failed AI operation, as the dashboard renders it."""

    id: str
    at: str
    operation: str
    kind: str
    detail: str
    model: str | None = None
    provider: str | None = None
    attempts: int | None = None
    max_tokens: int | None = None


class AIFailureListResponse(BaseModel):
    """The recent-failure tail, newest first."""

    failures: list[AIFailureItem] = Field(default_factory=list)
    dismissed: int = 0


def _to_item(failure: AIFailure) -> AIFailureItem:
    return AIFailureItem(**failure.as_dict())


# Returned for database_stats when the stats query itself fails, so /status can
# still respond (degraded) instead of 500-ing.
_EMPTY_DB_STATS = {
    "total_resumes": 0,
    "total_jobs": 0,
    "total_improvements": 0,
    "has_master_resume": False,
}


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Lightweight liveness check for Docker HEALTHCHECK.

    Does NOT call the LLM provider. Use GET /status for full LLM health.
    """
    return HealthResponse(status="healthy")


@router.get("/status", response_model=StatusResponse)
async def get_status(workspace_id: WorkspaceId) -> StatusResponse:
    """Get comprehensive application status.

    Each subsystem check is isolated: a failure in the LLM health probe or the
    database stats query degrades only its own field instead of 500-ing the
    whole endpoint, so the status page can still report partial/degraded state.
    """
    llm_configured = False
    llm_healthy = False
    try:
        config = get_llm_config()
        # ollama / openai_compatible run without a key, matching check_llm_health.
        llm_configured = bool(config.api_key) or config.provider in ("ollama", "openai_compatible")
        llm_status = await check_llm_health(config)
        llm_healthy = bool(llm_status.get("healthy"))
    except Exception:
        logger.exception("Status: LLM health check failed")

    db_stats: dict = dict(_EMPTY_DB_STATS)
    try:
        db_stats = await db.get_stats(workspace_id)
    except Exception:
        logger.exception("Status: database stats failed")

    has_master_resume = bool(db_stats.get("has_master_resume"))

    return StatusResponse(
        status="ready" if llm_healthy and has_master_resume else "setup_required",
        llm_configured=llm_configured,
        llm_healthy=llm_healthy,
        has_master_resume=has_master_resume,
        database_stats=db_stats,
    )


@router.get("/diagnostics/ai-failures", response_model=AIFailureListResponse)
async def list_ai_failures(workspace_id: WorkspaceId) -> AIFailureListResponse:
    """This workspace's recent AI failures, newest first.

    The dashboard shows these so a truncated or rejected model answer is
    visible as a cause instead of a generic "please try again". The records
    carry no prompt, resume or model output — only the shape of the failure.
    """
    return AIFailureListResponse(
        failures=[_to_item(failure) for failure in recent_ai_failures(workspace_id)]
    )


@router.delete("/diagnostics/ai-failures", response_model=AIFailureListResponse)
async def dismiss_ai_failures(workspace_id: WorkspaceId) -> AIFailureListResponse:
    """Drop the tracked failures once the user has read them."""
    return AIFailureListResponse(dismissed=clear_ai_failures(workspace_id))
