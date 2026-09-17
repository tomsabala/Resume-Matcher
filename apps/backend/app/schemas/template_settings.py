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
    """Spacing steps, 1 (tightest) to 9 (loosest).

    ``bulletLeadIn`` is the gap above a bullet list. It only reaches the LaTeX
    templates — the Chromium renderer has no equivalent length — but it is
    stored with the rest, because it is part of the look the user chose.
    """

    model_config = ConfigDict(extra="forbid")

    section: int = Field(5, ge=1, le=9)
    item: int = Field(4, ge=1, le=9)
    bulletLeadIn: int = Field(4, ge=1, le=9)
    lineHeight: int = Field(5, ge=1, le=9)


class FontSizeSettings(BaseModel):
    """Type scale steps plus the two font families.

    1-5, not 1-9 like the spacing axes: ``extarticle`` offers 8/9/10/11/12pt
    and nothing below 8pt, so there is no honest step to add downward.
    """

    model_config = ConfigDict(extra="forbid")

    base: int = Field(3, ge=1, le=5)
    headerScale: int = Field(3, ge=1, le=5)
    headerFont: FontFamily = "serif"
    bodyFont: FontFamily = "sans-serif"


class TemplateSettings(BaseModel):
    """One resume's presentation settings. Defaults mirror the frontend's.

    ``settingsVersion`` tells a stored payload's level vocabulary apart from
    its predecessor's: the spacing axes used to run 1-5 and now run 1-9, so
    the two ranges overlap and the levels alone are ambiguous. It is
    *required*, deliberately: a body without it comes from a client speaking
    v1, and a 422 it can see beats silently storing its levels two steps
    tighter than the user chose. Rows already in the database predate the
    marker, so `app/routers/resumes.py` upgrades those on read.
    """

    model_config = ConfigDict(extra="forbid")

    settingsVersion: Literal[2]
    template: TemplateId = "swiss-single"
    pageSize: Literal["A4", "LETTER"] = "A4"
    margins: MarginSettings = Field(default_factory=MarginSettings)
    spacing: SpacingSettings = Field(default_factory=SpacingSettings)
    fontSize: FontSizeSettings = Field(default_factory=FontSizeSettings)
    compactMode: bool = False
    showContactIcons: bool = False
    accentColor: Literal["blue", "green", "orange", "red"] = "blue"
