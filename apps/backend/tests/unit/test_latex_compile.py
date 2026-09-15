"""LaTeX compilation: engine selection and failure behaviour.

The real compile is covered by a gated end-to-end test — most hosts and CI
have no TeX. What is always testable is how we choose an engine and what the
caller sees when one is missing or the source is broken.
"""

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
from app.latex.render import render_document_tex
from app.schemas.document import ResumeDocument

pytestmark = pytest.mark.unit

_MINIMAL = "\\documentclass{article}\\begin{document}Hello.\\end{document}"


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
