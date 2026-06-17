"""add payroll burden settings table

Revision ID: f1a2b3c4d5e6
Revises: e3f4a5b6c7d8
Create Date: 2026-02-19

Stores employer payroll tax rate and flat monthly payroll service fees with
effective date ranges so historical labor cost calculations can remain
accurate as rates change.

The public migration creates the table only. Business-specific payroll burden
defaults are intentionally configured locally and are not included in this
portfolio snapshot.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "e3f4a5b6c7d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payroll_burden_settings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("payroll_tax_rate", sa.Numeric(precision=6, scale=4), nullable=False),
        sa.Column("payroll_fee_monthly", sa.Numeric(precision=10, scale=2), nullable=False, server_default=sa.text("0")),
        sa.Column("effective_start_date", sa.Date(), nullable=False),
        sa.Column("effective_end_date", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_payroll_burden_dates",
        "payroll_burden_settings",
        ["effective_start_date", "effective_end_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_payroll_burden_dates", table_name="payroll_burden_settings")
    op.drop_table("payroll_burden_settings")
