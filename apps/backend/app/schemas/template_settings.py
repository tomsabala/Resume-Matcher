"""The template and formatting choice a resume carries.

Chosen in the builder's *Template & Formatting* panel and stored on the resume,
so the viewer and every export render what the user picked for *that* resume
rather than a per-browser default.

Presentation only: no document content lives here, which is why these settings
are not part of the version timeline — restoring an older document must not
also revert how it looks today.

Field names are camelCase because the frontend's ``TemplateSettings``
(`apps/frontend/lib/types/template-settings.ts`) is the same object, stored
verbatim; ``extra="forbid"`` keeps the two from drifting silently.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "HTML_TEMPLATES",
    "TEX_TEMPLATES",
    "TemplateSettings",
]

# The Chromium print route renders these; `tex-*` ids are compiled by the
# LaTeX engine instead. Both sets together are the ids a resume may store.
HTML_TEMPLATES = frozenset(
    {
        "swiss-single",
        "swiss-two-column",
        "modern",
        "modern-two-column",
        "latex",
        "clean",
        "vivid",
    }
)
TEX_TEMPLATES = frozenset({"tex-classic", "tex-compact"})

TemplateId = Literal[
    "swiss-single",
    "swiss-two-column",
    "modern",
    "modern-two-column",
    "latex",
    "clean",
    "vivid",
    "tex-classic",
    "tex-compact",
]
FontFamily = Literal["serif", "sans-serif", "mono"]


class MarginSettings(BaseModel):
    """Page margins in millimetres, matching the print route's bounds."""

    model_config = ConfigDict(extra="forbid")

    top: int = Field(10, ge=5, le=25)
    bottom: int = Field(10, ge=5, le=25)
    left: int = Field(10, ge=5, le=25)
    right: int = Field(10, ge=5, le=25)


class SpacingSettings(BaseModel):
    """Spacing steps, 1 (tightest) to 5 (loosest)."""

    model_config = ConfigDict(extra="forbid")

    section: int = Field(3, ge=1, le=5)
    item: int = Field(2, ge=1, le=5)
    lineHeight: int = Field(3, ge=1, le=5)


class FontSizeSettings(BaseModel):
    """Type scale steps plus the two font families."""

    model_config = ConfigDict(extra="forbid")

    base: int = Field(3, ge=1, le=5)
    headerScale: int = Field(3, ge=1, le=5)
    headerFont: FontFamily = "serif"
    bodyFont: FontFamily = "sans-serif"


class TemplateSettings(BaseModel):
    """One resume's presentation settings. Defaults mirror the frontend's."""

    model_config = ConfigDict(extra="forbid")

    template: TemplateId = "swiss-single"
    pageSize: Literal["A4", "LETTER"] = "A4"
    margins: MarginSettings = Field(default_factory=MarginSettings)
    spacing: SpacingSettings = Field(default_factory=SpacingSettings)
    fontSize: FontSizeSettings = Field(default_factory=FontSizeSettings)
    compactMode: bool = False
    showContactIcons: bool = False
    accentColor: Literal["blue", "green", "orange", "red"] = "blue"
