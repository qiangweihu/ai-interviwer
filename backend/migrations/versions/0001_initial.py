"""initial interview schema"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "anonymous_sessions",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="needs_onboarding"),
        sa.Column("profile_revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("current_run_id", sa.String(length=64)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_anonymous_sessions_token_hash", "anonymous_sessions", ["token_hash"], unique=True)
    op.create_index("ix_anonymous_sessions_status", "anonymous_sessions", ["status"])
    op.create_index("ix_anonymous_sessions_expires_at", "anonymous_sessions", ["expires_at"])
    op.create_table(
        "profiles",
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("direction", sa.Text(), nullable=False),
        sa.Column("target_group", sa.Text(), nullable=False),
        sa.Column("target_program", sa.Text(), nullable=False),
        sa.Column("research_context_json", sa.Text(), nullable=False),
        sa.Column("candidate_profile_json", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["anonymous_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("session_id"),
    )
    op.create_table(
        "interview_runs",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("profile_revision", sa.Integer(), nullable=False),
        sa.Column("plan_profile_revision", sa.Integer()),
        sa.Column("research_status", sa.String(length=32)),
        sa.Column("plan_json", sa.Text()),
        sa.Column("research_json", sa.Text()),
        sa.Column("feedback_json", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["anonymous_sessions.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_interview_runs_session_id", "interview_runs", ["session_id"])
    op.create_index("ix_interview_runs_status", "interview_runs", ["status"])
    op.create_table(
        "research_sources",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("accessed_at", sa.String(length=32), nullable=False),
        sa.Column("conclusion", sa.Text(), nullable=False),
        sa.Column("relation", sa.Text(), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.ForeignKeyConstraint(["run_id"], ["interview_runs.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_research_sources_run_id", "research_sources", ["run_id"])
    op.create_table(
        "interview_turns",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("topic", sa.Text()),
        sa.Column("request_id", sa.String(length=128)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["interview_runs.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_interview_turns_run_id", "interview_turns", ["run_id"])
    op.create_index("ix_interview_turns_request_id", "interview_turns", ["request_id"])
    op.create_table(
        "observations",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("turn_sequence", sa.Integer()),
        sa.Column("topic", sa.Text()),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("needs_clarification", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.ForeignKeyConstraint(["run_id"], ["interview_runs.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_observations_run_id", "observations", ["run_id"])


def downgrade() -> None:
    op.drop_table("observations")
    op.drop_table("interview_turns")
    op.drop_table("research_sources")
    op.drop_table("interview_runs")
    op.drop_table("profiles")
    op.drop_index("ix_anonymous_sessions_expires_at", table_name="anonymous_sessions")
    op.drop_index("ix_anonymous_sessions_status", table_name="anonymous_sessions")
    op.drop_index("ix_anonymous_sessions_token_hash", table_name="anonymous_sessions")
    op.drop_table("anonymous_sessions")
