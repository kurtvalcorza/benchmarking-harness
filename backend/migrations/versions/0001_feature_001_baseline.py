"""feature 001 baseline

Declarative baseline matching the schema Feature 001 created via
`SQLModel.metadata.create_all` (data-model.md migration step 1). Enum-typed
columns are stored as their string values (str+Enum), so they are plain string
columns here.

Revision ID: 0001_feature_001_baseline
Revises:
Create Date: 2026-07-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_feature_001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("model_class", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("name", "model_class"),
    )
    op.create_index("ix_model_name", "model", ["name"])

    op.create_table(
        "goldentestset",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("domain", sa.String(), nullable=False),
        sa.Column("model_class", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("manifest_ref", sa.String(), nullable=False),
        sa.Column("checksum", sa.String(), nullable=False),
        sa.Column("conditions", sa.JSON(), nullable=False),
        sa.Column("safety_critical_classes", sa.JSON(), nullable=False),
        sa.Column("recall_floors", sa.JSON(), nullable=False),
        sa.Column("label_map", sa.JSON(), nullable=False),
        sa.Column("license", sa.String(), nullable=False),
        sa.Column("is_public", sa.Boolean(), nullable=False),
        sa.Column("data_ref", sa.String(), nullable=False),
        sa.Column("registered_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("name", "version"),
    )

    op.create_table(
        "modelversion",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("model_id", sa.String(), sa.ForeignKey("model.id"), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("artifact_ref", sa.String(), nullable=False),
        sa.Column("framework", sa.String(), nullable=False),
        sa.Column("declared_sources", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("model_id", "version"),
    )
    op.create_index("ix_modelversion_model_id", "modelversion", ["model_id"])

    op.create_table(
        "evaluationrun",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "model_version_id", sa.String(), sa.ForeignKey("modelversion.id"), nullable=False
        ),
        sa.Column("harness_version", sa.String(), nullable=False),
        sa.Column("golden_set_id", sa.String(), nullable=True),
        sa.Column("golden_set_version", sa.String(), nullable=True),
        sa.Column("golden_set_checksum", sa.String(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("verdict", sa.String(), nullable=True),
        sa.Column("infra_ok", sa.Boolean(), nullable=False),
        sa.Column("flag_trigger", sa.String(), nullable=True),
    )
    op.create_index("ix_evaluationrun_model_version_id", "evaluationrun", ["model_version_id"])

    op.create_table(
        "reevaluationclaim",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "model_version_id", sa.String(), sa.ForeignKey("modelversion.id"), nullable=False
        ),
        sa.Column(
            "golden_set_id", sa.String(), sa.ForeignKey("goldentestset.id"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("model_version_id", "golden_set_id"),
    )
    op.create_index(
        "ix_reevaluationclaim_model_version_id", "reevaluationclaim", ["model_version_id"]
    )
    op.create_index("ix_reevaluationclaim_golden_set_id", "reevaluationclaim", ["golden_set_id"])

    op.create_table(
        "tierresult",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("run_id", sa.String(), sa.ForeignKey("evaluationrun.id"), nullable=False),
        sa.Column("tier", sa.String(), nullable=False),
        sa.Column("condition", sa.String(), nullable=True),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("threshold", sa.JSON(), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=True),
        sa.Column("evidence_ref", sa.String(), nullable=False),
        sa.Column("dataset_checksum", sa.String(), nullable=False),
    )
    op.create_index("ix_tierresult_run_id", "tierresult", ["run_id"])

    op.create_table(
        "modelcard",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "model_version_id", sa.String(), sa.ForeignKey("modelversion.id"), nullable=False
        ),
        sa.Column("human_sections", sa.String(), nullable=False),
        sa.Column("machine_blocks", sa.String(), nullable=False),
        sa.Column("missing_fields", sa.JSON(), nullable=False),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_modelcard_model_version_id", "modelcard", ["model_version_id"])

    op.create_table(
        "adjudicationrecord",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("run_id", sa.String(), sa.ForeignKey("evaluationrun.id"), nullable=False),
        sa.Column("trigger", sa.String(), nullable=False),
        sa.Column("evidence_ref", sa.String(), nullable=False),
        sa.Column("reviewer", sa.String(), nullable=False),
        sa.Column("decision", sa.String(), nullable=False),
        sa.Column("rationale", sa.String(), nullable=False),
        sa.Column("decided_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("run_id"),
    )
    op.create_index("ix_adjudicationrecord_run_id", "adjudicationrecord", ["run_id"])

    op.create_table(
        "auditevent",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("actor", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("target_ref", sa.String(), nullable=False),
        sa.Column("checksum", sa.String(), nullable=True),
        sa.Column("at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    for table in (
        "auditevent",
        "adjudicationrecord",
        "modelcard",
        "tierresult",
        "reevaluationclaim",
        "evaluationrun",
        "modelversion",
        "goldentestset",
        "model",
    ):
        op.drop_table(table)
