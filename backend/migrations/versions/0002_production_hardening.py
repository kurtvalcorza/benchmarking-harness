"""production hardening entities and identity

Adds ArtifactReceipt, JobIntent/JobAttempt, coverage/evaluator/evidence-digest
fields, and audit identity columns; backfills legacy identity (data-model.md
migration steps 2-4). New NOT NULL identity uses a server default so existing
Feature 001 rows backfill to the legacy principal.

Revision ID: 0002_production_hardening
Revises: 0001_feature_001_baseline
Create Date: 2026-07-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_production_hardening"
down_revision: str | None = "0001_feature_001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_PRINCIPAL = "legacy:feature-001"


def upgrade() -> None:
    # ---- new persisted entities ----
    op.create_table(
        "artifactreceipt",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("storage_ref", sa.String(), nullable=False),
        sa.Column("original_filename", sa.String(), nullable=False),
        sa.Column("byte_count", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("framework", sa.String(), nullable=False),
        sa.Column("submitted_by", sa.String(), nullable=False),
        sa.Column("finalized_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("storage_ref"),
    )
    op.create_index("ix_artifactreceipt_sha256", "artifactreceipt", ["sha256"])

    op.create_table(
        "jobintent",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column(
            "model_version_id", sa.String(), sa.ForeignKey("modelversion.id"), nullable=False
        ),
        sa.Column(
            "golden_set_id", sa.String(), sa.ForeignKey("goldentestset.id"), nullable=True
        ),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("lease_owner", sa.String(), nullable=True),
        sa.Column("leased_until", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("dispatched_at", sa.DateTime(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_jobintent_model_version_id", "jobintent", ["model_version_id"])
    op.create_index("ix_jobintent_idempotency_key", "jobintent", ["idempotency_key"])
    op.create_index("ix_jobintent_state", "jobintent", ["state"])

    op.create_table(
        "jobattempt",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("job_intent_id", sa.String(), sa.ForeignKey("jobintent.id"), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(), nullable=False),
        sa.Column("transport_job_id", sa.String(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("outcome", sa.String(), nullable=True),
        sa.Column("run_id", sa.String(), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.UniqueConstraint("job_intent_id", "attempt_number"),
    )
    op.create_index("ix_jobattempt_job_intent_id", "jobattempt", ["job_intent_id"])

    # ---- identity + integrity columns on existing tables ----
    with op.batch_alter_table("modelversion") as batch:
        batch.add_column(
            sa.Column(
                "submitted_by",
                sa.String(),
                nullable=False,
                server_default=LEGACY_PRINCIPAL,
            )
        )
        batch.add_column(sa.Column("artifact_receipt_id", sa.String(), nullable=True))
        batch.create_foreign_key(
            "fk_modelversion_artifact_receipt",
            "artifactreceipt",
            ["artifact_receipt_id"],
            ["id"],
        )
    op.create_index("ix_modelversion_submitted_by", "modelversion", ["submitted_by"])

    with op.batch_alter_table("goldentestset") as batch:
        batch.add_column(
            sa.Column(
                "registered_by",
                sa.String(),
                nullable=False,
                server_default=LEGACY_PRINCIPAL,
            )
        )
    op.create_index("ix_goldentestset_registered_by", "goldentestset", ["registered_by"])

    with op.batch_alter_table("tierresult") as batch:
        batch.add_column(sa.Column("coverage", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("evaluator", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("evidence_digest", sa.String(), nullable=True))

    with op.batch_alter_table("adjudicationrecord") as batch:
        batch.add_column(sa.Column("reviewer_display", sa.String(), nullable=True))

    with op.batch_alter_table("auditevent") as batch:
        batch.add_column(sa.Column("request_id", sa.String(), nullable=True))
        batch.add_column(sa.Column("principal_issuer", sa.String(), nullable=True))
        batch.add_column(sa.Column("outcome", sa.String(), nullable=True))
        batch.add_column(sa.Column("audit_metadata", sa.JSON(), nullable=True))

    # step 4: existing rows are backfilled by the server_default above; drop it so
    # new inserts must carry an explicit authenticated principal.
    with op.batch_alter_table("modelversion") as batch:
        batch.alter_column("submitted_by", server_default=None)
    with op.batch_alter_table("goldentestset") as batch:
        batch.alter_column("registered_by", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("auditevent") as batch:
        for col in ("audit_metadata", "outcome", "principal_issuer", "request_id"):
            batch.drop_column(col)
    with op.batch_alter_table("adjudicationrecord") as batch:
        batch.drop_column("reviewer_display")
    with op.batch_alter_table("tierresult") as batch:
        for col in ("evidence_digest", "evaluator", "coverage"):
            batch.drop_column(col)
    op.drop_index("ix_goldentestset_registered_by", "goldentestset")
    with op.batch_alter_table("goldentestset") as batch:
        batch.drop_column("registered_by")
    op.drop_index("ix_modelversion_submitted_by", "modelversion")
    with op.batch_alter_table("modelversion") as batch:
        batch.drop_constraint("fk_modelversion_artifact_receipt", type_="foreignkey")
        batch.drop_column("artifact_receipt_id")
        batch.drop_column("submitted_by")
    op.drop_table("jobattempt")
    op.drop_table("jobintent")
    op.drop_table("artifactreceipt")
