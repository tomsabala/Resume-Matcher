"""Pydantic schemas for resume version history."""

from typing import Any, Literal

from pydantic import BaseModel, Field

# What produced a version. Only ``manual`` ever coalesces; every other origin
# is a deliberate checkpoint the user may want to return to.
VersionOrigin = Literal[
    "import", "manual", "ai_tailor", "ai_enrich", "wizard", "restore", "tex_edit"
]
TexSourceMode = Literal["generated", "edited"]


class VersionSummary(BaseModel):
    """One version's metadata. Deliberately excludes the document payload —
    a history list must not ship one full resume per row."""

    version_id: str
    resume_id: str
    workspace_id: str
    parent_version_id: str | None = None
    content_hash: str
    label: str | None = None
    origin: VersionOrigin
    origin_ref: str | None = None
    is_pinned: bool = False
    is_head: bool = False
    tex_source_mode: TexSourceMode = "generated"
    created_at: str


class VersionDetail(VersionSummary):
    """One version including its stored document."""

    document: dict[str, Any]
    tex_source: str | None = None


class VersionListResponse(BaseModel):
    """A page of history, newest first."""

    versions: list[VersionSummary]
    next_cursor: str | None = None


class VersionUpdateRequest(BaseModel):
    """Set a version's user label or pin. Content is immutable."""

    label: str | None = Field(default=None, max_length=120)
    is_pinned: bool | None = None


class RestoreVersionRequest(BaseModel):
    """Restore a past version by writing it forward as a new head."""

    version_id: str
