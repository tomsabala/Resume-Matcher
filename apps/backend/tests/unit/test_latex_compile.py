"""LaTeX compilation: engine selection and failure behaviour.

The real compile is covered by a gated end-to-end test — most hosts and CI
have no TeX. What is always testable is how we choose an engine and what the
caller sees when one is missing or the source is broken.
"""

import io
import shutil
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


def _baseline_gap_before(pdf: bytes, heading: str) -> float:
    """Points between the last baseline above ``heading`` and the heading's.

    pypdf hands the text matrix to the visitor, so this reads the typeset
    geometry rather than trusting the source.
    """
    from pypdf import PdfReader

    baselines: list[tuple[float, str]] = []

    def visit(text: str, cm: Any, tm: Any, font: Any, size: Any) -> None:
        if text.strip():
            baselines.append((round(tm[5], 1), text.strip()))

    PdfReader(io.BytesIO(pdf)).pages[0].extract_text(visitor_text=visit)
    heading_y = max(y for y, text in baselines if heading.lower() in text.lower())
    above = sorted(y for y, _ in baselines if y > heading_y)
    return above[0] - heading_y


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
