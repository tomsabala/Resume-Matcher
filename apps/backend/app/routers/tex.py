"""LaTeX source and PDF endpoints.

Two products from one document: a generated ``.tex`` the user can download or
hand-edit, and a compiled PDF. Compilation is optional — when no engine is
installed every route still works except ``/tex/pdf``, which answers 503 with
a message the UI turns into a ``.tex`` download.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Response

from app.database import DatabaseBusyError, db
from app.latex.compile import (
    LatexCompileError,
    LatexUnavailableError,
    compile_tex_to_pdf,
    latex_engine,
)
from app.latex.render import LATEX_TEMPLATES, UnknownLatexTemplateError, render_document_tex
from app.schemas.document import migrate_document
from app.schemas.tex import TexCapabilities, TexSourceResponse, TexSourceUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/resumes", tags=["LaTeX"])


def _engine_name() -> str | None:
    """The engine's bare name, not its path — the path is host detail."""
    engine = latex_engine()
    return Path(engine).name if engine else None


def _filename(resume: dict[str, object], extension: str) -> str:
    """A safe download filename derived from the resume title."""
    raw = str(resume.get("title") or "resume")
    safe = "".join(char if char.isalnum() or char in "-_ " else "" for char in raw).strip()
    return f"{(safe or 'resume').replace(' ', '_')}.{extension}"


async def _load(resume_id: str) -> dict[str, object]:
    resume = await db.get_resume(resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    return resume


def _generate(resume: dict[str, object], template: str, page_size: str) -> str:
    document = migrate_document(resume.get("processed_data"))
    try:
        return render_document_tex(
            document, template, settings={"pageSize": page_size}
        )
    except UnknownLatexTemplateError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown LaTeX template. Choose one of: {', '.join(sorted(LATEX_TEMPLATES))}",
        ) from None


def _source_for(
    resume: dict[str, object], template: str, page_size: str
) -> tuple[str, bool]:
    """The source to serve, and whether it is the user's override."""
    override = resume.get("tex_source")
    if isinstance(override, str) and override.strip():
        return override, True
    return _generate(resume, template, page_size), False


# The picker's page size is the only formatting control the LaTeX templates
# read; every other knob is HTML-only and disabled for a tex selection.
_PAGE_SIZE = Query("A4", pattern="^(A4|LETTER)$")


@router.get("/tex/capabilities", response_model=TexCapabilities)
async def get_tex_capabilities() -> TexCapabilities:
    """Whether this deployment can compile LaTeX, and with what."""
    engine = _engine_name()
    return TexCapabilities(
        engine=engine,
        can_compile=engine is not None,
        templates=sorted(LATEX_TEMPLATES),
    )


@router.get("/{resume_id}/tex", response_model=TexSourceResponse)
async def get_resume_tex(
    resume_id: str,
    template: str = Query("tex-classic"),
    pageSize: str = _PAGE_SIZE,  # noqa: N803 - query name matches the client
    regenerate: bool = Query(
        False,
        description="Ignore a saved override and render from the document.",
    ),
) -> TexSourceResponse:
    """The resume's LaTeX source: the user's override, or freshly generated."""
    resume = await _load(resume_id)
    if regenerate:
        source, is_override = _generate(resume, template, pageSize), False
    else:
        source, is_override = _source_for(resume, template, pageSize)
    return TexSourceResponse(
        resume_id=resume_id,
        source=source,
        is_override=is_override,
        template=template,
        engine=_engine_name(),
    )


@router.put("/{resume_id}/tex", response_model=TexSourceResponse)
async def put_resume_tex(
    resume_id: str, request: TexSourceUpdate
) -> TexSourceResponse:
    """Save hand-edited LaTeX.

    From here the document no longer drives this resume's ``.tex``; the
    override is served verbatim until it is deleted.

    The save lands on the version timeline as a ``tex_edit`` checkpoint. The
    document is unchanged, so without recording the source the history would
    show nothing happened and the edit could not be restored.
    """
    resume = await _load(resume_id)
    document = migrate_document(resume.get("processed_data"))
    try:
        await db.commit_resume_version(
            resume_id,
            document.model_dump(mode="json"),
            origin="tex_edit",
            tex_source=request.source,
            tex_source_mode="edited",
            resume_updates={"tex_source": request.source},
        )
    except DatabaseBusyError:
        raise
    except Exception as error:
        logger.error(f"Failed to save LaTeX source for {resume_id}: {error}")
        raise HTTPException(
            status_code=500, detail="Failed to save LaTeX source. Please try again."
        ) from error
    return TexSourceResponse(
        resume_id=resume_id,
        source=request.source,
        is_override=True,
        template="custom",
        engine=_engine_name(),
    )


@router.delete("/{resume_id}/tex", response_model=TexSourceResponse)
async def delete_resume_tex(
    resume_id: str,
    template: str = Query("tex-classic"),
    pageSize: str = _PAGE_SIZE,  # noqa: N803 - query name matches the client
) -> TexSourceResponse:
    """Drop the override and go back to generating from the document."""
    resume = await _load(resume_id)
    try:
        await db.commit_resume_version(
            resume_id,
            migrate_document(resume.get("processed_data")).model_dump(mode="json"),
            origin="tex_edit",
            tex_source=None,
            tex_source_mode="generated",
            resume_updates={"tex_source": None},
        )
    except DatabaseBusyError:
        raise
    except Exception as error:
        logger.error(f"Failed to clear LaTeX source for {resume_id}: {error}")
        raise HTTPException(
            status_code=500, detail="Failed to clear LaTeX source. Please try again."
        ) from error
    return TexSourceResponse(
        resume_id=resume_id,
        source=_generate(resume, template, pageSize),
        is_override=False,
        template=template,
        engine=_engine_name(),
    )


@router.get("/{resume_id}/tex/source")
async def download_resume_tex(
    resume_id: str,
    template: str = Query("tex-classic"),
    pageSize: str = _PAGE_SIZE,  # noqa: N803 - query name matches the client
) -> Response:
    """The ``.tex`` as a file download — the fallback when no engine exists."""
    resume = await _load(resume_id)
    source, _ = _source_for(resume, template, pageSize)
    return Response(
        content=source.encode("utf-8"),
        media_type="application/x-tex",
        headers={
            "Content-Disposition": f'attachment; filename="{_filename(resume, "tex")}"'
        },
    )


@router.get("/{resume_id}/tex/pdf")
async def download_resume_tex_pdf(
    resume_id: str,
    template: str = Query("tex-classic"),
    pageSize: str = _PAGE_SIZE,  # noqa: N803 - query name matches the client
) -> Response:
    """Compile the resume's LaTeX and return the PDF."""
    resume = await _load(resume_id)
    source, _ = _source_for(resume, template, pageSize)
    try:
        pdf_bytes = await compile_tex_to_pdf(source)
    except LatexUnavailableError as error:
        # 503, not 500: the request is fine, the capability is missing. The
        # UI reads this as "offer the .tex download".
        raise HTTPException(status_code=503, detail=str(error)) from error
    except LatexCompileError as error:
        logger.error(f"LaTeX compile failed for {resume_id}")
        # The log is the user's own source failing; it is theirs to see.
        raise HTTPException(
            status_code=422,
            detail={"message": str(error), "log": error.log},
        ) from error
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{_filename(resume, "pdf")}"'
        },
    )
