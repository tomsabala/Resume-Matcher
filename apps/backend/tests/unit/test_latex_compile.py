"""LaTeX compilation: engine selection and failure behaviour.

The real compile is covered by a gated end-to-end test — most hosts and CI
have no TeX. What is always testable is how we choose an engine and what the
caller sees when one is missing or the source is broken.
"""

import io
import shutil
from collections import Counter
from typing import Any

import pytest

from app.latex import compile as latex_compile
from app.latex.compile import (
    LatexCompileError,
    LatexUnavailableError,
    compile_tex_to_pdf,
    latex_engine,
)
from app.latex.render import LATEX_TEMPLATES, render_document_tex
from app.schemas.document import ResumeDocument

pytestmark = pytest.mark.unit

_MINIMAL = "\\documentclass{article}\\begin{document}Hello.\\end{document}"


def _page_text(pdf: bytes) -> str:
    """First page text, whitespace-normalised.

    Line wrapping is a layout decision, so the probe compares words.
    """
    from pypdf import PdfReader

    return " ".join(PdfReader(io.BytesIO(pdf)).pages[0].extract_text().split())


def _baselines(pdf: bytes) -> list[tuple[float, str, float]]:
    """``(baseline y, text, font size)`` for every text chunk on page 1.

    pypdf hands the text matrix to the visitor, so this reads the typeset
    geometry rather than trusting the source.
    """
    from pypdf import PdfReader

    chunks: list[tuple[float, str, float]] = []

    def visit(text: str, cm: Any, tm: Any, font: Any, size: Any) -> None:
        if text.strip():
            chunks.append((round(tm[5], 1), text.strip(), float(size)))

    PdfReader(io.BytesIO(pdf)).pages[0].extract_text(visitor_text=visit)
    return chunks


def _baseline_gap_before(pdf: bytes, heading: str) -> float:
    """Points between the last baseline above ``heading`` and the heading's."""
    chunks = _baselines(pdf)
    heading_y = max(y for y, text, _ in chunks if heading.lower() in text.lower())
    above = sorted(y for y, _, _ in chunks if y > heading_y)
    return above[0] - heading_y


def _baseline_of(pdf: bytes, needle: str) -> float:
    """The baseline of the chunk containing ``needle``."""
    return max(y for y, text, _ in _baselines(pdf) if needle in text)


def _body_font_size(pdf: bytes) -> float:
    """The most common font size on the page, i.e. the body size."""
    return Counter(round(size, 1) for _, _, size in _baselines(pdf)).most_common(1)[0][0]


def _leading_below(pdf: bytes, heading: str) -> float:
    """Baseline-to-baseline distance inside the paragraph under ``heading``.

    The fixture's wrapped paragraph is the page's last block, so every
    baseline below the heading belongs to it.
    """
    heading_y = max(y for y, text, _ in _baselines(pdf) if heading.lower() in text.lower())
    lines = sorted({y for y, _, _ in _baselines(pdf) if y < heading_y}, reverse=True)
    assert len(lines) >= 3, "fixture paragraph must wrap"
    return lines[0] - lines[1]


def test_tectonic_is_preferred_over_a_local_tex_distribution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tectonic fetches its own packages, so an image that has it needs no
    TeX Live; picking latexmk first would make the image choice moot."""
    monkeypatch.delenv("RESUME_MATCHER_LATEX_ENGINE", raising=False)
    monkeypatch.setattr(
        latex_compile.shutil,
        "which",
        lambda name: f"/usr/bin/{name}" if name in {"tectonic", "latexmk"} else None,
    )

    assert latex_engine() == "/usr/bin/tectonic"


def test_the_engine_environment_override_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESUME_MATCHER_LATEX_ENGINE", "xelatex")
    monkeypatch.setattr(latex_compile.shutil, "which", lambda name: f"/opt/{name}")

    assert latex_engine() == "/opt/xelatex"


async def test_no_engine_raises_the_unavailable_error_not_a_generic_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The router turns exactly this type into a 503 + .tex fallback."""
    monkeypatch.delenv("RESUME_MATCHER_LATEX_ENGINE", raising=False)
    monkeypatch.setattr(latex_compile.shutil, "which", lambda _name: None)

    with pytest.raises(LatexUnavailableError):
        await compile_tex_to_pdf(_MINIMAL)


