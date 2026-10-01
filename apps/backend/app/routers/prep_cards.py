"""Interview-prep flashcard deck endpoints.

Workspace-global, unlike the per-resume ``interview_prep`` builder tab. The
three POST endpoints that call an LLM carry no feature flag: with no provider
configured they fail with the standard 500/503/504, like cover-letter
generation.
"""

import logging

from fastapi import APIRouter, HTTPException, Query

from app.ai_budget import AIOperationDeadlineExceeded, AIOperationRoute
from app.ai_limits import MAX_JOB_CHARACTERS, PromptSizeError, require_source_size
from app.database import DatabaseBusyError, db
from app.deps import OutputLanguage, WorkspaceId
from app.schemas import (
    PrepCardActionResponse,
    PrepCardBulkCreate,
    PrepCardCategory,
    PrepCardCreate,
    PrepCardCritiqueRequest,
    PrepCardDelete,
    PrepCardGenerateRequest,
    PrepCardGenerateResponse,
    PrepCardListResponse,
    PrepCardResponse,
    PrepCardUpdate,
)
from app.services.prep_cards import (
    answer_prep_card,
    critique_prep_answer,
    generate_prep_cards,
)

logger = logging.getLogger(__name__)

# AIOperationRoute wraps POST handlers in the request deadline and maps
# PromptSizeError -> 422 and TimeoutError -> 504. A no-op for the CRUD verbs.
router = APIRouter(
    route_class=AIOperationRoute, prefix="/prep-cards", tags=["Interview Prep"]
)

#: Columns a PATCH may legitimately clear. Everything else drops a null rather
#: than writing one, so an explicit ``"category": null`` cannot blank a column.
_NULLABLE_UPDATES = frozenset(
    {"answer", "explanation", "examples", "my_answer", "application_id"}
)


async def _require_resume_data(workspace_id: str) -> dict:
    """The master resume's parsed content, which grounds every LLM call."""
    master = await db.get_master_resume(workspace_id)
    if not master or not master.get("processed_data"):
        raise HTTPException(
            status_code=400,
            detail="Create a master resume first so answers can be grounded in it.",
        )
    return master["processed_data"]


async def _job_description_for(
    application_id: str | None, workspace_id: str
) -> str | None:
    """The linked interview's JD, when there is one.

    A deleted application or job degrades to ``None``: the card still works, it
    just loses job-specific grounding.
    """
    if not application_id:
        return None
    application = await db.get_application(application_id, workspace_id=workspace_id)
    if not application:
        return None
    job = await db.get_job(application["job_id"], workspace_id=workspace_id)
    if not job:
        return None
    content = job.get("content") or ""
    require_source_size(content, MAX_JOB_CHARACTERS)
    return content


@router.get("", response_model=PrepCardListResponse)
async def list_prep_cards(
    workspace_id: WorkspaceId,
    category: PrepCardCategory | None = Query(None),
) -> PrepCardListResponse:
    """List the active workspace's prep cards, newest first."""
    try:
        cards = await db.list_prep_cards(
            workspace_id=workspace_id,
            category=category.value if category else None,
        )
    except DatabaseBusyError:
        raise
    except Exception as e:
        logger.error("Failed to list prep cards: %s", e)
        raise HTTPException(
            status_code=500, detail="Failed to load cards. Please try again."
        )
    return PrepCardListResponse(cards=[PrepCardResponse(**card) for card in cards])


@router.post("", response_model=PrepCardResponse)
async def create_prep_card(
    request: PrepCardCreate, workspace_id: WorkspaceId
) -> PrepCardResponse:
    """Create one card by hand."""
    try:
        card = await db.create_prep_card(
            workspace_id=workspace_id,
            category=request.category.value,
            question=request.question,
            answer=request.answer,
            explanation=request.explanation,
            examples=request.examples,
            application_id=request.application_id,
            source="manual",
        )
    except DatabaseBusyError:
        raise
    except Exception as e:
        logger.error("Failed to create prep card: %s", e)
        raise HTTPException(
            status_code=500, detail="Failed to save card. Please try again."
        )
    return PrepCardResponse(**card)


@router.post("/bulk-create", response_model=PrepCardListResponse)
async def bulk_create_prep_cards(
    request: PrepCardBulkCreate, workspace_id: WorkspaceId
) -> PrepCardListResponse:
    """Accept a reviewed batch of proposals into the deck."""
    try:
        cards = await db.create_prep_cards(
            [
                {
                    "category": card.category.value,
                    "question": card.question,
                    "answer": card.answer,
                    "explanation": card.explanation,
                    "examples": card.examples,
                    "application_id": card.application_id,
                    "source": "generated",
                }
                for card in request.cards
            ],
            workspace_id=workspace_id,
        )
    except DatabaseBusyError:
        raise
    except Exception as e:
        logger.error("Failed to bulk-create prep cards: %s", e)
        raise HTTPException(
            status_code=500, detail="Failed to save cards. Please try again."
        )
    return PrepCardListResponse(cards=[PrepCardResponse(**card) for card in cards])


@router.post("/bulk-delete", response_model=PrepCardActionResponse)
async def bulk_delete_prep_cards(
    request: PrepCardDelete, workspace_id: WorkspaceId
) -> PrepCardActionResponse:
    """Delete many cards at once."""
    try:
        deleted = await db.bulk_delete_prep_cards(
            request.card_ids, workspace_id=workspace_id
        )
    except DatabaseBusyError:
        raise
    except Exception as e:
        logger.error("Failed to bulk-delete prep cards: %s", e)
        raise HTTPException(
            status_code=500, detail="Failed to delete cards. Please try again."
        )
    return PrepCardActionResponse(message=f"Deleted {deleted} card(s)", affected=deleted)


