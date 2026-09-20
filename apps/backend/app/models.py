"""SQLAlchemy ORM models for Resume Matcher.

A single declarative ``Base`` backs all tables (doc tables migrated from
TinyDB plus the new ``applications`` and ``api_keys`` tables). The facade in
``app/database.py`` converts ORM rows to plain dicts so the rest of the app
never sees ORM objects — preserving the TinyDB-era contracts.
"""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Boolean, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow_iso() -> str:
    """Return the current UTC time as an ISO-8601 string.

    Timestamps are stored as strings (not native datetimes) to preserve the
    TinyDB-era behavior: code compares them lexically and returns them to
    clients verbatim.
    """
    return datetime.now(timezone.utc).isoformat()


class Base(DeclarativeBase):
    """Declarative base shared by every table."""


class Workspace(Base):
    """A named owner profile scoping resumes, jobs and tracker applications.

    A workspace is a *profile* ("Tom", "Lior — Hebrew"), and ``workspace_id``
    is the only scope predicate the seven document tables carry. ``tenant_ref``
    groups the profiles that belong to one identity, so the multi-profile
    feature survives per tenant: tenant → workspaces is one-to-many.

    ``tenant_ref = ""`` is the standalone tenant — what every row carries under
    ``TENANT_MODE=single``, and what ``CLAIM_TENANT_REF`` transfers to the
    operator's real tenant when the instance is flipped to ``header`` mode. It
    is NOT NULL with an empty-string sentinel on purpose:
    ``ux_workspaces_tenant_default`` enforces one default per tenant, and
    SQLite treats NULLs as distinct, so a nullable column would silently lose
    that guarantee.

    ``is_anonymous`` marks a workspace the hourly purge may delete once
    ``last_seen_at`` is older than ``ANONYMOUS_RETENTION_HOURS``. An admin's
    workspaces are never purged.
    """

    __tablename__ = "workspaces"

    workspace_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    slug: Mapped[str] = mapped_column(String)
    content_language: Mapped[str] = mapped_column(String, default="en")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    tenant_ref: Mapped[str] = mapped_column(String, default="", server_default="")
    is_anonymous: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("0")
    )
    last_seen_at: Mapped[str] = mapped_column(String, default=_utcnow_iso)
    created_at: Mapped[str] = mapped_column(String, default=_utcnow_iso)
    updated_at: Mapped[str] = mapped_column(String, default=_utcnow_iso)

    __table_args__ = (
        # Slugs are unique *within a tenant*, not across the table. A global
        # namespace leaked profile names between tenants: creating "Lior" and
        # being handed ``lior-2`` told you somebody else already had ``lior``.
        Index("ux_workspaces_tenant_slug", "tenant_ref", "slug", unique=True),
        Index(
            "ux_workspaces_tenant_default",
            "tenant_ref",
            "is_default",
            unique=True,
            sqlite_where=text("is_default = 1"),
        ),
        Index("ix_workspaces_tenant", "tenant_ref"),
    )


class Resume(Base):
    """A resume document (master or tailored)."""

    __tablename__ = "resumes"

    resume_id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String, default="")
    content: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(String, default="md")
    filename: Mapped[str | None] = mapped_column(String, nullable=True)
    is_master: Mapped[bool] = mapped_column(Boolean, default=False)
    parent_id: Mapped[str | None] = mapped_column(String, nullable=True)
    processed_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    processing_status: Mapped[str] = mapped_column(String, default="pending")
    processing_token: Mapped[str | None] = mapped_column(String, nullable=True)
    cover_letter: Mapped[str | None] = mapped_column(Text, nullable=True)
    outreach_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    interview_prep: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    # original_markdown has *absence* semantics in the TinyDB era: the key was
    # omitted entirely when None. The facade reproduces that by only emitting
    # the key when this column is non-null.
    original_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Newest row in ``resume_versions`` for this resume. Denormalised so the
    # hot read path never has to sort the history.
    head_version_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # Hand-edited LaTeX. NULL means "generate from the document"; once set,
    # the .tex endpoints serve this verbatim and the document stops driving
    # the LaTeX output until the user clears it.
    tex_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The resume's own template and formatting choice (camelCase JSON, the
    # frontend's TemplateSettings). NULL means the user has not chosen for
    # this resume yet, so the client falls back to its last-used settings.
    # Deliberately outside resume_versions: presentation is not content, and
    # restoring an older document must not revert how the resume looks.
    template_settings: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=_utcnow_iso)
    updated_at: Mapped[str] = mapped_column(String, default=_utcnow_iso)

    __table_args__ = (
        # At most one master resume *per workspace*. Partial unique index
        # enforces the invariant at the storage layer; the facade serializes
        # compound designation changes with a SQLite writer transaction.
        Index(
            "ux_resumes_workspace_master",
            "workspace_id",
            "is_master",
            unique=True,
            sqlite_where=text("is_master = 1"),
        ),
        Index("ix_resumes_workspace", "workspace_id"),
    )


