"""Formatting controls → LaTeX preamble values.

The builder's **Template & Formatting** panel speaks in levels — 1-9 on the
four spacing axes, 1-5 on the two font axes — and in millimetres; LaTeX wants
document-class options, a ``geometry`` option list and lengths in points. This
module is the single translation between the two, so the templates interpolate
ready-made strings and never do arithmetic.

Four spacing axes stay disjoint on purpose, because the panel adjusts them
independently: ``sectionSpacing`` only moves the section rhythm
(``\\titlespacing`` + the trailing ``\\vspace`` macros), ``itemSpacing`` only
the bullet/entry gaps, ``bulletLeadIn`` only the gap above a bullet list, and
``lineHeight`` only ``\\linespread``. ``parskip`` fixes ``\\parskip`` from the
class size at load time and does not follow ``\\linespread``, so leading
cannot leak into the other three.

``_section_end``'s collision floor is the one deliberate exception: the
trailing ``\\vspace`` is negative, and how far it may pull before the heading
prints through the line above depends on the leading and the font size as well
as on the section level. So a sub-single ``lineHeight`` shortens the pull. It
binds only there; every other combination gets the tuned trailer untouched.

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
    ``\\titlespacing`` before-gap from being counted twice. ``item_lead_pt`` is
    the template's own ``\\parskip``, the length that used to decide the gap
    above a bullet list implicitly; making it a baseline turns that accident
    into a knob without moving the neutral render. ``heading_gap_fit`` is a
    measured model of the gap a *neutral* section level produces —
    ``a * baselineskip + c * font_pt + b``, least squares over compiled
    fixtures, worst residual 0.5pt. Only ``_section_end`` reads it, to predict
    what it is about to produce before it floors it.
    """

    geometry_default: str
    margins_mm: tuple[float, float, float, float]  # top, bottom, left, right
    section_before_pt: float
    section_after_pt: float
    section_end_pt: float
    entry_gap_pt: float
    item_sep_pt: float
    item_lead_pt: float
    section_size: str
    gap_residual_pt: float
    heading_gap_fit: tuple[float, float, float]


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
        entry_gap_pt=1,
        item_sep_pt=2,
        item_lead_pt=6,
        section_size="\\large",
        gap_residual_pt=7,
        heading_gap_fit=(1.5809, 0.3542, -7.672),
    ),
    "tex-compact": TemplateBaseline(
        geometry_default="margin=1.2cm",
        margins_mm=(12, 12, 12, 12),
        section_before_pt=5,
        section_after_pt=2,
        section_end_pt=-9,
        entry_gap_pt=1,
        item_sep_pt=1,
        item_lead_pt=2,
        section_size="\\normalsize",
        gap_residual_pt=6,
        heading_gap_fit=(1.3815, 0.0695, -4.733),
    ),
}

# Level tables. The HTML renderer's maps divided by their own neutral value,
# so a level means the same relative change in both renderers. The spacing
# axes run 1-9; the font axes run 1-5, because `extarticle` offers 8/9/10/11/
# 12pt and nothing below 8pt, so there is no step to add below `fontSize` 1.
_SECTION_SCALE = {  # SECTION_SPACING_MAP / 16px
    1: 0.125,
    2: 0.25,
    3: 0.375,
    4: 0.625,
    5: 1.0,
    6: 1.25,
    7: 1.5,
    8: 2.0,
    9: 2.5,
}
_ITEM_SCALE = {  # ITEM_SPACING_MAP / 4px
    1: 0.0,
    2: 0.25,
    3: 0.5,
    4: 1.0,
    5: 2.0,
    6: 3.0,
    7: 4.0,
    8: 6.0,
    9: 8.0,
}
_LINESPREAD = {  # LINE_HEIGHT_MAP / 1.35
    1: 0.778,
    2: 0.815,
    3: 0.852,
    4: 0.926,
    5: 1.0,
    6: 1.074,
    7: 1.148,
    8: 1.259,
    9: 1.37,
}
_FONT_PT = {1: 8, 2: 9, 3: 10, 4: 11, 5: 12}
_HEADER_SHIFT = {1: -2, 2: -1, 3: 0, 4: 1, 5: 2}

_COMPACT_SPACING = 0.6  # frontend COMPACT_MULTIPLIER
_COMPACT_LINESPREAD = 0.92  # frontend COMPACT_LINE_HEIGHT_MULTIPLIER

# The neutral level per knob: the one that reproduces the baseline, and the
# frontend's DEFAULT_TEMPLATE_SETTINGS value. The spacing axes were widened
# from 1-5 to 1-9 by adding two steps at each end, so their neutral moved by
# +2 and every stored level had to move with it — see the ``settingsVersion``
# upgrade in `app/routers/resumes.py`.
_NEUTRAL = {
    "sectionSpacing": 5,
    "itemSpacing": 4,
    "bulletLeadIn": 4,
    "lineHeight": 5,
    "fontSize": 3,
    "headerScale": 3,
}

