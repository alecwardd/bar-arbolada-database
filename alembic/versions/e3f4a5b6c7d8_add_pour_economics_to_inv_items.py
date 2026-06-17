"""add pour economics to inv_items

Revision ID: e3f4a5b6c7d8
Revises: d2a3b4c5e6f7
Create Date: 2026-02-19

Adds 4 new columns to inv_items:
  - purchase_unit   how the vendor ships it (case, keg, bottle, etc.)
  - current_qty     physical qty on hand (supports partial bottles: 0.5, 36.5)
  - standard_pour_oz  serving size in oz (1.5 spirits, 5.0 wine, 16.0 draft)
  - menu_price      what you charge per pour/serving

Derived metrics (pours_per_unit, cost_per_pour, pour_cost_pct, revenue_per_unit)
are calculated in the query layer rather than stored, to avoid stale data.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e3f4a5b6c7d8"
down_revision: Union[str, None] = "d2a3b4c5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "inv_items",
        sa.Column("purchase_unit", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "inv_items",
        sa.Column("current_qty", sa.Numeric(precision=10, scale=2), nullable=True),
    )
    op.add_column(
        "inv_items",
        sa.Column("standard_pour_oz", sa.Numeric(precision=5, scale=2), nullable=True),
    )
    op.add_column(
        "inv_items",
        sa.Column("menu_price", sa.Numeric(precision=10, scale=2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("inv_items", "menu_price")
    op.drop_column("inv_items", "standard_pour_oz")
    op.drop_column("inv_items", "current_qty")
    op.drop_column("inv_items", "purchase_unit")
