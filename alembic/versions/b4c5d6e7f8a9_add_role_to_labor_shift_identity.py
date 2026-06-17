"""add role to labor shift identity

Revision ID: b4c5d6e7f8a9
Revises: a1b2c3d4e5f6
Create Date: 2026-03-24

Pre-migration checks:

1. Exact duplicates under the new key (should be empty before creating the index):

   SELECT
       employee_id,
       last_name,
       first_name,
       shift_date,
       shift_start,
       COALESCE(TRIM(role), '') AS normalized_role,
       COUNT(*) AS row_count
   FROM pos_labor
   GROUP BY
       employee_id,
       last_name,
       first_name,
       shift_date,
       shift_start,
       COALESCE(TRIM(role), '')
   HAVING COUNT(*) > 1;

2. Same clock-in recorded under multiple roles (useful for auditing rare POS edge cases):

   SELECT
       employee_id,
       last_name,
       first_name,
       shift_date,
       shift_start,
       COUNT(DISTINCT COALESCE(TRIM(role), '')) AS role_count,
       ARRAY_AGG(DISTINCT COALESCE(TRIM(role), '') ORDER BY COALESCE(TRIM(role), '')) AS roles
   FROM pos_labor
   GROUP BY employee_id, last_name, first_name, shift_date, shift_start
   HAVING COUNT(DISTINCT COALESCE(TRIM(role), '')) > 1;
"""
from typing import Sequence, Union

from alembic import op


revision: str = "b4c5d6e7f8a9"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("uq_labor_shift", "pos_labor", type_="unique")
    op.execute(
        """
        CREATE UNIQUE INDEX uq_labor_shift
        ON pos_labor (
            employee_id,
            last_name,
            first_name,
            shift_date,
            shift_start,
            COALESCE(TRIM(role), '')
        )
        """
    )


def downgrade() -> None:
    op.drop_index("uq_labor_shift", table_name="pos_labor")
    op.create_unique_constraint(
        "uq_labor_shift",
        "pos_labor",
        ["employee_id", "last_name", "first_name", "shift_date", "shift_start"],
    )
