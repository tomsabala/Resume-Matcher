"""Pydantic schemas for the interview-prep flashcard deck.

Distinct from ``app.schemas.models.InterviewPrepData``, which is the per-resume
builder tab's payload. These models back the workspace-global deck.
"""

from enum import Enum

from pydantic import BaseModel, Field


class PrepCardCategory(str, Enum):
    """``technical`` is the flip-card game; ``personal`` is the rehearsal list."""

    technical = "technical"
    personal = "personal"


class PrepCardConfidence(str, Enum):
    """Manual three-way rating; there is no scheduling algorithm."""

    unrated = "unrated"
    again = "again"
    good = "good"
    easy = "easy"


class PrepCardCritique(BaseModel):
    """The LLM's assessment of the owner's own answer."""

    score: int = Field(ge=1, le=5)
    strengths: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    suggested_rewrite: str


class PrepCardResponse(BaseModel):
    """One card, front and back."""

    card_id: str
    category: PrepCardCategory
    question: str
    answer: str | None = None
    explanation: str | None = None
    examples: list[str] | None = None
    my_answer: str | None = None
    critique: PrepCardCritique | None = None
    confidence: PrepCardConfidence
    source: str
    application_id: str | None = None
    reviewed_at: str | None = None
    created_at: str
    updated_at: str


class PrepCardListResponse(BaseModel):
    cards: list[PrepCardResponse]


class PrepCardCreate(BaseModel):
    category: PrepCardCategory = PrepCardCategory.technical
    question: str = Field(min_length=1, max_length=2000)
    answer: str | None = None
    explanation: str | None = None
    examples: list[str] | None = None
    application_id: str | None = None


class PrepCardBulkCreate(BaseModel):
    cards: list[PrepCardCreate] = Field(min_length=1, max_length=50)


class PrepCardUpdate(BaseModel):
    category: PrepCardCategory | None = None
    question: str | None = Field(default=None, min_length=1, max_length=2000)
    answer: str | None = None
    explanation: str | None = None
    examples: list[str] | None = None
    my_answer: str | None = None
    confidence: PrepCardConfidence | None = None
    application_id: str | None = None


class PrepCardDelete(BaseModel):
    card_ids: list[str] = Field(min_length=1)


class PrepCardActionResponse(BaseModel):
    message: str
    affected: int


class PrepCardAnswer(BaseModel):
    """The back of a card, as the LLM returns it."""

    answer: str
    explanation: str
    examples: list[str] = Field(default_factory=list)


class PrepCardProposal(BaseModel):
    """A generated question the user has not accepted yet.

    ``category`` defaults because the generator prompt asks only for questions:
    the service forces the requested category on, never trusting a model echo.
    """

    category: PrepCardCategory = PrepCardCategory.technical
    question: str
    explanation: str | None = None


class PrepCardGenerateRequest(BaseModel):
    category: PrepCardCategory
    count: int = Field(default=8, ge=1, le=20)
    application_id: str | None = None


class PrepCardGenerateResponse(BaseModel):
    proposals: list[PrepCardProposal]


class PrepCardCritiqueRequest(BaseModel):
    my_answer: str = Field(min_length=1, max_length=10_000)
