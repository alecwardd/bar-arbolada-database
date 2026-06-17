"""add import run snapshots table

Revision ID: c6d7e8f9a0b1
Revises: b4c5d6e7f8a9
Create Date: 2026-03-30
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c6d7e8f9a0b1"
down_revision: Union[str, None] = "b4c5d6e7f8a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "import_run_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("staging_root", sa.String(length=500), nullable=True),
        sa.Column("run_staging_dir", sa.String(length=500), nullable=True),
        sa.Column("messages_fetched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("csv_attachments_saved", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lookback_days", sa.Integer(), nullable=False, server_default="7"),
        sa.Column("coverage_max_dates_json", sa.Text(), nullable=True),
        sa.Column("missing_report_days_json", sa.Text(), nullable=True),
        sa.Column("generated_on", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_import_run_snapshots_created_at",
        "import_run_snapshots",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_import_run_snapshots_created_at", table_name="import_run_snapshots")
    op.drop_table("import_run_snapshots")