def test_a_bare_engine_runs_twice_but_a_driver_runs_once() -> None:
    """pdflatex needs a second pass for tabularx widths to settle; latexmk
    and tectonic already loop internally and a second run wastes seconds."""
    assert latex_compile._passes("/usr/bin/pdflatex") == 2
    assert latex_compile._passes("/usr/bin/latexmk") == 1
    assert latex_compile._passes("/usr/bin/tectonic") == 1


def test_shell_escape_is_disabled_on_every_tex_invocation() -> None:
    for engine in ("/usr/bin/latexmk", "/usr/bin/pdflatex", "/usr/bin/xelatex"):
        assert "-no-shell-escape" in latex_compile._argv(engine, "resume.tex")


@pytest.mark.skipif(latex_engine() is None, reason="no LaTeX engine installed")
async def test_the_generated_source_actually_compiles(
    sample_resume: dict[str, Any],
) -> None:
    """The one test that proves the templates are valid LaTeX rather than
    plausible-looking text."""
    document = ResumeDocument.model_validate(sample_resume)

    pdf = await compile_tex_to_pdf(render_document_tex(document))

    assert pdf.startswith(b"%PDF-")
    assert len(pdf) > 1000


@pytest.mark.skipif(latex_engine() is None, reason="no LaTeX engine installed")
async def test_a_broken_document_fails_with_the_engine_log() -> None:
    with pytest.raises(LatexCompileError) as caught:
        await compile_tex_to_pdf(
            "\\documentclass{article}\\begin{document}\\undefinedmacro\\end{document}"
        )

    assert "undefinedmacro" in caught.value.log.lower()


def test_the_error_excerpt_leads_with_the_tex_error_not_package_chatter() -> None:
    """A raw tail buries the one line that explains the failure."""
    log = (
        "Package hyperref Info: Option 'colorlinks' set 'true' on input line 26.\n" * 200
        + "! Undefined control sequence.\n"
        + "l.50 \\begin{document}\\thisMacroDoesNotExist\n"
        + "Here is how much of TeX's memory you used:\n"
        + " 13550 strings out of 478287\n" * 40
    )

    excerpt = latex_compile._error_excerpt(log)

    assert excerpt.startswith("! Undefined control sequence.")
    assert "thisMacroDoesNotExist" in excerpt


def test_a_log_with_no_marked_error_falls_back_to_the_tail() -> None:
    log = "x" * 9000

    excerpt = latex_compile._error_excerpt(log)

    assert len(excerpt) == latex_compile._LOG_TAIL_CHARS


def _hostile_document() -> ResumeDocument:
    """A document carrying every input class that used to break the engine or
    the page: bullet markup, OT1-mangled ASCII, and unmappable unicode."""
    return ResumeDocument.model_validate(
        {
            "schemaVersion": 2,
            "header": {"name": "Ada & Co", "headline": "Engineer"},
            "sections": [
                {
                    "id": "s-1",
                    "key": "experience",
                    "heading": "Experience",
                    "kind": "entries",
                    "visible": True,
                    "column": "main",
                    "entries": [
                        {
                            "id": "e-1",
                            "title": "Acme",
                            "period": "2020 - 2024",
                            "bullets": [
                                {
                                    "text": (
                                        "<p>Kept <strong>1.5s latency</strong> and "
                                        "<em>p99 &lt; 200ms</em> via "
                                        '<a href="https://x.dev">link</a></p>'
                                    )
                                },
                                {"text": "latency < 200ms & 50% of cases"},
                                {"text": "≥ ✓ « π ≠ ∞ ★ | Java"},
                            ],
                        }
                    ],
                }
            ],
        }
    )


@pytest.mark.skipif(latex_engine() is None, reason="no LaTeX engine installed")
@pytest.mark.parametrize("template_id", sorted(LATEX_TEMPLATES))
async def test_rich_bullets_and_hostile_characters_compile(template_id: str) -> None:
    """Each of these aborted the compile or printed garbage before the
    escaping rework: ``<`` became ``¡``, ``|`` became an em dash, and ``≥``
    failed with "Unicode character not set up for use with LaTeX"."""
    source = render_document_tex(_hostile_document(), template_id)

    pdf = await compile_tex_to_pdf(source)

    assert pdf.startswith(b"%PDF-")
    text = _page_text(pdf)
    assert "Kept 1.5s latency and p99 < 200ms via link" in text
    assert "latency < 200ms & 50% of cases" in text
    assert "<strong>" not in text
    assert "Java" in text and "—" not in text


