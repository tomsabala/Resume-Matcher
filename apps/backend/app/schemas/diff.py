"""Shape of a structured document comparison.

The models live beside the other schemas rather than with the engine because
they are part of the API surface: ``POST /diff`` returns a ``DocumentDiff``
verbatim, and the tailoring responses embed one.
"""

from typing import Literal

from pydantic import BaseModel, Field

__all__ = [
    "DiffAnchor",
    "DiffRow",
    "DiffSpan",
    "DiffStats",
    "DocumentDiff",
    "RowKind",
    "RowStatus",
    "SectionDiff",
    "SectionStatus",
]

RowKind = Literal["entry", "bullet", "tag", "group", "text", "line"]
RowStatus = Literal["added", "removed", "modified", "moved", "unchanged"]
SectionStatus = Literal[
    "added", "removed", "renamed", "modified", "moved", "unchanged"
]


class DiffSpan(BaseModel):
    """A character range within one side of a modified row."""

    side: Literal["base", "head"]
    start: int
    end: int
    op: Literal["insert", "delete", "replace"]


class DiffAnchor(BaseModel):
    """Where a row lives, for scroll-to and partial accept."""

    section_id: str | None = None
    section_key: str | None = None
    entry_id: str | None = None
    index: int | None = None


class DiffRow(BaseModel):
    """One comparable line of the document."""

    kind: RowKind
    status: RowStatus
    # Grammar shared with `improver._resolve_path`, so a row can be accepted
    # individually by replaying the corresponding change.
    path: str
    base_text: str | None = None
    head_text: str | None = None
    # Word-level spans, populated only for `modified` rows.
    spans: list[DiffSpan] = Field(default_factory=list)
    anchor: DiffAnchor = Field(default_factory=DiffAnchor)


class SectionDiff(BaseModel):
    """One section's rows, plus how the section itself changed."""

    status: SectionStatus
    base_key: str | None = None
    head_key: str | None = None
    base_heading: str | None = None
    head_heading: str | None = None
    base_index: int | None = None
    head_index: int | None = None
    rows: list[DiffRow] = Field(default_factory=list)


class DiffStats(BaseModel):
    """Counts for the summary bar."""

    sections_added: int = 0
    sections_removed: int = 0
    sections_renamed: int = 0
    sections_moved: int = 0
    entries_added: int = 0
    entries_removed: int = 0
    entries_modified: int = 0
    entries_moved: int = 0
    bullets_added: int = 0
    bullets_removed: int = 0
    bullets_modified: int = 0
    tags_added: int = 0
    tags_removed: int = 0
    total_changes: int = 0


class DocumentDiff(BaseModel):
    """A whole comparison, grouped by section."""

    stats: DiffStats = Field(default_factory=DiffStats)
    header: list[DiffRow] = Field(default_factory=list)
    sections: list[SectionDiff] = Field(default_factory=list)
