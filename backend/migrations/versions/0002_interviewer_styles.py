"""store interviewer style preferences and topic indexes"""

from alembic import op
import sqlalchemy as sa


revision = "0002_interviewer_styles"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable columns keep historical sessions and in-progress runs usable;
    # runtime code resolves missing style data to the default snapshot.
    op.add_column(
        "anonymous_sessions",
        sa.Column("preferred_interviewer_style_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "interview_runs",
        sa.Column("interviewer_style_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "interview_turns",
        sa.Column("plan_topic_index", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("interview_turns", "plan_topic_index")
    op.drop_column("interview_runs", "interviewer_style_json")
    op.drop_column("anonymous_sessions", "preferred_interviewer_style_json")
