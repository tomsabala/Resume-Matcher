"""Document comparison endpoint.

One surface for resume-vs-resume, version-vs-version and
resume-vs-AI-suggestion: each side is a ``Ref`` that resolves to a document,
and the engine does not care which kind produced it.
"""

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator

from app.database import db
from app.deps import WorkspaceId
from app.schemas.document import ResumeDocument, migrate_document
from app.schemas.diff import DiffRow, DocumentDiff
from app.latex.render import render_document_tex
from app.services.document_diff import diff_documents, diff_tex_sources

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/diff", tags=["Diff"])


class DiffRef(BaseModel):
    """One side of a comparison. Exactly one field must be set."""

    version_id: str | None = None
    resume_id: str | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> "DiffRef":
        if (self.version_id is None) == (self.resume_id is None):
            raise ValueError("Provide exactly one of version_id or resume_id")
        return self


class DiffRequest(BaseModel):
    """Compare two refs."""

    base: DiffRef
    head: DiffRef
    mode: Literal["document", "tex"] = "document"
    # Unchanged rows kept around each change; 0 returns changes only.
    context: int = Field(default=2, ge=0, le=20)


class TexDiffResponse(BaseModel):
    """Line diff over LaTeX source."""

    rows: list[DiffRow]


class ResolvedRef(BaseModel):
    """A ref's document plus the workspace it belongs to."""

    document: ResumeDocument
    workspace_id: str
    tex_source: str | None = None


async def _resolve(ref: DiffRef) -> ResolvedRef:
    """Load the document a ref names, or 404."""
    if ref.version_id is not None:
        version = await db.get_resume_version(ref.version_id)
        if version is None:
            raise HTTPException(
                status_code=404, detail=f"Version not found: {ref.version_id}"
            )
        return ResolvedRef(
            document=migrate_document(version["document"]),
            workspace_id=version["workspace_id"],
            tex_source=version.get("tex_source"),
        )

    resume = await db.get_resume(ref.resume_id or "")
    if resume is None:
        raise HTTPException(
            status_code=404, detail=f"Resume not found: {ref.resume_id}"
        )
    return ResolvedRef(
        document=migrate_document(resume.get("processed_data")),
        workspace_id=str(resume.get("workspace_id") or ""),
        tex_source=resume.get("tex_source"),
    )


def _tex_for(ref: ResolvedRef) -> str:
    """The LaTeX a ref stands for.

    A side with no saved override still has a source - the one its document
    generates. Comparing "" against real LaTeX would report the whole file as
    added, which is never what the user meant.
    """
    if ref.tex_source and ref.tex_source.strip():
        return ref.tex_source
    return render_document_tex(ref.document)


@router.post("", response_model=DocumentDiff | TexDiffResponse)
async def compare(
    request: DiffRequest, workspace_id: WorkspaceId
) -> DocumentDiff | TexDiffResponse:
    """Compare two documents, or their LaTeX sources.

    Both refs must live in the active workspace: a diff is a read of two
    documents at once, and workspaces are separate namespaces.
    """
    base = await _resolve(request.base)
    head = await _resolve(request.head)

    for side in (base, head):
        if side.workspace_id and side.workspace_id != workspace_id:
            raise HTTPException(
                status_code=403, detail="Cannot compare across workspaces"
            )

    if request.mode == "tex":
        return TexDiffResponse(
            rows=diff_tex_sources(
                _tex_for(base), _tex_for(head), context=request.context
            )
        )
    return diff_documents(base.document, head.document, context=request.context)
