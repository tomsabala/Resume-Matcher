"""Pydantic schemas for the LaTeX source endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = [
    "TexCapabilities",
    "TexSourceResponse",
    "TexSourceUpdate",
]

# A resume that needs more than this is not a resume. The cap bounds both the
# request body and what a compile can be asked to chew on.
MAX_TEX_SOURCE_CHARS = 400_000


class TexSourceResponse(BaseModel):
    """The LaTeX for a resume, and where it came from."""

    resume_id: str
    source: str
    # True when the user has saved their own source: the document no longer
    # drives the .tex, so the UI must say so before an edit is lost.
    is_override: bool
    template: str
    # Engine availability travels with the source so the UI can offer
    # "Download .tex" instead of "Download PDF" without a second request.
    engine: str | None = None


class TexSourceUpdate(BaseModel):
    """Save hand-edited LaTeX as the resume's source of truth."""

    source: str = Field(min_length=1, max_length=MAX_TEX_SOURCE_CHARS)


class TexCapabilities(BaseModel):
    """What this deployment can do with LaTeX."""

    # None when no engine is installed: generation and editing still work,
    # only in-container compilation is unavailable.
    engine: str | None
    can_compile: bool
    templates: list[str]