class ResumeVersion(Base):
    """One immutable snapshot of a resume's content.

    Append-only: a restore writes a *new* row whose ``document`` is the
    restored one, so history is never rewound. Rows are content-hash deduped
    and consecutive builder autosaves coalesce (see
    ``Database.commit_resume_version``).
    """

    __tablename__ = "resume_versions"
    __table_args__ = (
        Index("ix_versions_resume_created", "resume_id", "created_at"),
        Index("ix_versions_workspace", "workspace_id"),
    )

    version_id: Mapped[str] = mapped_column(String, primary_key=True)
    resume_id: Mapped[str] = mapped_column(String)
    workspace_id: Mapped[str] = mapped_column(String)
    parent_version_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # sha256 of the canonical JSON of ``document``.
    content_hash: Mapped[str] = mapped_column(String)
    document: Mapped[dict[str, Any]] = mapped_column(JSON)
    tex_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    tex_source_mode: Mapped[str] = mapped_column(String, default="generated")
    label: Mapped[str | None] = mapped_column(String, nullable=True)
    origin: Mapped[str] = mapped_column(String)
    origin_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[str] = mapped_column(String, default=_utcnow_iso)


class Job(Base):
    """A job description.

    Only the stable columns are first-class; everything the pipeline attaches
    dynamically (``job_keywords``, ``job_keywords_hash``, ``preview_hash``,
    ``preview_hashes``, ``preview_prompt_id``, ``company``, ``role``) lives in
    ``metadata_json``. The facade flattens that map to top-level keys on read
    and merges non-core keys into it on update, reproducing TinyDB semantics.
    """

    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_workspace", "workspace_id"),)

    job_id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String, default="")
    content: Mapped[str] = mapped_column(Text)
    resume_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=_utcnow_iso)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Improvement(Base):
    """A tailoring result linking an original resume, a tailored resume, and a job."""

    __tablename__ = "improvements"
    __table_args__ = (Index("ix_improvements_workspace", "workspace_id"),)

    request_id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String, default="")
    original_resume_id: Mapped[str] = mapped_column(String)
    tailored_resume_id: Mapped[str] = mapped_column(String, index=True)
    job_id: Mapped[str] = mapped_column(String)
    improvements: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[str] = mapped_column(String, default=_utcnow_iso)


class TailoringPreview(Base):
    """An accepted preview, bounded confirmation claim and immutable result."""

    __tablename__ = "tailoring_previews"
    __table_args__ = (
        Index("ix_preview_compatibility", "source_id", "job_id", "payload_hash", "created_at"),
        Index("ix_previews_workspace", "workspace_id"),
    )

    improvements: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)

    preview_id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String, default="")
    source_id: Mapped[str] = mapped_column(String, index=True)
    job_id: Mapped[str] = mapped_column(String, index=True)
    payload_hash: Mapped[str] = mapped_column(String)
    source_hash: Mapped[str] = mapped_column(String)
    job_hash: Mapped[str] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String)
    expires_at: Mapped[str] = mapped_column(String, index=True)
    result_resume_id: Mapped[str | None] = mapped_column(
        String, nullable=True, index=True
    )
    claim_token: Mapped[str | None] = mapped_column(String, nullable=True)
    claim_expires_at: Mapped[str | None] = mapped_column(String, nullable=True)
    response_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class Application(Base):
    """A Kanban application-tracker card."""

    __tablename__ = "applications"
    __table_args__ = (
        # Concurrency-safe dedupe: a card is unique per (job, applied resume).
        # The app-level select-then-insert relies on this to collapse races.
        UniqueConstraint("job_id", "resume_id", name="uq_application_job_resume"),
        Index("ix_applications_workspace", "workspace_id"),
    )

    application_id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String, default="")
    job_id: Mapped[str] = mapped_column(String, index=True)
    # The applied/tailored resume shown in the modal and opened by "Edit".
    resume_id: Mapped[str] = mapped_column(String, index=True)
    # Optional base resume the tailored one descends from (powers "stack" grouping).
    master_resume_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="applied", index=True)
    company: Mapped[str | None] = mapped_column(String, nullable=True)
    role: Mapped[str | None] = mapped_column(String, nullable=True)
    applied_at: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String, default=_utcnow_iso)
    updated_at: Mapped[str] = mapped_column(String, default=_utcnow_iso)


class ApiKey(Base):
    """One workspace's encrypted LLM provider API key.

    ``provider`` is the *key-store* provider name (e.g. ``google`` for the
    ``gemini`` LLM provider, via ``_PROVIDER_KEY_MAP``). Only ciphertext is
    stored; plaintext exists in memory only at call time.

    The primary key is ``(workspace_id, provider)``: every tenant brings its
    own keys, and an anonymous visitor with none gets "no API key configured"
    rather than the operator's ``LLM_API_KEY`` (see ``llm.resolve_api_key``).
    """

    __tablename__ = "api_keys"

    workspace_id: Mapped[str] = mapped_column(String, primary_key=True)
    provider: Mapped[str] = mapped_column(String, primary_key=True)
    ciphertext: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[str] = mapped_column(String, default=_utcnow_iso)


class WorkspaceSetting(Base):
    """One workspace's override of an instance-wide ``config.json`` key.

    Only the keys a tenant may own are ever written here (``llm``,
    ``features``, ``language``, ``content_language``, ``prompts``,
    ``feature_prompts``). An absent row means "use the instance default", so
    an empty table is exactly right for a fresh tenant.
    """

    __tablename__ = "workspace_settings"

    workspace_id: Mapped[str] = mapped_column(String, primary_key=True)
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[Any] = mapped_column(JSON, default=dict)
    updated_at: Mapped[str] = mapped_column(String, default=_utcnow_iso)
