"""Formatting controls → LaTeX preamble values.

The builder's **Template & Formatting** panel speaks in levels (1-5) and
millimetres; LaTeX wants document-class options, a ``geometry`` option list and
lengths in points. This module is the single translation between the two, so
the templates interpolate ready-made strings and never do arithmetic.

Three spacing axes stay disjoint on purpose, because the panel adjusts them
independently: ``sectionSpacing`` only moves the section rhythm
(``\\titlespacing`` + the trailing ``\\vspace`` macros), ``itemSpacing`` only
the bullet/entry gaps, ``lineHeight`` only ``\\linespread``. ``parskip`` fixes
``\\parskip`` from the class size at load time and does not follow
``\\linespread``, so leading cannot leak into the other two.

Every level table's neutral entry reproduces the per-template baseline
exactly, and the neutral level matches the frontend default for that knob, so
a builder render at default settings equals a parameterless render of the
reference CV.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["LATEX_BASELINES", "tex_layout"]


@dataclass(frozen=True, slots=True)
class TemplateBaseline:
    """One template's un-scaled formatting, i.e. its reference look.

    ``gap_residual_pt`` is the measured gap from a section's last body line to
    the next heading minus ``section_before_pt``: the part of that gap the
    trailing ``\\vspace`` owns. Scaling only the residual keeps the
    ``\\titlespacing`` before-gap from being counted twice.
    """

    geometry_default: str
    margins_mm: tuple[float, float, float, float]  # top, bottom, left, right
    section_before_pt: float
    section_after_pt: float
    section_end_pt: float
    block_end_pt: float
    entry_gap_pt: float
    item_sep_pt: float
    section_size: str
    gap_residual_pt: float


# Today's literals from `classic.tex.j2` / `compact.tex.j2`. `margins_mm` is
# the A4 equivalent of each template's default geometry, used per side when
# that side has no explicit value.
LATEX_BASELINES: dict[str, TemplateBaseline] = {
    "tex-classic": TemplateBaseline(
        geometry_default="scale=0.9",
        margins_mm=(14.85, 14.85, 10.5, 10.5),
        section_before_pt=7,
        section_after_pt=4,
        section_end_pt=-11,
        block_end_pt=-2,
        entry_gap_pt=1,
        item_sep_pt=2,
        section_size="\\large",
        gap_residual_pt=7,
    ),
    "tex-compact": TemplateBaseline(
        geometry_default="margin=1.2cm",
        margins_mm=(12, 12, 12, 12),
        section_before_pt=5,
        section_after_pt=2,
        section_end_pt=-9,
        block_end_pt=-2,
        entry_gap_pt=1,
        item_sep_pt=1,
        section_size="\\normalsize",
        gap_residual_pt=6,
    ),
}

# Level tables. The HTML renderer's maps divided by their own neutral value,
# so a level means the same relative change in both renderers.
_SECTION_SCALE = {1: 0.375, 2: 0.625, 3: 1.0, 4: 1.25, 5: 1.5}  # SECTION_SPACING_MAP / 16px
_ITEM_SCALE = {1: 0.5, 2: 1.0, 3: 2.0, 4: 3.0, 5: 4.0}  # ITEM_SPACING_MAP / 4px
_LINESPREAD = {1: 0.852, 2: 0.926, 3: 1.0, 4: 1.074, 5: 1.148}  # LINE_HEIGHT_MAP / 1.35
_FONT_PT = {1: 8, 2: 9, 3: 10, 4: 11, 5: 12}
_HEADER_SHIFT = {1: -2, 2: -1, 3: 0, 4: 1, 5: 2}

_COMPACT_SPACING = 0.6  # frontend COMPACT_MULTIPLIER
_COMPACT_LINESPREAD = 0.92  # frontend COMPACT_LINE_HEIGHT_MULTIPLIER

# The neutral level per knob: the one that reproduces the baseline, and the
# frontend's DEFAULT_TEMPLATE_SETTINGS value.
_NEUTRAL = {
    "sectionSpacing": 3,
    "itemSpacing": 2,
    "lineHeight": 3,
    "fontSize": 3,
    "headerScale": 3,
}

# LaTeX's size commands in order, so a header scale is a step along a ladder
# rather than a font-size calculation the class would fight.
_SIZE_LADDER = [
    "\\tiny",
    "\\scriptsize",
    "\\footnotesize",
    "\\small",
    "\\normalsize",
    "\\large",
    "\\Large",
    "\\LARGE",
    "\\huge",
    "\\Huge",
]

_MARGIN_KEYS = ("marginTop", "marginBottom", "marginLeft", "marginRight")
_MARGIN_SIDES = ("top", "bottom", "left", "right")


def _level(settings: dict[str, object], key: str) -> int:
    """A 1-5 level from ``settings``, falling back to the neutral level."""
    default = _NEUTRAL[key]
    value = settings.get(key, default)
    try:
        level = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return level if 1 <= level <= 5 else default


def _pt(value: float) -> str:
    """A TeX length: ``-11.0`` → ``-11pt``, ``2.625`` → ``2.62pt``."""
    return f"{round(value, 2):g}pt"


def _scaled_size(base: str, shift: int) -> str:
    """``base`` moved ``shift`` steps along the size ladder, clamped."""
    index = _SIZE_LADDER.index(base) + shift
    return _SIZE_LADDER[max(0, min(index, len(_SIZE_LADDER) - 1))]


def _geometry(baseline: TemplateBaseline, settings: dict[str, object]) -> str:
    """The ``geometry`` option list.

    With no margin parameter at all the template's paper-proportional default
    is kept verbatim: a parameterless ``GET /tex`` must still be the reference
    CV. One explicit side switches to per-side millimetres, the other sides
    taking the baseline's equivalent.
    """
    values = [settings.get(key) for key in _MARGIN_KEYS]
    if all(value is None for value in values):
        return baseline.geometry_default
    sides = zip(_MARGIN_SIDES, values, baseline.margins_mm, strict=True)
    return ",".join(
        f"{side}={(fallback if value is None else float(value)):g}mm"  # type: ignore[arg-type]
        for side, value, fallback in sides
    )


def tex_layout(template_id: str, settings: dict[str, object]) -> dict[str, str]:
    """Ready-to-interpolate preamble values for one template + settings dict.

    ``settings`` keys are spelled exactly like the query parameters of the
    ``/tex*`` routes (and the Chromium ``/pdf`` route), so a router hands its
    parsed dict straight through. Unknown keys are ignored; absent keys fall
    back to the neutral level, which is the template's reference look.
    """
    baseline = LATEX_BASELINES[template_id]

    compact = bool(settings.get("compactMode", False))
    section = _SECTION_SCALE[_level(settings, "sectionSpacing")] * (
        _COMPACT_SPACING if compact else 1.0
    )
    item = _ITEM_SCALE[_level(settings, "itemSpacing")] * (
        _COMPACT_SPACING if compact else 1.0
    )
    spread = round(
        _LINESPREAD[_level(settings, "lineHeight")]
        * (_COMPACT_LINESPREAD if compact else 1.0),
        3,
    )

    # `article` only offers 10/11/12pt; `extarticle` (extsizes) adds 8pt and
    # 9pt and inputs the stock size10.clo at 10pt, so the neutral level is
    # byte-identical to before.
    point_size = _FONT_PT[_level(settings, "fontSize")]
    document_class = "extarticle" if point_size < 10 else "article"
    paper = "letterpaper" if settings.get("pageSize") == "LETTER" else "a4paper"

    shift = _HEADER_SHIFT[_level(settings, "headerScale")]

    return {
        "documentclass": f"\\documentclass[{paper},{point_size}pt]{{{document_class}}}",
        "geometry": _geometry(baseline, settings),
        "linespread": f"{spread:g}",
        "section_size": _scaled_size(baseline.section_size, shift),
        "section_before": _pt(section * baseline.section_before_pt),
        "section_after": _pt(section * baseline.section_after_pt),
        "section_end": _pt(
            baseline.section_end_pt + (section - 1) * baseline.gap_residual_pt
        ),
        "block_end": _pt(
            baseline.block_end_pt + (section - 1) * baseline.gap_residual_pt
        ),
        "entry_gap": _pt(item * baseline.entry_gap_pt),
        "item_sep": _pt(item * baseline.item_sep_pt),
        "name_size": _scaled_size("\\LARGE", shift),
        "headline_size": _scaled_size("\\large", shift),
    }