@router.post("/generate", response_model=PrepCardGenerateResponse)
async def generate_prep_card_proposals(
    request: PrepCardGenerateRequest,
    workspace_id: WorkspaceId,
    output_language: OutputLanguage,
) -> PrepCardGenerateResponse:
    """Propose questions from the master resume. Persists nothing."""
    resume_data = await _require_resume_data(workspace_id)
    job_description = await _job_description_for(request.application_id, workspace_id)

    try:
        proposals = await generate_prep_cards(
            category=request.category.value,
            resume_data=resume_data,
            job_description=job_description,
            count=request.count,
            output_language=output_language,
        )
    except (DatabaseBusyError, AIOperationDeadlineExceeded, PromptSizeError):
        raise
    except Exception as e:
        logger.exception("Prep card generation failed: %s", e)
        raise HTTPException(
            status_code=500, detail="Failed to generate cards. Please try again."
        )
    return PrepCardGenerateResponse(proposals=proposals)


@router.get("/{card_id}", response_model=PrepCardResponse)
async def get_prep_card(card_id: str, workspace_id: WorkspaceId) -> PrepCardResponse:
    """Get one card."""
    try:
        card = await db.get_prep_card(card_id, workspace_id=workspace_id)
    except DatabaseBusyError:
        raise
    except Exception as e:
        logger.error("Failed to load prep card %s: %s", card_id, e)
        raise HTTPException(
            status_code=500, detail="Failed to load card. Please try again."
        )
    if card is None:
        raise HTTPException(status_code=404, detail="Card not found")
    return PrepCardResponse(**card)


@router.post("/{card_id}/answer", response_model=PrepCardResponse)
async def answer_prep_card_endpoint(
    card_id: str,
    workspace_id: WorkspaceId,
    output_language: OutputLanguage,
) -> PrepCardResponse:
    """Author the back of one card and store it."""
    card = await db.get_prep_card(card_id, workspace_id=workspace_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Card not found")

    resume_data = await _require_resume_data(workspace_id)
    job_description = await _job_description_for(card["application_id"], workspace_id)

    try:
        generated = await answer_prep_card(
            category=card["category"],
            question=card["question"],
            resume_data=resume_data,
            job_description=job_description,
            output_language=output_language,
        )
    except (DatabaseBusyError, AIOperationDeadlineExceeded, PromptSizeError):
        raise
    except Exception as e:
        logger.exception("Prep card answer generation failed: %s", e)
        raise HTTPException(
            status_code=500, detail="Failed to generate an answer. Please try again."
        )

    updated = await db.update_prep_card(
        card_id,
        {
            "answer": generated.answer,
            "explanation": generated.explanation,
            "examples": generated.examples,
        },
        workspace_id=workspace_id,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Card not found")
    return PrepCardResponse(**updated)


@router.post("/{card_id}/critique", response_model=PrepCardResponse)
async def critique_prep_card_endpoint(
    card_id: str,
    request: PrepCardCritiqueRequest,
    workspace_id: WorkspaceId,
    output_language: OutputLanguage,
) -> PrepCardResponse:
    """Store the owner's own answer and the LLM's critique of it."""
    card = await db.get_prep_card(card_id, workspace_id=workspace_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Card not found")

    resume_data = await _require_resume_data(workspace_id)

    try:
        critique = await critique_prep_answer(
            question=card["question"],
            my_answer=request.my_answer,
            model_answer=card["answer"],
            resume_data=resume_data,
            output_language=output_language,
        )
    except (DatabaseBusyError, AIOperationDeadlineExceeded, PromptSizeError):
        raise
    except Exception as e:
        logger.exception("Prep card critique failed: %s", e)
        raise HTTPException(
            status_code=500, detail="Failed to review the answer. Please try again."
        )

    updated = await db.update_prep_card(
        card_id,
        {
            "my_answer": request.my_answer,
            "critique": critique.model_dump(mode="json"),
        },
        workspace_id=workspace_id,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Card not found")
    return PrepCardResponse(**updated)


@router.patch("/{card_id}", response_model=PrepCardResponse)
async def update_prep_card(
    card_id: str, request: PrepCardUpdate, workspace_id: WorkspaceId
) -> PrepCardResponse:
    """Update a card (question/answer/category/confidence/own answer)."""
    updates = {
        key: value
        for key, value in request.model_dump(exclude_unset=True).items()
        if value is not None or key in _NULLABLE_UPDATES
    }
    # Normalize the enums to their stable string values for the data layer.
    for key in ("category", "confidence"):
        if updates.get(key) is not None:
            updates[key] = updates[key].value

    try:
        updated = await db.update_prep_card(card_id, updates, workspace_id=workspace_id)
    except DatabaseBusyError:
        raise
    except Exception as e:
        logger.error("Failed to update prep card %s: %s", card_id, e)
        raise HTTPException(
            status_code=500, detail="Failed to save card. Please try again."
        )
    if updated is None:
        raise HTTPException(status_code=404, detail="Card not found")
    return PrepCardResponse(**updated)


@router.delete("/{card_id}", response_model=PrepCardActionResponse)
async def delete_prep_card(
    card_id: str, workspace_id: WorkspaceId
) -> PrepCardActionResponse:
    """Delete one card."""
    try:
        deleted = await db.delete_prep_card(card_id, workspace_id=workspace_id)
    except DatabaseBusyError:
        raise
    except Exception as e:
        logger.error("Failed to delete prep card %s: %s", card_id, e)
        raise HTTPException(
            status_code=500, detail="Failed to delete card. Please try again."
        )
    if not deleted:
        raise HTTPException(status_code=404, detail="Card not found")
    return PrepCardActionResponse(message="Deleted 1 card(s)", affected=1)