@pytest.mark.skipif(latex_engine() is None, reason="no LaTeX engine installed")
@pytest.mark.parametrize(
    "template_id,low,high",
    [("tex-classic", 12.0, 17.0), ("tex-compact", 9.0, 14.0)],
)
async def test_a_section_does_not_leave_a_heading_sized_hole_behind_it(
    template_id: str, low: float, high: float
) -> None:
    """The trailing ``\\vspace`` after an entries section is what decides
    whether a resume fits one page. At the old uniform ``-6pt`` this gap
    measures 19.6pt (classic) / 15.5pt (compact); the reference CV's own
    section gaps are 13.8-15.4pt. Content-independent: it measures the
    document's own geometry, not a page count.
    """
    document = ResumeDocument.model_validate(
        {
            "schemaVersion": 2,
            "header": {"name": "Ada Lovelace"},
            "sections": [
                {
                    "id": "s-1",
                    "key": "experience",
                    "heading": "Experience",
                    "kind": "entries",
                    "visible": True,
                    "column": "main",
                    "entries": [
                        {
                            "id": "e-1",
                            "title": "Acme",
                            "period": "2020 - 2024",
                            "bullets": [
                                {"text": "Shipped the platform end to end."},
                                {"text": "Owned latency budgets across services."},
                            ],
                        }
                    ],
                },
                {
                    "id": "s-2",
                    "key": "summary",
                    "heading": "Summary",
                    "kind": "text",
                    "visible": True,
                    "column": "main",
                    "text": "A short paragraph.",
                },
            ],
        }
    )

    pdf = await compile_tex_to_pdf(render_document_tex(document, template_id))

    assert low <= _baseline_gap_before(pdf, "Summary") <= high


def _rhythm_document() -> ResumeDocument:
    """Two entries, two bullets each, and a wrapped closing paragraph.

    One fixture carrying all three spacing axes: heading gaps, bullet gaps and
    the leading inside a paragraph. The paragraph is last, so every baseline
    below its heading belongs to it.
    """
    return ResumeDocument.model_validate(
        {
            "schemaVersion": 2,
            "header": {"name": "Ada Lovelace", "headline": "Engineer"},
            "sections": [
                {
                    "id": "s-1",
                    "key": "experience",
                    "heading": "Experience",
                    "kind": "entries",
                    "visible": True,
                    "column": "main",
                    "entries": [
                        {
                            "id": "e-1",
                            "title": "Acme",
                            "period": "2020 - 2024",
                            "bullets": [
                                {"text": "Shipped the platform."},
                                {"text": "Owned latency budgets."},
                            ],
                        },
                        {
                            "id": "e-2",
                            "title": "Initech",
                            "period": "2016 - 2020",
                            "bullets": [
                                {"text": "Rebuilt the ingest pipeline."},
                                {"text": "Halved the deploy time."},
                            ],
                        },
                    ],
                },
                {
                    "id": "s-2",
                    "key": "summary",
                    "heading": "Summary",
                    "kind": "text",
                    "visible": True,
                    "column": "main",
                    "text": (
                        "Engineer with a long history of shipping systems that other "
                        "people depend on, from storage layers and ingest pipelines to "
                        "the deployment machinery around them, written here at enough "
                        "length that the paragraph wraps onto several lines no matter "
                        "which of the two templates renders it."
                    ),
                },
            ],
        }
    )


_TIGHT: dict[str, object] = {
    "sectionSpacing": 1,
    "itemSpacing": 1,
    "lineHeight": 1,
    "fontSize": 1,
    "headerScale": 1,
    "marginTop": 5,
    "marginBottom": 5,
    "marginLeft": 5,
    "marginRight": 5,
}

_LOOSE: dict[str, object] = {
    "sectionSpacing": 5,
    "itemSpacing": 5,
    "lineHeight": 5,
    "fontSize": 5,
    "headerScale": 5,
    "marginTop": 25,
    "marginBottom": 25,
    "marginLeft": 25,
    "marginRight": 25,
}


@pytest.mark.skipif(latex_engine() is None, reason="no LaTeX engine installed")
@pytest.mark.parametrize("template_id", sorted(LATEX_TEMPLATES))
@pytest.mark.parametrize("settings", [_TIGHT, _LOOSE], ids=["tight", "loose"])
async def test_the_formatting_extremes_compile(
    template_id: str, settings: dict[str, object]
) -> None:
    """Both ends of every control at once. The tight end is the only path
    through ``extarticle`` at 8pt, which a stock ``article`` cannot do."""
    pdf = await compile_tex_to_pdf(
        render_document_tex(_rhythm_document(), template_id, settings=settings)
    )

    assert pdf.startswith(b"%PDF-")


