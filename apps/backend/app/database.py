"""SQLAlchemy (SQLite) data layer for Resume Matcher.

This is a behavior-preserving replacement for the original TinyDB wrapper. The
``Database`` facade keeps the same method names/signatures and returns **plain
dicts** (never ORM rows), so the ~50 call sites only needed ``await`` added.

Two engines back one SQLite file:
- an **async** engine (``aiosqlite``) for the document tables and applications;
- a **sync** engine for the encrypted ``api_keys`` table, which is read on the
  synchronous LLM hot path (``get_llm_config`` → ``resolve_api_key``).
"""

import copy
import logging
import re
import shutil
import sqlite3
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from sqlalchemy import and_, delete, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.db_engine import init_models_sync, make_async_engine, make_sync_engine
from app.models import (
    ApiKey,
    Application,
    Improvement,
    Job,
    Resume,
    ResumeVersion,
    TailoringPreview,
    Workspace,
)
from app.preview import (
    PreviewBusyError,
    PreviewClaim,
    PreviewConflictError,
    PreviewValidationError,
    document_fingerprint,
    job_fingerprint,
    resume_fingerprint,
)

logger = logging.getLogger(__name__)

# Columns that are first-class on the jobs table; everything else the pipeline
# attaches dynamically is stored in ``metadata_json`` (see Job model).
_JOB_CORE_FIELDS = frozenset({"job_id", "content", "resume_id", "created_at", "workspace_id"})

# Application status columns (stable keys, decoupled from i18n labels).
APPLICATION_STATUSES: tuple[str, ...] = (
    "saved",
    "applied",
    "no_response",
    "response",
    "interview",
    "accepted",
    "rejected",
)
ProcessingFinishOutcome = Literal["committed", "stale", "missing"]


