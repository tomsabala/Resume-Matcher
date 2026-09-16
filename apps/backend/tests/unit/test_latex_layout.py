"""Formatting levels → LaTeX preamble values.

The panel's controls and the engine's lengths are different vocabularies, and
the translation is where "adjust section spacing" can quietly become "adjust
everything". These tests pin the reference look at default levels and the
independence of the three spacing axes.
"""

import pytest

from app.latex.layout import LATEX_BASELINES, tex_layout
from app.latex.render import LATEX_TEMPLATES

pytestmark = pytest.mark.unit

NEUTRAL: dict[str, object] = {
    "pageSize": "A4",
    "sectionSpacing": 3,
    "itemSpacing": 2,
    "lineHeight": 3,
    "fontSize": 3,
    "headerScale": 3,
    "compactMode": False,
}

_SECTION_KEYS = ("section_before", "section_after", "section_end", "block_end")
_ITEM_KEYS = ("entry_gap", "item_sep")
_SIZE_KEYS = ("documentclass", "name_size", "headline_size", "section_size")


def _layout(template_id: str = "tex-classic", **overrides: object) -> dict[str, str]:
    return tex_layout(template_id, {**NEUTRAL, **overrides})


@pytest.mark.parametrize(
    "template_id,geometry,section_end,section_size,item_sep",
    [
        ("tex-classic", "scale=0.9", "-11pt", "\\large", "2pt"),
        ("tex-compact", "margin=1.2cm", "-9pt", "\\normalsize", "1pt"),
    ],
)
def test_default_levels_reproduce_the_reference_cv(
    template_id: str,
    geometry: str,
    section_end: str,
    section_size: str,
    item_sep: str,
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
        ("sectionSpacing", "section_end"),
        ("itemSpacing", "item_sep"),
        ("itemSpacing", "entry_gap"),
    ],
)
def test_a_spacing_level_moves_its_length_monotonically(knob: str, key: str) -> None:
    values = [_pt(_layout(**{knob: level})[key]) for level in (1, 2, 3, 4, 5)]

    assert values == sorted(values)
    assert values[0] < values[-1]


def test_line_height_levels_are_monotonic() -> None:
    values = [float(_layout(lineHeight=level)["linespread"]) for level in (1, 2, 3, 4, 5)]

    assert values == sorted(values)
    assert values[0] < values[-1]


def test_the_heading_gap_stays_negative_and_ordered_across_levels() -> None:
    """``section_end`` pulls the next heading up; a positive value at high
    levels would open a heading-sized hole instead of a tuned gap."""
    values = [_pt(_layout(sectionSpacing=level)["section_end"]) for level in (1, 3, 5)]

    assert values == sorted(values)
    assert all(value < 0 for value in values)


def test_compact_mode_tightens_spacing_and_leading() -> None:
    normal = _layout()
    compact = _layout(compactMode=True)

    assert _pt(compact["section_before"]) < _pt(normal["section_before"])
    assert _pt(compact["item_sep"]) < _pt(normal["item_sep"])
    assert _pt(compact["section_end"]) < _pt(normal["section_end"])
    assert float(compact["linespread"]) < float(normal["linespread"])


@pytest.mark.parametrize(
    "knob,neutral,moves",
    [
        ("sectionSpacing", 3, _SECTION_KEYS),
        ("itemSpacing", 2, _ITEM_KEYS),
        ("lineHeight", 3, ("linespread",)),
    ],
)
def test_each_spacing_axis_moves_only_its_own_keys(
    knob: str, neutral: int, moves: tuple[str, ...]
) -> None:
    """The acceptance test for "adjust section, item and line spacing
    separately": every other output key must be byte-identical across the
    whole range of the knob under test."""
    baseline = _layout()
    untouched = [
        key
        for key in (*_SECTION_KEYS, *_ITEM_KEYS, "linespread", *_SIZE_KEYS)
        if key not in moves
    ]

    for level in (level for level in (1, 2, 3, 4, 5) if level != neutral):
        layout = _layout(**{knob: level})
        assert {key: layout[key] for key in untouched} == {
            key: baseline[key] for key in untouched
        }
        assert any(layout[key] != baseline[key] for key in moves)


@pytest.mark.parametrize("knob", ["fontSize", "headerScale"])
def test_type_size_levels_leave_the_spacing_lengths_alone(knob: str) -> None:
    baseline = _layout()
    spacing_keys = (*_SECTION_KEYS, *_ITEM_KEYS, "linespread")

    for level in (1, 2, 4, 5):
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
