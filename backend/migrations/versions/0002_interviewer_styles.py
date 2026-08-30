"""store interviewer style preferences and per-run snapshots"""

from alembic import op
import sqlalchemy as sa


revision = "0002_interviewer_styles"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable keeps the migration safe for historical sessions/runs.  The
    # runtime resolves null values to the versioned default style.
    op.add_column(
        "anonymous_sessions",
        sa.Column("preferred_interviewer_style_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "interview_runs",
        sa.Column("interviewer_style_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("interview_runs", "interviewer_style_json")
    op.drop_column("anonymous_sessions", "preferred_interviewer_style_json")
