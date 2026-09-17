"""Formatting levels → LaTeX preamble values.

The panel's controls and the engine's lengths are different vocabularies, and
the translation is where "adjust section spacing" can quietly become "adjust
everything". These tests pin the reference look at default levels and the
independence of the four spacing axes.
"""

import pytest

from app.latex.layout import LATEX_BASELINES, tex_layout
from app.latex.render import LATEX_TEMPLATES

pytestmark = pytest.mark.unit

NEUTRAL: dict[str, object] = {
    "pageSize": "A4",
    "sectionSpacing": 5,
    "itemSpacing": 4,
    "bulletLeadIn": 4,
    "lineHeight": 5,
    "fontSize": 3,
    "headerScale": 3,
    "compactMode": False,
}

# The vocabulary per axis: the spacing axes were widened to 1-9, the font
# axes stay 1-5 because `extarticle` has nothing below 8pt.
_SPACING_LEVELS = (1, 2, 3, 4, 5, 6, 7, 8, 9)
_FONT_LEVELS = (1, 2, 3, 4, 5)

_SECTION_KEYS = ("section_before", "section_after", "section_end")
_ITEM_KEYS = ("entry_gap", "item_sep")
_LEAD_KEYS = ("item_lead",)
_SIZE_KEYS = ("documentclass", "name_size", "headline_size", "section_size")


def _layout(template_id: str = "tex-classic", **overrides: object) -> dict[str, str]:
    return tex_layout(template_id, {**NEUTRAL, **overrides})


@pytest.mark.parametrize(
    "template_id,geometry,section_end,section_size,item_sep,item_lead",
    [
        ("tex-classic", "scale=0.9", "-11pt", "\\large", "2pt", "6pt"),
        ("tex-compact", "margin=1.2cm", "-9pt", "\\normalsize", "1pt", "2pt"),
    ],
)
def test_default_levels_reproduce_the_reference_cv(
    template_id: str,
    geometry: str,
    section_end: str,
    section_size: str,
    item_sep: str,
    item_lead: str,
) -> None:
    """Every knob at its frontend default must render the tuned baseline, or
    opening the builder silently reformats every existing tex resume."""
    layout = _layout(template_id)

    assert layout["documentclass"] == "\\documentclass[a4paper,10pt]{article}"
    assert layout["geometry"] == geometry
    assert layout["linespread"] == "1"
    assert layout["section_end"] == section_end
    assert layout["section_size"] == section_size
    assert layout["item_sep"] == item_sep
    assert layout["item_lead"] == item_lead
    assert layout["name_size"] == "\\LARGE"
    assert layout["headline_size"] == "\\large"


def test_settings_with_no_formatting_keys_at_all_are_the_baseline_too() -> None:
    """A parameterless ``GET /tex`` and the diff view pass ``{}``."""
    assert tex_layout("tex-classic", {}) == _layout("tex-classic")


def test_letter_page_size_switches_the_class_option() -> None:
    assert "letterpaper" in _layout(pageSize="LETTER")["documentclass"]


def test_one_margin_switches_geometry_to_explicit_millimetres() -> None:
    """The paper-proportional default cannot express one changed side, so the
    first explicit margin moves the whole option list to mm."""
    layout = _layout(marginLeft=20)

    assert layout["geometry"] == "top=14.85mm,bottom=14.85mm,left=20mm,right=10.5mm"
    assert "scale=" not in layout["geometry"]


def test_absent_sides_fall_back_to_the_template_baseline() -> None:
    assert _layout("tex-compact", marginTop=5)["geometry"] == (
        "top=5mm,bottom=12mm,left=12mm,right=12mm"
    )


@pytest.mark.parametrize(
    "level,expected",
    [
        (1, "\\documentclass[a4paper,8pt]{extarticle}"),
        (2, "\\documentclass[a4paper,9pt]{extarticle}"),
        (3, "\\documentclass[a4paper,10pt]{article}"),
        (4, "\\documentclass[a4paper,11pt]{article}"),
        (5, "\\documentclass[a4paper,12pt]{article}"),
    ],
)
def test_base_font_size_picks_a_class_that_offers_that_size(
    level: int, expected: str
) -> None:
    """``article`` has no 8pt or 9pt option; asking for one silently gives
    10pt, so the sub-10pt levels must switch to ``extarticle``."""
    assert _layout(fontSize=level)["documentclass"] == expected


def _pt(value: str) -> float:
    return float(value.removesuffix("pt"))


@pytest.mark.parametrize(
    "knob,key",
    [
        ("sectionSpacing", "section_before"),
        ("itemSpacing", "item_sep"),
        ("itemSpacing", "entry_gap"),
        ("bulletLeadIn", "item_lead"),
    ],
)
def test_a_spacing_level_moves_its_length_monotonically(knob: str, key: str) -> None:
    values = [_pt(_layout(**{knob: level})[key]) for level in _SPACING_LEVELS]

    assert values == sorted(values)
    assert values[0] < values[-1]


def test_line_height_levels_are_monotonic() -> None:
    values = [float(_layout(lineHeight=level)["linespread"]) for level in _SPACING_LEVELS]

    assert values == sorted(values)
    assert values[0] < values[-1]


