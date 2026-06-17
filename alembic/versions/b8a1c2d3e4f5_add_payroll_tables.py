"""add payroll tables (settings, cash tips, employee settings)

Revision ID: b8a1c2d3e4f5
Revises: 5ef8f58f8b70
Create Date: 2026-02-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b8a1c2d3e4f5"
down_revision: Union[str, None] = "5ef8f58f8b70"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payroll_settings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("kitchen_tipout_pct", sa.Numeric(precision=5, scale=4), nullable=False, server_default="0.05"),
        sa.Column("barback_multiplier", sa.Numeric(precision=4, scale=2), nullable=False, server_default="0.5"),
        sa.Column("food_category_name", sa.String(length=200), nullable=False, server_default=sa.text("'Food'")),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    # Public migration defines the schema only. Configure payroll settings locally.

    op.create_table(
        "payroll_cash_tips",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trading_day", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=10, scale=2), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trading_day", name="uq_payroll_cash_tips_trading_day"),
    )
    op.create_index("ix_payroll_cash_tips_trading_day", "payroll_cash_tips", ["trading_day"], unique=False)

    op.create_table(
        "payroll_employee_settings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("employee_id", sa.String(length=20), nullable=False, server_default=""),
        sa.Column("first_name", sa.String(length=100), nullable=False),
        sa.Column("last_name", sa.String(length=100), nullable=False),
        sa.Column("include_in_tip_pool", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("tip_pool_multiplier", sa.Numeric(precision=4, scale=2), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("employee_id", "first_name", "last_name", name="uq_payroll_employee_identity"),
    )
    op.create_index(
        "ix_payroll_employee_settings_identity",
        "payroll_employee_settings",
        ["employee_id", "first_name", "last_name"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_payroll_employee_settings_identity", table_name="payroll_employee_settings")
    op.drop_table("payroll_employee_settings")
    op.drop_index("ix_payroll_cash_tips_trading_day", table_name="payroll_cash_tips")
    op.drop_table("payroll_cash_tips")
    op.drop_table("payroll_settings")
