"""Compile LaTeX source to PDF.

The engine is whatever the host provides — Tectonic if present (it fetches
its own packages, so a container needs no TeX Live), otherwise latexmk, then
a bare pdflatex/xelatex run. All of them are optional: when none is
installed the caller gets :class:`LatexUnavailableError` and the UI offers a
``.tex`` download instead, which is why every code path keeps the source.

Every run is sandboxed to a fresh temp directory with shell-escape disabled
and file I/O restricted to that directory, so even a template bug cannot read
or write outside it.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = [
    "LatexCompileError",
    "LatexUnavailableError",
    "compile_tex_to_pdf",
    "latex_engine",
]

# Runaway TeX (a bad \loop, an unclosed environment) burns CPU forever;
# every engine invocation is bounded.
_TIMEOUT_SECONDS = 120

# How much engine log to surface on failure. A raw tail buries the one line
# that matters under package chatter, so `_error_excerpt` finds the error
# first and only falls back to the tail.
_LOG_TAIL_CHARS = 4000
_ERROR_CONTEXT_LINES = 40


def _error_excerpt(log: str) -> str:
    """The part of a TeX log a human needs.

    TeX marks real errors with a line starting ``!`` and prints the offending
    source line under it, then pads the end of the log with memory statistics.
    Returning from the first ``!`` puts the diagnosis at the top of whatever
    the UI renders.
    """
    lines = log.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("!"):
            return "\n".join(lines[index : index + _ERROR_CONTEXT_LINES])[
                :_LOG_TAIL_CHARS
            ]
    return log[-_LOG_TAIL_CHARS:]


class LatexUnavailableError(RuntimeError):
    """No LaTeX engine is installed on this host."""


@dataclass(frozen=True)
class LatexCompileError(RuntimeError):
    """The engine ran and rejected the document."""

    message: str
    log: str

    def __str__(self) -> str:
        return self.message


def _argv(engine: str, source_name: str) -> list[str]:
    if engine.endswith("tectonic"):
        # Tectonic is single-pass-by-default and resolves references itself.
        return [engine, "--keep-logs", "--outdir", ".", source_name]
    if engine.endswith("latexmk"):
        return [
            engine,
            "-pdf",
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-no-shell-escape",
            source_name,
        ]
    return [engine, "-interaction=nonstopmode", "-halt-on-error", "-no-shell-escape", source_name]


def latex_engine() -> str | None:
    """Absolute path of the preferred available engine, or ``None``.

    ``RESUME_MATCHER_LATEX_ENGINE`` overrides the search, so an operator can
    pin an engine without changing the image.
    """
    override = os.environ.get("RESUME_MATCHER_LATEX_ENGINE", "").strip()
    if override:
        return shutil.which(override) or (override if Path(override).is_file() else None)
    for candidate in ("tectonic", "latexmk", "xelatex", "pdflatex"):
        found = shutil.which(candidate)
        if found:
            return found
    return None


def _passes(engine: str) -> int:
    """How many times to run the engine.

    Tectonic and latexmk loop internally. A bare engine needs a second pass
    so ``tabularx`` column widths and page references settle.
    """
    return 1 if engine.endswith(("tectonic", "latexmk")) else 2


async def compile_tex_to_pdf(source: str) -> bytes:
    """Compile LaTeX ``source`` and return the PDF bytes.

    Raises :class:`LatexUnavailableError` when no engine is installed and
    :class:`LatexCompileError` when the engine rejects the document.
    """
    engine = latex_engine()
    if engine is None:
        raise LatexUnavailableError(
            "No LaTeX engine found. Install tectonic or a TeX distribution, "
            "or download the .tex source instead."
        )

    with tempfile.TemporaryDirectory(prefix="rm-latex-") as workdir:
        directory = Path(workdir)
        tex_path = directory / "resume.tex"
        tex_path.write_text(source, encoding="utf-8")

        env = {
            **os.environ,
            # Confine file I/O to the working directory even if a template
            # somehow emits an \input or \openout. This, `-no-shell-escape`
            # and the temp cwd are the sandbox; HOME and the engine caches
            # are deliberately *not* redirected here - Tectonic keeps its
            # downloaded TeX bundle (hundreds of MB) under the user cache,
            # and a per-run HOME would re-fetch it on every single compile.
            "openin_any": "p",
            "openout_any": "p",
            "SOURCE_DATE_EPOCH": "0",  # reproducible PDFs
        }

        output = ""
        for _ in range(_passes(engine)):
            process = await asyncio.create_subprocess_exec(
                *_argv(engine, tex_path.name),
                cwd=directory,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
            )
            try:
                stdout, _ = await asyncio.wait_for(
                    process.communicate(), timeout=_TIMEOUT_SECONDS
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                raise LatexCompileError(
                    message=f"LaTeX compilation timed out after {_TIMEOUT_SECONDS}s.",
                    log="",
                ) from None
            output = stdout.decode("utf-8", errors="replace")
            if process.returncode != 0:
                break

        pdf_path = directory / "resume.pdf"
        if not pdf_path.exists() or pdf_path.stat().st_size == 0:
            log_path = directory / "resume.log"
            log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else output
            logger.error("LaTeX compilation produced no PDF (engine=%s)", engine)
            raise LatexCompileError(
                message="LaTeX compilation failed.",
                log=_error_excerpt(log),
            )
        return pdf_path.read_bytes()
