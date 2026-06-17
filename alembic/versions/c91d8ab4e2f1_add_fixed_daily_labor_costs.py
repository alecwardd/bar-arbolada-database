"""add fixed daily labor costs table

Revision ID: c91d8ab4e2f1
Revises: af24cf8c6811
Create Date: 2026-02-11
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c91d8ab4e2f1"
down_revision: Union[str, None] = "af24cf8c6811"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "labor_fixed_daily_costs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("cost_name", sa.String(length=200), nullable=False),
        sa.Column("daily_amount", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("effective_start_date", sa.Date(), nullable=False),
        sa.Column("effective_end_date", sa.Date(), nullable=True),
        sa.Column("include_in_projections", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_labor_fixed_dates",
        "labor_fixed_daily_costs",
        ["effective_start_date", "effective_end_date"],
        unique=False,
    )
    op.create_index(
        "ix_labor_fixed_include",
        "labor_fixed_daily_costs",
        ["include_in_projections"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_labor_fixed_include", table_name="labor_fixed_daily_costs")
    op.drop_index("ix_labor_fixed_dates", table_name="labor_fixed_daily_costs")
    op.drop_table("labor_fixed_daily_costs")