def test_the_heading_gap_grows_with_the_level_and_never_opens_a_hole() -> None:
    """What the reader sees is ``section_before`` + the trailer, so that sum is
    the thing the axis must move. The trailer alone is not monotonic by design:
    where the collision floor binds it gives back exactly what the growing
    before-gap takes, holding the gap at the tightest safe value instead of
    printing the heading through the line above."""
    gaps = [
        _pt(_layout(sectionSpacing=level)["section_before"])
        + _pt(_layout(sectionSpacing=level)["section_end"])
        for level in _SPACING_LEVELS
    ]

    # Both lengths are emitted rounded to 0.01pt, so a plateau can read 0.01pt
    # out of order; nothing about that is a level moving the wrong way.
    assert all(later >= earlier - 0.02 for earlier, later in zip(gaps, gaps[1:]))
    assert gaps[0] < gaps[-1]
    # The trailer still pulls the heading up at every level; a positive value
    # would open a heading-sized hole instead of a tuned gap.
    assert all(_pt(_layout(sectionSpacing=level)["section_end"]) < 0 for level in _SPACING_LEVELS)


def test_compact_mode_tightens_spacing_and_leading() -> None:
    normal = _layout()
    compact = _layout(compactMode=True)

    assert _pt(compact["section_before"]) < _pt(normal["section_before"])
    assert _pt(compact["item_sep"]) < _pt(normal["item_sep"])
    assert _pt(compact["item_lead"]) < _pt(normal["item_lead"])
    assert float(compact["linespread"]) < float(normal["linespread"])
    # The heading gap, not the trailer: compact mode scales the section axis to
    # 0.6, which is tight enough for the collision floor to give some of the
    # pull back, so the trailer alone can read *less* negative than normal.
    assert _pt(compact["section_before"]) + _pt(compact["section_end"]) < _pt(
        normal["section_before"]
    ) + _pt(normal["section_end"])


@pytest.mark.parametrize(
    "knob,neutral,moves,exempt",
    [
        ("sectionSpacing", 5, _SECTION_KEYS, ()),
        ("itemSpacing", 4, _ITEM_KEYS, ()),
        ("bulletLeadIn", 4, _LEAD_KEYS, ()),
        # Tight leading needs a shorter pull to keep the heading off the line
        # above it, so the collision floor couples `lineHeight` to the trailer.
        # That is the one intended coupling between the four axes; the
        # before-gap and everything else still stay put.
        ("lineHeight", 5, ("linespread",), ("section_end",)),
    ],
)
def test_each_spacing_axis_moves_only_its_own_keys(
    knob: str, neutral: int, moves: tuple[str, ...], exempt: tuple[str, ...]
) -> None:
    """The acceptance test for "adjust section, item and line spacing
    separately": every other output key must be byte-identical across the
    whole range of the knob under test."""
    baseline = _layout()
    untouched = [
        key
        for key in (*_SECTION_KEYS, *_ITEM_KEYS, *_LEAD_KEYS, "linespread", *_SIZE_KEYS)
        if key not in moves and key not in exempt
    ]

    for level in (level for level in _SPACING_LEVELS if level != neutral):
        layout = _layout(**{knob: level})
        assert {key: layout[key] for key in untouched} == {
            key: baseline[key] for key in untouched
        }
        assert any(layout[key] != baseline[key] for key in moves)


def test_only_sub_single_leading_borrows_from_the_section_trailer() -> None:
    """The collision floor is allowed to couple ``lineHeight`` to the trailer,
    but only where it has to: the two levels whose leading is tighter than the
    type. Everywhere else the trailer is the tuned baseline, so a leading
    change must not quietly reflow the section rhythm."""
    tuned = _pt(_layout()["section_end"])

    for level in (1, 2):
        assert _pt(_layout(lineHeight=level)["section_end"]) > tuned
    for level in (3, 4, 5, 6, 7, 8, 9):
        assert _pt(_layout(lineHeight=level)["section_end"]) == tuned


@pytest.mark.parametrize("knob", ["fontSize", "headerScale"])
def test_type_size_levels_leave_the_spacing_lengths_alone(knob: str) -> None:
    baseline = _layout()
    spacing_keys = (*_SECTION_KEYS, *_ITEM_KEYS, *_LEAD_KEYS, "linespread")

    for level in (level for level in _FONT_LEVELS if level != 3):
        layout = _layout(**{knob: level})
        assert {key: layout[key] for key in spacing_keys} == {
            key: baseline[key] for key in spacing_keys
        }


@pytest.mark.parametrize(
    "level,name_size,section_size",
    [
        (1, "\\large", "\\small"),
        (3, "\\LARGE", "\\large"),
        (5, "\\Huge", "\\LARGE"),
    ],
)
def test_header_scale_steps_along_the_size_ladder(
    level: int, name_size: str, section_size: str
) -> None:
    layout = _layout(headerScale=level)

    assert layout["name_size"] == name_size
    assert layout["section_size"] == section_size


def test_every_template_has_a_baseline() -> None:
    """A template added without one would KeyError at render time."""
    assert LATEX_BASELINES.keys() == LATEX_TEMPLATES.keys()