# Which table each knob reads, so the accepted vocabulary per knob is the
# table's own keys rather than a bound repeated here.
_LEVEL_TABLES: dict[str, dict[int, float]] = {
    "sectionSpacing": _SECTION_SCALE,
    "itemSpacing": _ITEM_SCALE,
    "bulletLeadIn": _ITEM_SCALE,
    "lineHeight": _LINESPREAD,
    "fontSize": _FONT_PT,
    "headerScale": _HEADER_SHIFT,
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
    """A level from ``settings``, falling back to the knob's neutral level.

    A level outside the knob's own table — 1-9 for the spacing axes, 1-5 for
    the font axes — is not clamped to the nearest end: it means the caller and
    this module disagree about the vocabulary, and the reference look is the
    only safe answer.
    """
    default = _NEUTRAL[key]
    value = settings.get(key, default)
    try:
        level = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return level if level in _LEVEL_TABLES[key] else default


def _pt(value: float) -> str:
    """A TeX length: ``-11.0`` → ``-11pt``, ``2.625`` → ``2.62pt``."""
    return f"{round(value, 2):g}pt"


def _scaled_size(base: str, shift: int) -> str:
    """``base`` moved ``shift`` steps along the size ladder, clamped."""
    index = _SIZE_LADDER.index(base) + shift
    return _SIZE_LADDER[max(0, min(index, len(_SIZE_LADDER) - 1))]


# The smallest baseline-to-baseline distance a heading may keep from the line
# above it, as a fraction of the base font size. A `\large` heading's cap
# height is about 0.84 of the base size and the line above hangs its
# descenders ~0.2 below its own baseline, so the ink meets at ~1.05 and this
# leaves a tenth of margin for the prediction's own error. Measured with
# `pdftotext -bbox` on a real resume: at the neutral font size a 9.8pt gap
# still overprinted nothing, 9.2pt printed five headings through the line
# above, and 11.5pt clears every font size and leading combination.
_MIN_HEADING_GAP_EM = 1.15


def _section_end(
    baseline: TemplateBaseline, section: float, spread: float, point_size: int
) -> float:
    """The trailing ``\\vspace``, floored so it cannot pull into the last line.

    The tuned trailer is negative and the section axis scales its residual, so
    the tight end of the axis asks for a pull larger than the line pitch and
    the heading overprints the text above it. That is reachable in the old 1-5
    vocabulary too (its level 1, and level 2 with tight leading); widening the
    axis only made it easier to reach, so the fix belongs here rather than in
    the level table.

    Only the tight combinations are floored: the prediction is the measured
    neutral-section gap plus what this level changes about it, and levels that
    already cleared the minimum come back untouched.
    """
    trailer = baseline.section_end_pt + (section - 1) * baseline.gap_residual_pt
    per_baselineskip, per_point, offset = baseline.heading_gap_fit
    neutral_gap = per_baselineskip * spread * 1.2 * point_size + per_point * point_size + offset
    predicted = (
        neutral_gap
        + (trailer - baseline.section_end_pt)
        + (section - 1) * baseline.section_before_pt
    )
    minimum = _MIN_HEADING_GAP_EM * point_size
    return trailer if predicted >= minimum else trailer + (minimum - predicted)


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
    ``/tex*`` routes, so a router hands its parsed dict straight through. Most
    are the Chromium ``/pdf`` route's parameters too; ``bulletLeadIn`` is the
    exception, because only the LaTeX templates have a list lead-in to move.
    Unknown keys are ignored; absent keys fall back to the neutral level,
    which is the template's reference look.
    """
    baseline = LATEX_BASELINES[template_id]

    compact = bool(settings.get("compactMode", False))
    section = _SECTION_SCALE[_level(settings, "sectionSpacing")] * (
        _COMPACT_SPACING if compact else 1.0
    )
    item = _ITEM_SCALE[_level(settings, "itemSpacing")] * (
        _COMPACT_SPACING if compact else 1.0
    )
    lead = _ITEM_SCALE[_level(settings, "bulletLeadIn")] * (
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
        "section_end": _pt(_section_end(baseline, section, spread, point_size)),
        "entry_gap": _pt(item * baseline.entry_gap_pt),
        "item_sep": _pt(item * baseline.item_sep_pt),
        "item_lead": _pt(lead * baseline.item_lead_pt),
        "name_size": _scaled_size("\\LARGE", shift),
        "headline_size": _scaled_size("\\large", shift),
    }