@pytest.mark.skipif(latex_engine() is None, reason="no LaTeX engine installed")
async def test_a_top_margin_change_moves_the_first_baseline() -> None:
    """20mm of margin is 56.7pt of paper; anything less means ``geometry``
    took the value but the body did not."""
    document = _rhythm_document()
    tight = await compile_tex_to_pdf(
        render_document_tex(document, "tex-classic", settings={"marginTop": 5})
    )
    wide = await compile_tex_to_pdf(
        render_document_tex(document, "tex-classic", settings={"marginTop": 25})
    )

    shift = _baseline_of(tight, "Ada Lovelace") - _baseline_of(wide, "Ada Lovelace")

    assert 53.7 <= shift <= 59.7


@pytest.mark.skipif(latex_engine() is None, reason="no LaTeX engine installed")
async def test_the_base_font_size_reaches_the_typeset_page() -> None:
    document = _rhythm_document()
    small = await compile_tex_to_pdf(
        render_document_tex(document, "tex-classic", settings={"fontSize": 1})
    )
    large = await compile_tex_to_pdf(
        render_document_tex(document, "tex-classic", settings={"fontSize": 5})
    )

    assert 7.5 <= _body_font_size(small) <= 8.5
    assert 11.5 <= _body_font_size(large) <= 12.5


@pytest.mark.skipif(latex_engine() is None, reason="no LaTeX engine installed")
async def test_section_spacing_moves_the_heading_gap_and_leaves_bullets_alone() -> None:
    """The panel adjusts the three spacing axes separately, so this one must
    change heading gaps without touching bullet rhythm."""
    document = _rhythm_document()
    pdfs = {
        level: await compile_tex_to_pdf(
            render_document_tex(document, "tex-classic", settings={"sectionSpacing": level})
        )
        for level in (1, 3, 5)
    }

    gaps = [_baseline_gap_before(pdfs[level], "Summary") for level in (1, 3, 5)]
    bullet_gaps = [
        _baseline_of(pdfs[level], "Shipped") - _baseline_of(pdfs[level], "Owned")
        for level in (1, 3, 5)
    ]

    assert gaps[0] < gaps[1] < gaps[2]
    # The default level must still land in the tuned window the reference CV
    # sets, the one `test_a_section_does_not_leave_a_heading_sized_hole` pins.
    assert 12.0 <= gaps[1] <= 17.0
    assert max(bullet_gaps) - min(bullet_gaps) < 1.0


@pytest.mark.skipif(latex_engine() is None, reason="no LaTeX engine installed")
async def test_item_spacing_moves_the_bullet_gap_and_leaves_headings_alone() -> None:
    document = _rhythm_document()
    tight = await compile_tex_to_pdf(
        render_document_tex(document, "tex-classic", settings={"itemSpacing": 1})
    )
    loose = await compile_tex_to_pdf(
        render_document_tex(document, "tex-classic", settings={"itemSpacing": 5})
    )

    def bullet_gap(pdf: bytes) -> float:
        return _baseline_of(pdf, "Shipped") - _baseline_of(pdf, "Owned")

    assert bullet_gap(tight) < bullet_gap(loose)
    assert (
        abs(
            _baseline_gap_before(tight, "Summary") - _baseline_gap_before(loose, "Summary")
        )
        < 1.5
    )


@pytest.mark.skipif(latex_engine() is None, reason="no LaTeX engine installed")
async def test_line_spacing_moves_the_leading_and_leaves_the_gaps_alone() -> None:
    """``\\linespread`` is leading inside a paragraph. ``parskip`` fixes
    ``\\parskip`` from the class size, so it cannot leak into the spacing
    macros — the rendered lengths stay byte-identical."""
    document = _rhythm_document()
    sources = {
        level: render_document_tex(document, "tex-classic", settings={"lineHeight": level})
        for level in (1, 5)
    }
    tight = await compile_tex_to_pdf(sources[1])
    loose = await compile_tex_to_pdf(sources[5])

    assert _leading_below(tight, "Summary") < _leading_below(loose, "Summary")
    for source in sources.values():
        assert "\\newcommand{\\resumeItemSep}{2pt}" in source
        assert "\\newcommand{\\resumeSectionEnd}{\\vspace{-11pt}}" in source