def slugify_workspace_name(name: str) -> str:
    """Lowercase ASCII slug for a workspace name; empty input yields ``workspace``."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "workspace"


class DatabaseBusyError(RuntimeError):
    """A write reservation could not be obtained; retry the unchanged request."""


@contextmanager
def _translate_write_errors() -> Iterator[None]:
    """Expose only SQLite contention as retryable, for async and sync writers."""
    try:
        yield
    except OperationalError as error:
        code = getattr(error.orig, "sqlite_errorcode", None)
        if isinstance(code, int) and code & 0xFF in (
            sqlite3.SQLITE_BUSY,
            sqlite3.SQLITE_LOCKED,
        ):
            raise DatabaseBusyError("Database is busy") from error
        raise


class ResumeNotFoundError(ValueError):
    """Raised when a write targets a resume ID that no longer exists.

    Subclasses ``ValueError`` deliberately: every pre-existing
    ``except ValueError`` handler around resume writes keeps working unchanged,
    while callers that need to distinguish "the row is gone" from any other
    bad-argument error can catch this type instead of string-matching the
    message (the message is not an API).
    """

    def __init__(self, resume_id: str) -> None:
        self.resume_id = resume_id
        super().__init__(f"Resume not found: {resume_id}")


def _now() -> str:
    """Current UTC time as an ISO-8601 string (TinyDB-era format)."""
    return datetime.now(timezone.utc).isoformat()


class _Inherit:
    """Sentinel: "keep what is already stored". Distinct from ``None``,
    which means "clear it"."""


_INHERIT = _Inherit()


class Database:
    """Async SQLAlchemy facade for resume matcher data."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or settings.sqlite_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._async_engine = None
        self._async_session_factory: async_sessionmaker[AsyncSession] | None = None
        self._sync_engine = None
        self._sync_session_factory: sessionmaker[Session] | None = None
        self._initialized = False
        # The default workspace id is read on essentially every request (the
        # ``X-Workspace-Id`` fallback), never changes without a workspace
        # write, and is cheap to invalidate — so it is memoized rather than
        # costing one SELECT per request.
        self._default_workspace_cache: str | None = None

    # -- engine / session plumbing ------------------------------------------

    def _ensure_initialized(self) -> None:
        """Create engines and tables once (idempotent).

        Tables are created via the **sync** engine so both the sync (api_keys)
        and async (docs) paths see them immediately, without needing an event
        loop. Both engines point at the same file.
        """
        if self._initialized:
            return
        self._sync_engine = make_sync_engine(self.db_path)
        self._sync_session_factory = sessionmaker(
            self._sync_engine, expire_on_commit=False
        )
        init_models_sync(self._sync_engine)
        self._async_engine = make_async_engine(self.db_path)
        self._async_session_factory = async_sessionmaker(
            self._async_engine, expire_on_commit=False
        )
        self._initialized = True

    @property
    def _session(self) -> async_sessionmaker[AsyncSession]:
        self._ensure_initialized()
        assert self._async_session_factory is not None
        return self._async_session_factory

    @asynccontextmanager
    async def _write_session(self) -> AsyncIterator[AsyncSession]:
        """Reserve SQLite's writer before reading state that a write depends on.

        The database reservation serializes across connections and processes,
        unlike an in-memory lock. Callers commit the complete operation; closing
        the session rolls back every change if any stage raises.
        """
        with _translate_write_errors():
            async with self._session() as session:
                await session.execute(text("BEGIN IMMEDIATE"))
                yield session

    @property
    def _sync(self) -> sessionmaker[Session]:
        self._ensure_initialized()
        assert self._sync_session_factory is not None
        return self._sync_session_factory

    @contextmanager
    def _sync_write_session(self) -> Iterator[Session]:
        """Reserve a synchronous key-store writer with the same busy contract."""
        with _translate_write_errors():
            with self._sync() as session:
                session.execute(text("BEGIN IMMEDIATE"))
                yield session

    async def ensure_ready(self) -> None:
        """Build/migrate the schema and warm the default workspace.

        Called once at startup. Without it the first request pays schema
        migration *and* the default-workspace lookup inside its own deadline —
        the AI routes budget a fixed wall-clock time and would charge the
        user's first operation for cold start.
        """
        self._ensure_initialized()
        await self.default_workspace_id()

    async def close(self) -> None:
        """Dispose engines and release file handles."""
        if self._async_engine is not None:
            await self._async_engine.dispose()
            self._async_engine = None
            self._async_session_factory = None
        if self._sync_engine is not None:
            self._sync_engine.dispose()
            self._sync_engine = None
            self._sync_session_factory = None
        self._initialized = False
        self._default_workspace_cache = None

    # -- row -> dict converters ---------------------------------------------

    @staticmethod
    def _resume_to_dict(row: Resume) -> dict[str, Any]:
        doc: dict[str, Any] = {
            "resume_id": row.resume_id,
            "workspace_id": row.workspace_id,
            "content": row.content,
            "content_type": row.content_type,
            "filename": row.filename,
            "is_master": row.is_master,
            "parent_id": row.parent_id,
            "processed_data": row.processed_data,
            "head_version_id": row.head_version_id,
            "tex_source": row.tex_source,
            "template_settings": row.template_settings,
            "processing_status": row.processing_status,
            "cover_letter": row.cover_letter,
            "outreach_message": row.outreach_message,
            "interview_prep": row.interview_prep,
            "title": row.title,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
        # Preserve TinyDB absence semantics: omit the key entirely when None.
        if row.original_markdown is not None:
            doc["original_markdown"] = row.original_markdown
        return doc

    @staticmethod
    def _job_to_dict(row: Job) -> dict[str, Any]:
        doc: dict[str, Any] = {
            "job_id": row.job_id,
            "workspace_id": row.workspace_id,
            "content": row.content,
            "resume_id": row.resume_id,
            "created_at": row.created_at,
        }
        meta = row.metadata_json or {}
        if isinstance(meta, dict):
            doc.update(meta)  # flatten dynamic fields to top level
        return doc

    @staticmethod
    def _improvement_to_dict(row: Improvement) -> dict[str, Any]:
        return {
            "request_id": row.request_id,
            "original_resume_id": row.original_resume_id,
            "tailored_resume_id": row.tailored_resume_id,
            "job_id": row.job_id,
            "improvements": row.improvements,
            "created_at": row.created_at,
        }

    @staticmethod
    def _application_to_dict(row: Application) -> dict[str, Any]:
        return {
            "application_id": row.application_id,
            "workspace_id": row.workspace_id,
            "job_id": row.job_id,
            "resume_id": row.resume_id,
            "master_resume_id": row.master_resume_id,
            "status": row.status,
            "company": row.company,
            "role": row.role,
            "applied_at": row.applied_at,
            "notes": row.notes,
            "position": row.position,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    @staticmethod
    def _workspace_to_dict(row: Workspace) -> dict[str, Any]:
        return {
            "workspace_id": row.workspace_id,
            "name": row.name,
            "slug": row.slug,
            "content_language": row.content_language,
            "is_default": row.is_default,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    # -- Workspace operations -----------------------------------------------

    async def list_workspaces(self) -> list[dict[str, Any]]:
        """List workspaces oldest first."""
        async with self._session() as session:
            result = await session.execute(
                select(Workspace).order_by(Workspace.created_at, Workspace.workspace_id)
            )
            return [self._workspace_to_dict(row) for row in result.scalars().all()]

    async def get_workspace(self, workspace_id: str) -> dict[str, Any] | None:
        """Get one workspace by id."""
        async with self._session() as session:
            row = await session.get(Workspace, workspace_id)
            return self._workspace_to_dict(row) if row else None

    async def get_default_workspace(self) -> dict[str, Any]:
        """Return the default workspace, creating it if the row is missing.

        Migration ``0002_workspaces`` seeds exactly one default row, so the
        create branch only fires if a user deleted it out of band. Every
        request path depends on this id existing, so it self-heals rather than
        failing the request.
        """
        async with self._session() as session:
            row = (
                await session.execute(
                    select(Workspace).where(Workspace.is_default.is_(True))
                )
            ).scalars().first()
            if row is not None:
                return self._workspace_to_dict(row)

        async with self._write_session() as session:
            row = (
                await session.execute(
                    select(Workspace).where(Workspace.is_default.is_(True))
                )
            ).scalars().first()
            if row is None:
                row = (
                    await session.execute(
                        select(Workspace).order_by(Workspace.created_at).limit(1)
                    )
                ).scalars().first()
                if row is not None:
                    row.is_default = True
                else:
                    row = await self._insert_workspace(
                        session, name="Default", slug="default", is_default=True
                    )
            await session.commit()
            return self._workspace_to_dict(row)

    async def _insert_workspace(
        self,
        session: AsyncSession,
        *,
        name: str,
        slug: str,
        content_language: str = "en",
        is_default: bool = False,
    ) -> Workspace:
        """Stage one workspace row with a slug unique across the table."""
        taken = set(
            (await session.execute(select(Workspace.slug))).scalars().all()
        )
        candidate = slug
        suffix = 2
        while candidate in taken:
            candidate = f"{slug}-{suffix}"
            suffix += 1
        now = _now()
        row = Workspace(
            workspace_id=str(uuid4()),
            name=name,
            slug=candidate,
            content_language=content_language,
            is_default=is_default,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        return row

    async def create_workspace(
        self, *, name: str, content_language: str = "en"
    ) -> dict[str, Any]:
        """Create a workspace; the first one ever created becomes the default."""
        async with self._write_session() as session:
            any_existing = await session.scalar(select(Workspace.workspace_id).limit(1))
            row = await self._insert_workspace(
                session,
                name=name,
                slug=slugify_workspace_name(name),
                content_language=content_language,
                is_default=any_existing is None,
            )
            await session.commit()
            self._default_workspace_cache = None
            return self._workspace_to_dict(row)

    async def update_workspace(
        self, workspace_id: str, updates: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Update a workspace. Promoting a default demotes the previous one."""
        async with self._write_session() as session:
            row = await session.get(Workspace, workspace_id)
            if row is None:
                return None
            if updates.get("is_default"):
                previous = await session.execute(
                    select(Workspace).where(
                        Workspace.is_default.is_(True),
                        Workspace.workspace_id != workspace_id,
                    )
                )
                for other in previous.scalars().all():
                    other.is_default = False
                # Free the partial unique-index slot before claiming it.
                await session.flush()
                row.is_default = True
            if "name" in updates and updates["name"]:
                row.name = updates["name"]
            if "content_language" in updates and updates["content_language"]:
                row.content_language = updates["content_language"]
            row.updated_at = _now()
            await session.commit()
            self._default_workspace_cache = None
            return self._workspace_to_dict(row)

    async def delete_workspace(self, workspace_id: str) -> dict[str, Any]:
        """Delete a workspace and every document scoped to it.

        Returns ``{"deleted": bool, "reason": str | None}``: the last workspace
        and the default one are refused, so the app always has somewhere to
        put documents.
        """
        async with self._write_session() as session:
            row = await session.get(Workspace, workspace_id)
            if row is None:
                return {"deleted": False, "reason": "not_found"}
            if row.is_default:
                return {"deleted": False, "reason": "is_default"}
            total = await session.scalar(select(func.count()).select_from(Workspace))
            if int(total or 0) <= 1:
                return {"deleted": False, "reason": "last_workspace"}

            resume_ids = set(
                (
                    await session.execute(
                        select(Resume.resume_id).where(
                            Resume.workspace_id == workspace_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            job_ids = set(
                (
                    await session.execute(
                        select(Job.job_id).where(Job.workspace_id == workspace_id)
                    )
                )
                .scalars()
                .all()
            )
            await session.execute(
                delete(Application).where(Application.workspace_id == workspace_id)
            )
            if resume_ids:
                await session.execute(
                    delete(TailoringPreview).where(
                        or_(
                            TailoringPreview.source_id.in_(resume_ids),
                            TailoringPreview.result_resume_id.in_(resume_ids),
                        )
                    )
                )
                await session.execute(
                    delete(Improvement).where(
                        or_(
                            Improvement.original_resume_id.in_(resume_ids),
                            Improvement.tailored_resume_id.in_(resume_ids),
                        )
                    )
                )
            if job_ids:
                await session.execute(
                    delete(TailoringPreview).where(TailoringPreview.job_id.in_(job_ids))
                )
                await session.execute(
                    delete(Improvement).where(Improvement.job_id.in_(job_ids))
                )
            await session.execute(delete(Job).where(Job.workspace_id == workspace_id))
            await session.execute(
                delete(Resume).where(Resume.workspace_id == workspace_id)
            )
            await session.delete(row)
            await session.commit()
            self._default_workspace_cache = None
            return {"deleted": True, "reason": None}

    # -- Resume operations --------------------------------------------------

    async def default_workspace_id(self) -> str:
        """Id of the fallback workspace used when a caller supplies none."""
        if self._default_workspace_cache is None:
            self._default_workspace_cache = str(
                (await self.get_default_workspace())["workspace_id"]
            )
        return self._default_workspace_cache

    async def _resolve_workspace_id(self, workspace_id: str | None) -> str:
        return workspace_id or await self.default_workspace_id()

    async def create_resume(
        self,
        content: str,
        content_type: str = "md",
        filename: str | None = None,
        is_master: bool = False,
        parent_id: str | None = None,
        processed_data: dict[str, Any] | None = None,
        processing_status: str = "pending",
        cover_letter: str | None = None,
        outreach_message: str | None = None,
        title: str | None = None,
        original_markdown: str | None = None,
        interview_prep: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a new resume entry.

        processing_status: "pending", "processing", "ready", "failed"
        """
        row = self._new_resume(
            workspace_id=await self._resolve_workspace_id(workspace_id),
            content=content,
            content_type=content_type,
            filename=filename,
            is_master=is_master,
            parent_id=parent_id,
            processed_data=processed_data,
            processing_status=processing_status,
            cover_letter=cover_letter,
            outreach_message=outreach_message,
            interview_prep=interview_prep,
            title=title,
            original_markdown=original_markdown,
        )
        async with self._write_session() as session:
            session.add(row)
            await session.commit()
        return self._resume_to_dict(row)

    @staticmethod
    def _new_resume(**values: Any) -> Resume:
        """Construct a resume row for standalone or compound transactions."""
        now = _now()
        return Resume(resume_id=str(uuid4()), created_at=now, updated_at=now, **values)

    async def create_resume_atomic_master(
        self,
        content: str,
        content_type: str = "md",
        filename: str | None = None,
        processed_data: dict[str, Any] | None = None,
        processing_status: str = "pending",
        cover_letter: str | None = None,
        outreach_message: str | None = None,
        original_markdown: str | None = None,
        title: str | None = None,
        interview_prep: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a resume and replace a failed master in one transaction.

        Mastership is per workspace: the demotion candidate is looked up inside
        the target workspace only.
        """
        scope = await self._resolve_workspace_id(workspace_id)
        async with self._write_session() as session:
            current_master = (
                await session.execute(
                    select(Resume).where(
                        Resume.workspace_id == scope, Resume.is_master.is_(True)
                    )
                )
            ).scalar_one_or_none()
            is_master = current_master is None
            if current_master and current_master.processing_status in (
                "failed",
                "processing",
            ):
                current_master.is_master = False
                # Release the partial unique-index slot within this transaction.
                # An insertion failure still rolls this demotion back.
                await session.flush()
                is_master = True
            row = self._new_resume(
                workspace_id=scope,
                content=content,
                content_type=content_type,
                filename=filename,
                is_master=is_master,
                processed_data=processed_data,
                processing_status=processing_status,
                cover_letter=cover_letter,
                outreach_message=outreach_message,
                interview_prep=interview_prep,
                title=title,
                original_markdown=original_markdown,
            )
            session.add(row)
            await session.commit()
            return self._resume_to_dict(row)

    async def get_resume(self, resume_id: str) -> dict[str, Any] | None:
        """Get resume by ID."""
        async with self._session() as session:
            row = await session.get(Resume, resume_id)
            return self._resume_to_dict(row) if row else None

    async def get_master_resume(
        self, workspace_id: str | None = None
    ) -> dict[str, Any] | None:
        """Get the workspace's master resume if one exists."""
        scope = await self._resolve_workspace_id(workspace_id)
        async with self._session() as session:
            result = await session.execute(
                select(Resume).where(
                    Resume.workspace_id == scope, Resume.is_master.is_(True)
                )
            )
            row = result.scalars().first()
            return self._resume_to_dict(row) if row else None

    async def update_resume(
        self, resume_id: str, updates: dict[str, Any]
    ) -> dict[str, Any]:
        """Update resume by ID.

        Raises:
            ResumeNotFoundError: If resume not found. It subclasses
                ``ValueError``, so existing ``except ValueError`` callers are
                unaffected.
        """
        async with self._write_session() as session:
            row = await session.get(Resume, resume_id)
            if row is None:
                raise ResumeNotFoundError(resume_id)
            for key, value in updates.items():
                if hasattr(row, key):
                    setattr(row, key, value)
                else:
                    logger.warning("Ignoring unknown resume field on update: %s", key)
            row.updated_at = _now()
            await session.commit()
            return self._resume_to_dict(row)

    async def claim_resume_processing(
        self,
        resume_id: str,
        *,
        allow_ready_at: str | None = None,
    ) -> str | None:
        """Rotate processing ownership and return its opaque operation token.

        Failed and processing rows are retryable. A legacy ready row is only
        claimable when the caller observed the same version and found its
        structured content empty. ``None`` means a concurrent completion made
        the row ineligible; a missing row raises ``ResumeNotFoundError``.
        """
        token = str(uuid4())
        eligible = Resume.processing_status.in_(("failed", "processing"))
        if allow_ready_at is not None:
            eligible = or_(
                eligible,
                and_(
                    Resume.processing_status == "ready",
                    Resume.updated_at == allow_ready_at,
                ),
            )

        async with self._write_session() as session:
            result = await session.execute(
                update(Resume)
                .where(Resume.resume_id == resume_id, eligible)
                .values(
                    processing_status="processing",
                    processing_token=token,
                    updated_at=_now(),
                )
            )
            if result.rowcount == 1:
                await session.commit()
                return token

            exists = await session.scalar(
                select(Resume.resume_id).where(Resume.resume_id == resume_id)
            )
            if exists is None:
                raise ResumeNotFoundError(resume_id)
            return None

    async def finish_resume_processing(
        self,
        resume_id: str,
        token: str | None,
        *,
        processing_status: Literal["ready", "failed"],
        processed_data: dict[str, Any] | None = None,
    ) -> ProcessingFinishOutcome:
        """Finish an owned attempt, or retire an unclaimed row with ``None``."""
        if token is None and processing_status != "failed":
            raise ValueError("Ready processing requires an ownership token")
        values: dict[str, Any] = {
            "processing_status": processing_status,
            "processing_token": None,
            "updated_at": _now(),
        }
        values["processed_data"] = (
            processed_data if processing_status == "ready" else None
        )

        async with self._write_session() as session:
            result = await session.execute(
                update(Resume)
                .where(
                    Resume.resume_id == resume_id,
                    Resume.processing_token == token,
                    Resume.processing_status == "processing",
                )
                .values(**values)
            )
            if result.rowcount == 1:
                await session.commit()
                return "committed"

            exists = await session.scalar(
                select(Resume.resume_id).where(Resume.resume_id == resume_id)
            )
            return "stale" if exists is not None else "missing"

    async def delete_resume(self, resume_id: str) -> bool:
        """Delete resume by ID."""
        async with self._write_session() as session:
            row = await session.get(Resume, resume_id)
            if row is None:
                return False
            # Keep a content-free consumed marker for deleted results so retries
            # cannot recreate them, while removing their cached personal data.
            previews = await session.execute(
                select(TailoringPreview).where(
                    TailoringPreview.result_resume_id == resume_id,
                )
            )
            for preview in previews.scalars():
                preview.response_data = None
            await session.execute(
                delete(TailoringPreview).where(TailoringPreview.source_id == resume_id)
            )
            await session.delete(row)
            await session.commit()
            return True

    async def list_resumes(
        self, workspace_id: str | None = None
    ) -> list[dict[str, Any]]:
        """List the workspace's resumes, oldest first."""
        scope = await self._resolve_workspace_id(workspace_id)
        async with self._session() as session:
            result = await session.execute(
                select(Resume)
                .where(Resume.workspace_id == scope)
                .order_by(Resume.created_at)
            )
            return [self._resume_to_dict(row) for row in result.scalars().all()]

    async def set_master_resume(self, resume_id: str) -> bool:
        """Set a resume as its workspace's master, unsetting the previous one.

        Returns False if the resume doesn't exist. Demote-then-promote happens
        in a single transaction so the partial unique index is never violated.
        Scoping is taken from the target row, so promoting in one workspace
        never touches another's master.
        """
        async with self._write_session() as session:
            target = await session.get(Resume, resume_id)
            if target is None:
                logger.warning("Cannot set master: resume %s not found", resume_id)
                return False

            current = await session.execute(
                select(Resume).where(
                    Resume.workspace_id == target.workspace_id,
                    Resume.is_master.is_(True),
                )
            )
            for row in current.scalars().all():
                if row.resume_id != resume_id:
                    row.is_master = False
            # Flush the demotions before promoting to satisfy the unique index.
            await session.flush()
            target.is_master = True
            await session.commit()
            return True

    async def seed_resume_version(
        self, resume_id: str, *, origin: str, origin_ref: str | None = None
    ) -> dict[str, Any] | None:
        """Record a freshly created resume's content as its first version.

        Creation paths (upload, AI tailor, wizard) build the row and its
        structured content in their own transactions; this gives that content
        a history entry. A no-op when the resume already has one, so a retried
        request cannot double-seed.
        """
        resume = await self.get_resume(resume_id)
        if resume is None or resume.get("head_version_id"):
            return None
        document = resume.get("processed_data")
        if not document:
            return None
        return await self.commit_resume_version(
            resume_id, document, origin=origin, origin_ref=origin_ref
        )

    # -- Resume version history ---------------------------------------------

    @staticmethod
    def _version_to_dict(row: ResumeVersion, *, head_version_id: str | None) -> dict[str, Any]:
        return {
            "version_id": row.version_id,
            "resume_id": row.resume_id,
            "workspace_id": row.workspace_id,
            "parent_version_id": row.parent_version_id,
            "content_hash": row.content_hash,
            "document": row.document,
            "tex_source": row.tex_source,
            "tex_source_mode": row.tex_source_mode,
            "label": row.label,
            "origin": row.origin,
            "origin_ref": row.origin_ref,
            "is_pinned": row.is_pinned,
            "created_at": row.created_at,
            "is_head": row.version_id == head_version_id,
        }

    async def commit_resume_version(
        self,
        resume_id: str,
        document: dict[str, Any],
        *,
        origin: str,
        origin_ref: str | None = None,
        label: str | None = None,
        # Not supplied means "whatever the resume currently has", so an
        # ordinary document save records the override that was in force
        # rather than silently dropping it from history.
        tex_source: str | None | _Inherit = _INHERIT,
        tex_source_mode: str | None = None,
        resume_updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist one content change as a version, atomically.

        The version row, the resume's ``processed_data``/``content`` and the
        head pointer move together inside a single ``BEGIN IMMEDIATE``
        transaction, so a crash can never leave a version nothing points at.

        Three rules shape the history:

        * **Dedup** — an unchanged document returns the current head untouched.
        * **Coalesce** — consecutive unlabelled, unpinned ``manual`` saves
          inside ``settings.resume_version_coalesce_seconds`` replace the head
          in place, inheriting its parent. Builder autosave would otherwise
          produce hundreds of rows, and every pause still checkpoints.
        * **Append-only** — nothing else is ever rewritten; a restore writes a
          new version whose document is the restored one.
        """
        content_hash = document_fingerprint(document)
        now = _now()

        async with self._write_session() as session:
            resume = await session.get(Resume, resume_id)
            if resume is None:
                raise ResumeNotFoundError(resume_id)

            head = (
                await session.get(ResumeVersion, resume.head_version_id)
                if resume.head_version_id
                else None
            )

            effective_tex = resume.tex_source if tex_source is _INHERIT else tex_source
            effective_mode = tex_source_mode or ("edited" if effective_tex else "generated")

            # A tex-only edit leaves the document identical, so the source
            # has to take part in the dedup or the checkpoint is lost.
            if (
                head is not None
                and head.content_hash == content_hash
                and head.tex_source == effective_tex
            ):
                return self._version_to_dict(head, head_version_id=head.version_id)

            row = self._coalescing_target(head, origin, now)
            if row is None:
                row = ResumeVersion(
                    version_id=str(uuid4()),
                    resume_id=resume_id,
                    workspace_id=resume.workspace_id,
                    parent_version_id=head.version_id if head else None,
                    created_at=now,
                )
                session.add(row)

            row.content_hash = content_hash
            row.document = copy.deepcopy(document)
            row.tex_source = effective_tex
            row.tex_source_mode = effective_mode
            row.label = label
            row.origin = origin
            row.origin_ref = origin_ref

            for key, value in (resume_updates or {}).items():
                if hasattr(resume, key):
                    setattr(resume, key, value)
                else:
                    logger.warning("Ignoring unknown resume field on commit: %s", key)
            resume.processed_data = copy.deepcopy(document)
            resume.head_version_id = row.version_id
            resume.updated_at = now

            await session.commit()
            return self._version_to_dict(row, head_version_id=row.version_id)

    @staticmethod
    def _coalescing_target(
        head: ResumeVersion | None, origin: str, now: str
    ) -> ResumeVersion | None:
        """The head row to overwrite in place, or ``None`` to append."""
        window = settings.resume_version_coalesce_seconds
        if (
            window <= 0
            or head is None
            or origin != "manual"
            or head.origin != "manual"
            or head.label is not None
            or head.is_pinned
        ):
            return None
        try:
            age = (
                datetime.fromisoformat(now) - datetime.fromisoformat(head.created_at)
            ).total_seconds()
        except ValueError:
            return None
        return head if 0 <= age <= window else None

    async def list_resume_versions(
        self, resume_id: str, *, limit: int = 50, cursor: str | None = None
    ) -> list[dict[str, Any]]:
        """Version metadata for a resume, newest first. No document payloads."""
        async with self._session() as session:
            resume = await session.get(Resume, resume_id)
            if resume is None:
                raise ResumeNotFoundError(resume_id)
            stmt = select(ResumeVersion).where(ResumeVersion.resume_id == resume_id)
            if cursor:
                stmt = stmt.where(ResumeVersion.created_at < cursor)
            stmt = stmt.order_by(
                ResumeVersion.created_at.desc(), ResumeVersion.version_id.desc()
            ).limit(limit)
            rows = (await session.execute(stmt)).scalars().all()
            return [
                {
                    key: value
                    for key, value in self._version_to_dict(
                        row, head_version_id=resume.head_version_id
                    ).items()
                    if key != "document"
                }
                for row in rows
            ]

    async def get_resume_version(self, version_id: str) -> dict[str, Any] | None:
        """One version, document included."""
        async with self._session() as session:
            row = await session.get(ResumeVersion, version_id)
            if row is None:
                return None
            resume = await session.get(Resume, row.resume_id)
            head = resume.head_version_id if resume else None
            return self._version_to_dict(row, head_version_id=head)

    async def update_resume_version(
        self, version_id: str, updates: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Set a version's user label or pin. Content is immutable."""
        async with self._write_session() as session:
            row = await session.get(ResumeVersion, version_id)
            if row is None:
                return None
            if "label" in updates:
                label = updates["label"]
                row.label = label.strip() or None if isinstance(label, str) else None
            if "is_pinned" in updates:
                row.is_pinned = bool(updates["is_pinned"])
            resume = await session.get(Resume, row.resume_id)
            head = resume.head_version_id if resume else None
            await session.commit()
            return self._version_to_dict(row, head_version_id=head)

    async def delete_resume_version(self, version_id: str) -> dict[str, Any]:
        """Delete one version. The head and pinned versions are refused."""
        async with self._write_session() as session:
            row = await session.get(ResumeVersion, version_id)
            if row is None:
                return {"deleted": False, "reason": "not_found"}
            resume = await session.get(Resume, row.resume_id)
            if resume is not None and resume.head_version_id == version_id:
                return {"deleted": False, "reason": "is_head"}
            if row.is_pinned:
                return {"deleted": False, "reason": "is_pinned"}
            # Children re-parent to the deleted row's parent so lineage stays
            # walkable instead of pointing at a missing id.
            await session.execute(
                update(ResumeVersion)
                .where(ResumeVersion.parent_version_id == version_id)
                .values(parent_version_id=row.parent_version_id)
            )
            await session.delete(row)
            await session.commit()
            return {"deleted": True, "reason": None}

    # -- Job operations -----------------------------------------------------

    async def create_job(
        self,
        content: str,
        resume_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        """Create one job description using the atomic batch writer."""
        return (await self.create_jobs([content], resume_id, workspace_id))[0]

    async def create_jobs(
        self,
        contents: list[str],
        resume_id: str | None = None,
        workspace_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Persist a validated job-description batch atomically, in input order."""
        scope = await self._resolve_workspace_id(workspace_id)
        rows = [
            Job(
                job_id=str(uuid4()),
                workspace_id=scope,
                content=content,
                resume_id=resume_id,
                created_at=_now(),
                metadata_json={},
            )
            for content in contents
        ]
        async with self._write_session() as session:
            session.add_all(rows)
            await session.commit()
        return [self._job_to_dict(row) for row in rows]

    async def get_job(self, job_id: str) -> dict[str, Any] | None:
        """Get job by ID (dynamic fields flattened to top level)."""
        async with self._session() as session:
            row = await session.get(Job, job_id)
            return self._job_to_dict(row) if row else None

    async def update_job(
        self, job_id: str, updates: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Update a job by ID.

        Core columns are set directly; every other key is merged into
        ``metadata_json`` so dynamic pipeline fields (``preview_hash``,
        ``job_keywords``, ``company``/``role``, …) round-trip through
        ``get_job`` as top-level keys.
        """
        async with self._write_session() as session:
            row = await session.get(Job, job_id)
            if row is None:
                return None
            meta = dict(row.metadata_json or {})
            for key, value in updates.items():
                if key in _JOB_CORE_FIELDS:
                    setattr(row, key, value)
                else:
                    meta[key] = value
            # Reassign so SQLAlchemy detects the JSON mutation.
            row.metadata_json = meta
            await session.commit()
            return self._job_to_dict(row)

    async def delete_job(self, job_id: str) -> bool:
        """Delete a job by ID (used to clean up an orphaned manual-add job)."""
        async with self._write_session() as session:
            row = await session.get(Job, job_id)
            if row is None:
                return False
            await session.execute(
                delete(TailoringPreview).where(TailoringPreview.job_id == job_id)
            )
            await session.delete(row)
            await session.commit()
            return True

    # -- Preview and confirmation operations --------------------------------

    @staticmethod
    async def _validate_preview_inputs(
        session: AsyncSession,
        preview: TailoringPreview,
    ) -> None:
        source = await session.get(Resume, preview.source_id)
        job = await session.get(Job, preview.job_id)
        if (
            source is None
            or job is None
            or resume_fingerprint(
                source.content, source.processed_data, source.original_markdown
            )
            != preview.source_hash
            or job_fingerprint(job.content) != preview.job_hash
        ):
            raise PreviewConflictError(
                "Resume or job description changed. Please retry preview."
            )

    async def register_preview(
        self,
        *,
        source_id: str,
        job_id: str,
        payload_hash: str,
        source_hash: str,
        job_hash: str,
        prompt_id: str,
        ttl_seconds: int,
        improvements: list[dict[str, Any]] | None = None,
    ) -> dict[str, str]:
        """Register the exact input/output snapshot before acknowledging preview."""
        now = _now()
        row = TailoringPreview(
            preview_id=str(uuid4()),
            improvements=copy.deepcopy(improvements or []),
            source_id=source_id,
            job_id=job_id,
            payload_hash=payload_hash,
            source_hash=source_hash,
            job_hash=job_hash,
            created_at=now,
            expires_at=(
                datetime.fromisoformat(now) + timedelta(seconds=ttl_seconds)
            ).isoformat(),
        )
        async with self._write_session() as session:
            await self._validate_preview_inputs(session, row)
            await session.execute(
                delete(TailoringPreview).where(
                    TailoringPreview.expires_at <= now,
                    TailoringPreview.result_resume_id.is_(None),
                    or_(
                        TailoringPreview.claim_token.is_(None),
                        TailoringPreview.claim_expires_at <= now,
                    ),
                )
            )
            job = await session.get(Job, job_id)
            assert job is not None  # Validated in the same reserved transaction.
            metadata = dict(job.metadata_json or {})
            hashes = metadata.get("preview_hashes")
            hashes = dict(hashes) if isinstance(hashes, dict) else {}
            hashes[prompt_id] = payload_hash
            metadata.update(
                preview_hash=payload_hash,
                preview_prompt_id=prompt_id,
                preview_hashes=hashes,
            )
            job.metadata_json = metadata
            session.add(row)
            await session.commit()
        return {"preview_id": row.preview_id, "expires_at": row.expires_at}

    async def claim_preview(
        self,
        *,
        preview_id: str | None,
        source_id: str,
        job_id: str,
        payload_hash: str,
        lease_seconds: int,
    ) -> PreviewClaim:
        """Claim once across workers; committed retries bypass generation."""
        async with self._write_session() as session:
            if preview_id:
                row = await session.get(TailoringPreview, preview_id)
            else:
                # Compatibility for clients that omit the new operation ID.
                row = (
                    await session.execute(
                        select(TailoringPreview)
                        .where(
                            TailoringPreview.source_id == source_id,
                            TailoringPreview.job_id == job_id,
                            TailoringPreview.payload_hash == payload_hash,
                            or_(TailoringPreview.result_resume_id.is_not(None), TailoringPreview.expires_at > _now()),
                        )
                        .order_by(TailoringPreview.result_resume_id.is_not(None).desc(), TailoringPreview.created_at.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
            if row is None:
                raise PreviewValidationError(
                    "Preview required before confirmation. Please retry preview."
                )
            if row.source_id != source_id or row.job_id != job_id:
                raise PreviewConflictError(
                    "Preview belongs to different inputs. Please retry preview."
                )
            if row.payload_hash != payload_hash:
                raise PreviewValidationError(
                    "Invalid improved resume data. Please retry preview."
                )
            if row.result_resume_id is not None:
                if (
                    row.response_data is None
                    or await session.get(Resume, row.result_resume_id) is None
                ):
                    raise PreviewConflictError(
                        "Confirmed resume was deleted. Please retry preview."
                    )
                return PreviewClaim(
                    row.preview_id, response=copy.deepcopy(row.response_data)
                )
            now = _now()
            if row.expires_at <= now:
                raise PreviewConflictError("Preview expired. Please retry preview.")
            await self._validate_preview_inputs(session, row)
            if row.claim_token and row.claim_expires_at and row.claim_expires_at > now:
                raise PreviewBusyError(
                    "Confirmation is already in progress. Please retry shortly."
                )
            row.claim_token = str(uuid4())
            row.claim_expires_at = (
                datetime.fromisoformat(now) + timedelta(seconds=lease_seconds)
            ).isoformat()
            await session.commit()
            return PreviewClaim(row.preview_id, token=row.claim_token, improvements=copy.deepcopy(row.improvements or []))

    async def release_preview_claim(self, claim: PreviewClaim) -> None:
        """Release only this request's uncommitted claim, including on cancellation."""
        if not claim.token:
            return
        async with self._write_session() as session:
            row = await session.get(TailoringPreview, claim.preview_id)
            if row is not None and claim.token and row.claim_token == claim.token:
                row.claim_token = None
                row.claim_expires_at = None
                await session.commit()

    async def complete_preview(
        self,
        *,
        claim: PreviewClaim,
        resume_fields: dict[str, Any],
        response_data: dict[str, Any],
        improvements: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Commit resume, required relation and replay snapshot atomically."""
        async with self._write_session() as session:
            preview = await session.get(TailoringPreview, claim.preview_id)
            now = _now()
            if (
                preview is None
                or not claim.token
                or preview.claim_token != claim.token
                or not preview.claim_expires_at
                or preview.claim_expires_at <= now
            ):
                raise PreviewConflictError(
                    "Confirmation ownership expired. Please retry preview."
                )
            await self._validate_preview_inputs(session, preview)
            row = self._new_resume(**resume_fields)
            result = copy.deepcopy(response_data)
            result.update(
                resume_id=row.resume_id,
                preview_id=preview.preview_id,
                preview_expires_at=preview.expires_at,
            )
            session.add(row)
            await session.flush()
            session.add(
                Improvement(
                    request_id=result["request_id"],
                    original_resume_id=preview.source_id,
                    tailored_resume_id=row.resume_id,
                    job_id=preview.job_id,
                    improvements=improvements,
                    created_at=now,
                )
            )
            preview.response_data = result
            preview.result_resume_id = row.resume_id
            preview.claim_token = None
            preview.claim_expires_at = None
            await session.commit()
            return result

    # -- Improvement operations ---------------------------------------------

    async def create_tailored_resume(
        self,
        *,
        request_id: str,
        original_resume_id: str,
        job_id: str,
        resume_fields: dict[str, Any],
        improvements: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Commit a direct tailoring result and its required relation together."""
        row = self._new_resume(**resume_fields)
        async with self._write_session() as session:
            session.add(row)
            await session.flush()
            session.add(
                Improvement(
                    request_id=request_id,
                    original_resume_id=original_resume_id,
                    tailored_resume_id=row.resume_id,
                    job_id=job_id,
                    improvements=copy.deepcopy(improvements),
                    created_at=_now(),
                )
            )
            await session.commit()
        return self._resume_to_dict(row)

    async def create_improvement(
        self,
        original_resume_id: str,
        tailored_resume_id: str,
        job_id: str,
        improvements: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Create an improvement result entry."""
        request_id = str(uuid4())
        now = _now()
        async with self._write_session() as session:
            session.add(
                Improvement(
                    request_id=request_id,
                    original_resume_id=original_resume_id,
                    tailored_resume_id=tailored_resume_id,
                    job_id=job_id,
                    improvements=improvements,
                    created_at=now,
                )
            )
            await session.commit()
        return {
            "request_id": request_id,
            "original_resume_id": original_resume_id,
            "tailored_resume_id": tailored_resume_id,
            "job_id": job_id,
            "improvements": improvements,
            "created_at": now,
        }

    async def get_improvement_by_tailored_resume(
        self, tailored_resume_id: str
    ) -> dict[str, Any] | None:
        """Get improvement record by tailored resume ID."""
        async with self._session() as session:
            result = await session.execute(
                select(Improvement).where(
                    Improvement.tailored_resume_id == tailored_resume_id
                )
            )
            row = result.scalars().first()
            return self._improvement_to_dict(row) if row else None

    # -- Application (tracker) operations -----------------------------------

    async def _next_position(
        self, session: AsyncSession, workspace_id: str, status: str
    ) -> int:
        result = await session.execute(
            select(func.count())
            .select_from(Application)
            .where(
                Application.workspace_id == workspace_id,
                Application.status == status,
            )
        )
        return int(result.scalar() or 0)

    async def _renumber(
        self, session: AsyncSession, workspace_id: str, status: str
    ) -> None:
        """Renumber one workspace column to a contiguous 0..n-1 sequence."""
        result = await session.execute(
            select(Application)
            .where(
                Application.workspace_id == workspace_id,
                Application.status == status,
            )
            .order_by(Application.position, Application.created_at)
        )
        for index, row in enumerate(result.scalars().all()):
            if row.position != index:
                row.position = index

    async def _insert_application(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        job_id: str,
        resume_id: str,
        master_resume_id: str | None = None,
        status: str = "applied",
        company: str | None = None,
        role: str | None = None,
        applied_at: str | None = None,
        notes: str | None = None,
    ) -> Application:
        """Stage one card with shared date and ordering rules, without committing."""
        now = _now()
        if applied_at is None and status != "saved":
            applied_at = now
        position = await self._next_position(session, workspace_id, status)
        row = Application(
            application_id=str(uuid4()),
            workspace_id=workspace_id,
            job_id=job_id,
            resume_id=resume_id,
            master_resume_id=master_resume_id,
            status=status,
            company=company,
            role=role,
            applied_at=applied_at,
            notes=notes,
            position=position,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        return row

    async def create_manual_application(
        self,
        *,
        content: str,
        resume_id: str,
        status: str = "applied",
        company: str | None = None,
        role: str | None = None,
        notes: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        """Commit a pasted job and its tracker card together, or roll back both."""
        scope = await self._resolve_workspace_id(workspace_id)
        async with self._write_session() as session:
            job = Job(
                job_id=str(uuid4()),
                workspace_id=scope,
                content=content,
                resume_id=resume_id,
                created_at=_now(),
                metadata_json=(
                    {"company": company, "role": role} if company or role else {}
                ),
            )
            session.add(job)
            await session.flush()
            row = await self._insert_application(
                session,
                workspace_id=scope,
                job_id=job.job_id,
                resume_id=resume_id,
                status=status,
                company=company,
                role=role,
                notes=notes,
            )
            await session.commit()
            return self._application_to_dict(row)

    async def create_application(
        self,
        job_id: str,
        resume_id: str,
        master_resume_id: str | None = None,
        status: str = "applied",
        company: str | None = None,
        role: str | None = None,
        applied_at: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Create a tracker card, deduped on (job_id, resume_id).

        If a card for the same job+resume already exists it is returned as-is
        (survives double-submit / retried confirms).
        """
        # A replay needs only a read. Recheck under the reservation before an
        # insert so concurrent new cards still share the position allocation.
        async with self._session() as session:
            found = await session.scalar(select(Application).where(
                Application.job_id == job_id, Application.resume_id == resume_id
            ))
            if found is not None:
                return self._application_to_dict(found)
        async with self._write_session() as session:
            existing = await session.execute(
                select(Application).where(
                    Application.job_id == job_id, Application.resume_id == resume_id
                )
            )
            found = existing.scalars().first()
            if found is not None:
                return self._application_to_dict(found)

            # A card lives where its job does, so autocreate from any code path
            # (including AI confirm, which has no request headers of its own)
            # lands in the right workspace.
            scope = await session.scalar(
                select(Job.workspace_id).where(Job.job_id == job_id)
            ) or await session.scalar(
                select(Resume.workspace_id).where(Resume.resume_id == resume_id)
            )
            row = await self._insert_application(
                session,
                workspace_id=scope
                or await session.scalar(
                    select(Workspace.workspace_id)
                    .where(Workspace.is_default.is_(True))
                    .limit(1)
                ),
                job_id=job_id,
                resume_id=resume_id,
                master_resume_id=master_resume_id,
                status=status,
                company=company,
                role=role,
                applied_at=applied_at,
                notes=notes,
            )
            try:
                await session.commit()
            except IntegrityError:
                # A concurrent create won the (job_id, resume_id) unique
                # constraint — return the existing card instead of duplicating.
                await session.rollback()
                dup = await session.execute(
                    select(Application).where(
                        Application.job_id == job_id,
                        Application.resume_id == resume_id,
                    )
                )
                found = dup.scalars().first()
                if found is not None:
                    logger.debug(
                        "Deduped concurrent application create for job=%s resume=%s",
                        job_id,
                        resume_id,
                    )
                    return self._application_to_dict(found)
                raise
            return self._application_to_dict(row)

    async def list_applications(
        self, status: str | None = None, workspace_id: str | None = None
    ) -> list[dict[str, Any]]:
        """List one workspace's applications ordered by (status, position)."""
        scope = await self._resolve_workspace_id(workspace_id)
        async with self._session() as session:
            stmt = select(Application).where(Application.workspace_id == scope)
            if status is not None:
                stmt = stmt.where(Application.status == status)
            stmt = stmt.order_by(Application.status, Application.position)
            result = await session.execute(stmt)
            return [self._application_to_dict(row) for row in result.scalars().all()]

    async def get_application(self, application_id: str) -> dict[str, Any] | None:
        """Get an application by ID."""
        async with self._session() as session:
            row = await session.get(Application, application_id)
            return self._application_to_dict(row) if row else None

    async def update_application(
        self, application_id: str, updates: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Update an application; renumber columns when status/position change.

        ``position`` is interpreted as the desired index within the (possibly
        new) ``status`` column; siblings are renumbered server-side so the
        column stays a contiguous 0..n-1 sequence.
        """
        async with self._write_session() as session:
            row = await session.get(Application, application_id)
            if row is None:
                return None

            old_status = row.status
            new_status = updates.get("status", old_status)
            target_position = updates.get("position", None)

            for key in ("company", "role", "applied_at", "notes"):
                if key in updates:
                    setattr(row, key, updates[key])

            if (
                old_status == "saved"
                and new_status != "saved"
                and row.applied_at is None
                and "applied_at" not in updates
            ):
                row.applied_at = _now()

            moved = "status" in updates or "position" in updates
            if moved:
                row.status = new_status
                # Park it out of the way, renumber both columns, then reinsert.
                row.position = 10_000_000
                await session.flush()
                if old_status != new_status:
                    await self._renumber(session, row.workspace_id, old_status)
                # Renumber the target column excluding this row, then splice in.
                siblings = await session.execute(
                    select(Application)
                    .where(
                        Application.workspace_id == row.workspace_id,
                        Application.status == new_status,
                        Application.application_id != application_id,
                    )
                    .order_by(Application.position, Application.created_at)
                )
                ordered = list(siblings.scalars().all())
                if target_position is None or target_position > len(ordered):
                    target_position = len(ordered)
                if target_position < 0:
                    target_position = 0
                ordered.insert(target_position, row)
                for index, item in enumerate(ordered):
                    item.position = index

            row.updated_at = _now()
            await session.commit()
            return self._application_to_dict(row)

    async def bulk_update_applications(
        self, application_ids: list[str], status: str
    ) -> int:
        """Move many applications to the end of ``status``. Returns count moved."""
        moved = 0
        async with self._write_session() as session:
            affected_old: set[tuple[str, str]] = set()
            workspaces: set[str] = set()
            for application_id in application_ids:
                row = await session.get(Application, application_id)
                if row is None:
                    continue
                affected_old.add((row.workspace_id, row.status))
                workspaces.add(row.workspace_id)
                if (
                    row.status == "saved"
                    and status != "saved"
                    and row.applied_at is None
                ):
                    row.applied_at = _now()
                row.status = status
                row.position = 20_000_000 + moved  # provisional, renumbered below
                row.updated_at = _now()
                moved += 1
            await session.flush()
            for workspace_id, old_status in affected_old - {(w, status) for w in workspaces}:
                await self._renumber(session, workspace_id, old_status)
            for workspace_id in workspaces:
                await self._renumber(session, workspace_id, status)
            await session.commit()
        return moved

    async def delete_application(self, application_id: str) -> bool:
        """Delete an application; renumber its column."""
        async with self._write_session() as session:
            row = await session.get(Application, application_id)
            if row is None:
                return False
            status = row.status
            workspace_id = row.workspace_id
            await session.delete(row)
            await session.flush()
            await self._renumber(session, workspace_id, status)
            await session.commit()
            return True

    async def bulk_delete_applications(self, application_ids: list[str]) -> int:
        """Delete many applications; renumber affected columns. Returns count."""
        deleted = 0
        async with self._write_session() as session:
            affected: set[tuple[str, str]] = set()
            for application_id in application_ids:
                row = await session.get(Application, application_id)
                if row is None:
                    continue
                affected.add((row.workspace_id, row.status))
                await session.delete(row)
                deleted += 1
            await session.flush()
            for workspace_id, status in affected:
                await self._renumber(session, workspace_id, status)
            await session.commit()
        return deleted

    # -- Encrypted API key store (sync; read on the LLM hot path) -----------

    def get_api_key_ciphertexts(self) -> dict[str, str]:
        """Return ``{provider: ciphertext}`` for all stored keys (sync)."""
        with self._sync() as session:
            rows = session.execute(select(ApiKey)).scalars().all()
            return {row.provider: row.ciphertext for row in rows}

    def set_api_key_ciphertext(self, provider: str, ciphertext: str) -> None:
        """Upsert one provider's ciphertext (sync)."""
        with self._sync_write_session() as session:
            row = session.get(ApiKey, provider)
            if row is None:
                session.add(
                    ApiKey(provider=provider, ciphertext=ciphertext, updated_at=_now())
                )
            else:
                row.ciphertext = ciphertext
                row.updated_at = _now()
            session.commit()

    def delete_api_key(self, provider: str) -> None:
        """Delete one provider's key (sync)."""
        with self._sync_write_session() as session:
            row = session.get(ApiKey, provider)
            if row is not None:
                session.delete(row)
                session.commit()

    def clear_api_keys(self) -> None:
        """Delete all stored keys (sync)."""
        with self._sync_write_session() as session:
            session.execute(delete(ApiKey))
            session.commit()

    def replace_api_keys(self, ciphertexts: dict[str, str]) -> None:
        """Atomically replace the whole key store (clear + insert in one txn).

        A single transaction means a failure mid-write can't leave the store
        half-cleared and wipe a user's previously saved keys.
        """
        with self._sync_write_session() as session:
            session.execute(delete(ApiKey))
            now = _now()
            for provider, ciphertext in ciphertexts.items():
                if ciphertext:
                    session.add(
                        ApiKey(provider=provider, ciphertext=ciphertext, updated_at=now)
                    )
            session.commit()

    # -- Stats / maintenance ------------------------------------------------

    async def get_stats(self) -> dict[str, Any]:
        """Get database statistics."""
        async with self._session() as session:
            resumes = await session.scalar(select(func.count()).select_from(Resume))
            jobs = await session.scalar(select(func.count()).select_from(Job))
            improvements = await session.scalar(
                select(func.count()).select_from(Improvement)
            )
            master = await session.execute(
                select(Resume.resume_id).where(Resume.is_master.is_(True)).limit(1)
            )
            return {
                "total_resumes": int(resumes or 0),
                "total_jobs": int(jobs or 0),
                "total_improvements": int(improvements or 0),
                "has_master_resume": master.first() is not None,
            }

    async def reset_database(self) -> None:
        """Reset by truncating user-document tables and clearing uploads.

        Clears resumes/jobs/improvements, preview replay data, and tracker applications (leaving
        orphaned cards after a full data reset would be a bug). Encrypted
        ``api_keys`` are preserved — matching the pre-existing behavior where a
        reset never wiped the user's stored credentials.
        """
        async with self._write_session() as session:
            await session.execute(delete(TailoringPreview))
            await session.execute(delete(Application))
            await session.execute(delete(Improvement))
            await session.execute(delete(Job))
            await session.execute(delete(Resume))
            await session.commit()

        uploads_dir = settings.data_dir / "uploads"
        if uploads_dir.exists():
            shutil.rmtree(uploads_dir)
            uploads_dir.mkdir(parents=True, exist_ok=True)


# Global database instance
db = Database()
