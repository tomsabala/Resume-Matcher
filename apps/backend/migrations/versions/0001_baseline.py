"""Baseline schema.

Reproduces exactly what ``Base.metadata.create_all`` plus the three legacy
idempotent ``ALTER TABLE`` patches produced before Alembic existed, so a
pre-Alembic ``data/resume_matcher.db`` can be stamped at this revision
(see ``app.db_engine.init_models_sync``) instead of rebuilt.

Revision ID: 0001_baseline
Revises:
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '0001_baseline'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('api_keys',
    sa.Column('provider', sa.String(), nullable=False),
    sa.Column('ciphertext', sa.Text(), nullable=False),
    sa.Column('updated_at', sa.String(), nullable=False),
    sa.PrimaryKeyConstraint('provider')
    )
    op.create_table('applications',
    sa.Column('application_id', sa.String(), nullable=False),
    sa.Column('job_id', sa.String(), nullable=False),
    sa.Column('resume_id', sa.String(), nullable=False),
    sa.Column('master_resume_id', sa.String(), nullable=True),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('company', sa.String(), nullable=True),
    sa.Column('role', sa.String(), nullable=True),
    sa.Column('applied_at', sa.String(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.String(), nullable=False),
    sa.Column('updated_at', sa.String(), nullable=False),
    sa.PrimaryKeyConstraint('application_id'),
    sa.UniqueConstraint('job_id', 'resume_id', name='uq_application_job_resume')
    )
    with op.batch_alter_table('applications', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_applications_job_id'), ['job_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_applications_resume_id'), ['resume_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_applications_status'), ['status'], unique=False)

    op.create_table('improvements',
    sa.Column('request_id', sa.String(), nullable=False),
    sa.Column('original_resume_id', sa.String(), nullable=False),
    sa.Column('tailored_resume_id', sa.String(), nullable=False),
    sa.Column('job_id', sa.String(), nullable=False),
    sa.Column('improvements', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.String(), nullable=False),
    sa.PrimaryKeyConstraint('request_id')
    )
    with op.batch_alter_table('improvements', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_improvements_tailored_resume_id'), ['tailored_resume_id'], unique=False)

    op.create_table('jobs',
    sa.Column('job_id', sa.String(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('resume_id', sa.String(), nullable=True),
    sa.Column('created_at', sa.String(), nullable=False),
    sa.Column('metadata_json', sa.JSON(), nullable=False),
    sa.PrimaryKeyConstraint('job_id')
    )
    op.create_table('resumes',
    sa.Column('resume_id', sa.String(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('content_type', sa.String(), nullable=False),
    sa.Column('filename', sa.String(), nullable=True),
    sa.Column('is_master', sa.Boolean(), nullable=False),
    sa.Column('parent_id', sa.String(), nullable=True),
    sa.Column('processed_data', sa.JSON(), nullable=True),
    sa.Column('processing_status', sa.String(), nullable=False),
    sa.Column('processing_token', sa.String(), nullable=True),
    sa.Column('cover_letter', sa.Text(), nullable=True),
    sa.Column('outreach_message', sa.Text(), nullable=True),
    sa.Column('interview_prep', sa.Text(), nullable=True),
    sa.Column('title', sa.String(), nullable=True),
    sa.Column('original_markdown', sa.Text(), nullable=True),
    sa.Column('created_at', sa.String(), nullable=False),
    sa.Column('updated_at', sa.String(), nullable=False),
    sa.PrimaryKeyConstraint('resume_id')
    )
    with op.batch_alter_table('resumes', schema=None) as batch_op:
        batch_op.create_index('ux_resumes_single_master', ['is_master'], unique=True, sqlite_where=sa.text('is_master = 1'))

    op.create_table('tailoring_previews',
    sa.Column('improvements', sa.JSON(), nullable=True),
    sa.Column('preview_id', sa.String(), nullable=False),
    sa.Column('source_id', sa.String(), nullable=False),
    sa.Column('job_id', sa.String(), nullable=False),
    sa.Column('payload_hash', sa.String(), nullable=False),
    sa.Column('source_hash', sa.String(), nullable=False),
    sa.Column('job_hash', sa.String(), nullable=False),
    sa.Column('created_at', sa.String(), nullable=False),
    sa.Column('expires_at', sa.String(), nullable=False),
    sa.Column('result_resume_id', sa.String(), nullable=True),
    sa.Column('claim_token', sa.String(), nullable=True),
    sa.Column('claim_expires_at', sa.String(), nullable=True),
    sa.Column('response_data', sa.JSON(), nullable=True),
    sa.PrimaryKeyConstraint('preview_id')
    )
    with op.batch_alter_table('tailoring_previews', schema=None) as batch_op:
        batch_op.create_index('ix_preview_compatibility', ['source_id', 'job_id', 'payload_hash', 'created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_tailoring_previews_expires_at'), ['expires_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_tailoring_previews_job_id'), ['job_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_tailoring_previews_result_resume_id'), ['result_resume_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_tailoring_previews_source_id'), ['source_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('tailoring_previews', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_tailoring_previews_source_id'))
        batch_op.drop_index(batch_op.f('ix_tailoring_previews_result_resume_id'))
        batch_op.drop_index(batch_op.f('ix_tailoring_previews_job_id'))
        batch_op.drop_index(batch_op.f('ix_tailoring_previews_expires_at'))
        batch_op.drop_index('ix_preview_compatibility')

    op.drop_table('tailoring_previews')
    with op.batch_alter_table('resumes', schema=None) as batch_op:
        batch_op.drop_index('ux_resumes_single_master', sqlite_where=sa.text('is_master = 1'))

    op.drop_table('resumes')
    op.drop_table('jobs')
    with op.batch_alter_table('improvements', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_improvements_tailored_resume_id'))

    op.drop_table('improvements')
    with op.batch_alter_table('applications', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_applications_status'))
        batch_op.drop_index(batch_op.f('ix_applications_resume_id'))
        batch_op.drop_index(batch_op.f('ix_applications_job_id'))

    op.drop_table('applications')
    op.drop_table('api_keys')
