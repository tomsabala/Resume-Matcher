"""Schemas for the adaptive one-question-at-a-time AI resume wizard."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

from app.ai_limits import validate_source_size
from app.schemas.document import ResumeDocument

SECTION_TOKEN_PREFIX = "section:"

# A wizard turn targets either a fixed step or one section of the document.
# Sections are pure data, so a section target is addressed by the document's own
# section key (`section:military_service`) instead of a built-in enum.
FIXED_WIZARD_SECTIONS: tuple[str, ...] = ("intro", "contact", "review")

SECTION_TOKEN_PATTERN = r"^(?:intro|contact|review|section:[a-z0-9_]+)$"

ResumeWizardSection = Annotated[
    str, StringConstraints(pattern=SECTION_TOKEN_PATTERN, max_length=120)
]

ResumeWizardStep = Literal["intro", "question", "review", "complete"]

ResumeWizardAction = Literal["start", "answer", "skip", "back", "review"]


def section_token(key: str) -> str:
    """The wizard target token addressing the section with this key."""
    return f"{SECTION_TOKEN_PREFIX}{key}"


def token_section_key(token: str) -> str:
    """The section key inside a target token, or "" for a fixed step."""
    if token.startswith(SECTION_TOKEN_PREFIX):
        return token[len(SECTION_TOKEN_PREFIX) :]
    return ""


class ResumeWizardQuestion(BaseModel):
    """A single question the wizard asks."""

    text: str = Field(default="", max_length=2000)
    section: ResumeWizardSection = "intro"


class ResumeWizardProgress(BaseModel):
    """Server-computed progress for the question card's bar."""

    current: int = 0
    total: int = 8


class ResumeWizardAnswer(BaseModel):
    """User answer for one wizard turn."""

    text: str = Field(min_length=1, max_length=6000)

    @field_validator("text")
    @classmethod
    def _reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("answer text must not be blank")
        return value


class ResumeWizardHistoryEntry(BaseModel):
    """One answered question, with a pre-answer draft snapshot for Back."""

    question: str = Field(max_length=2000)
    answer: str = Field(max_length=6000)
    section: ResumeWizardSection
    resume_data_before: ResumeDocument


class ResumeWizardState(BaseModel):
    """Complete state that round-trips between client and server."""

    step: ResumeWizardStep = "intro"
    resume_data: ResumeDocument = Field(default_factory=ResumeDocument)
    current_question: ResumeWizardQuestion = Field(default_factory=ResumeWizardQuestion)
    history: list[ResumeWizardHistoryEntry] = Field(default_factory=list, max_length=15)
    asked_count: int = 0
    inferred_skills: list[Annotated[str, Field(max_length=200)]] = Field(
        default_factory=list, max_length=100
    )
    is_complete: bool = False
    progress: ResumeWizardProgress = Field(default_factory=ResumeWizardProgress)
    warnings: list[Annotated[str, Field(max_length=2000)]] = Field(
        default_factory=list, max_length=100
    )

    @model_validator(mode="after")
    def _validate_source_budget(self) -> "ResumeWizardState":
        validate_source_size(self.resume_data.model_dump(mode="json"))
        for entry in self.history:
            validate_source_size(entry.resume_data_before.model_dump(mode="json"))
        return self


class ResumeWizardTurnRequest(BaseModel):
    """Request for one wizard turn."""

    state: ResumeWizardState
    action: ResumeWizardAction
    answer: ResumeWizardAnswer | None = None

    @model_validator(mode="after")
    def _validate_answer_present(self) -> "ResumeWizardTurnRequest":
        if self.action == "answer" and self.answer is None:
            raise ValueError("answer is required for answer actions")
        return self


class ResumeWizardTurnResponse(BaseModel):
    """Response for one wizard turn."""

    state: ResumeWizardState


class ResumeWizardFinalizeRequest(BaseModel):
    """Request to create the master resume from the wizard draft."""

    state: ResumeWizardState

    @model_validator(mode="after")
    def _validate_ready_to_finalize(self) -> "ResumeWizardFinalizeRequest":
        if not self.state.resume_data.header.name.strip():
            raise ValueError("header.name is required")
        return self


class ResumeWizardFinalizeResponse(BaseModel):
    """Response after creating the master resume."""

    message: str
    request_id: str
    resume_id: str
    processing_status: Literal["ready"] = "ready"
    is_master: bool
