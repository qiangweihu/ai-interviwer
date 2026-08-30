"""add structured practical tasks and final submissions"""
from alembic import op
import sqlalchemy as sa


revision = "0003_practical_tasks"
down_revision = "0002_interviewer_styles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("interview_turns", sa.Column("turn_kind", sa.String(length=32), nullable=False, server_default="oral"))
    op.add_column("interview_turns", sa.Column("task_id", sa.String(length=128), nullable=True))
    op.add_column("interview_turns", sa.Column("metadata_json", sa.Text(), nullable=True))
    op.create_index("ix_interview_turns_task_id", "interview_turns", ["task_id"])
    op.create_table(
        "practical_submissions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=128), nullable=False),
        sa.Column("turn_sequence", sa.Integer(), nullable=False),
        sa.Column("task_type", sa.String(length=32), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("is_final", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["interview_runs.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_practical_submissions_run_id", "practical_submissions", ["run_id"])
    op.create_index("ix_practical_submissions_task_id", "practical_submissions", ["task_id"])
    op.create_index("ix_practical_submissions_request_id", "practical_submissions", ["request_id"])
    op.create_index(
        "uq_practical_submission_run_request",
        "practical_submissions",
        ["run_id", "request_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_practical_submission_run_request", table_name="practical_submissions")
    op.drop_index("ix_practical_submissions_request_id", table_name="practical_submissions")
    op.drop_index("ix_practical_submissions_task_id", table_name="practical_submissions")
    op.drop_index("ix_practical_submissions_run_id", table_name="practical_submissions")
    op.drop_table("practical_submissions")
    op.drop_index("ix_interview_turns_task_id", table_name="interview_turns")
    op.drop_column("interview_turns", "metadata_json")
    op.drop_column("interview_turns", "task_id")
    op.drop_column("interview_turns", "turn_kind")
