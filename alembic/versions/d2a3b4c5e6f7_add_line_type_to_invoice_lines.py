"""add line_type to invoice lines

Revision ID: d2a3b4c5e6f7
Revises: c91d8ab4e2f1
Create Date: 2026-02-12
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d2a3b4c5e6f7"
down_revision: Union[str, None] = "c91d8ab4e2f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "inv_invoice_lines",
        sa.Column(
            "line_type",
            sa.String(length=10),
            nullable=False,
            server_default="item",
        ),
    )


def downgrade() -> None:
    op.drop_column("inv_invoice_lines", "line_type")
