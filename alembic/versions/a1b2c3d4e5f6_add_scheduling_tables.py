"""add scheduling, employee master, availability, events, and demand tables

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2026-02-25

New tables:
  - employees: master employee roster (seeded from pos_labor)
  - employee_availability: weekly availability windows per employee
  - schedule_templates + schedule_template_shifts: reusable shift templates
  - schedule_entries: published schedule (one row per employee per day)
  - external_events: OKC Thunder games, Civic Center shows, etc.
  - scheduling_settings: single-row config for demand engine
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── employees ──────────────────────────────────────────────────────
    op.create_table(
        "employees",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("pos_employee_id", sa.String(length=20), nullable=True),
        sa.Column("first_name", sa.String(length=100), nullable=False),
        sa.Column("last_name", sa.String(length=100), nullable=False),
        sa.Column("primary_role", sa.String(length=100), nullable=True),
        sa.Column("hire_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("max_hours_per_week", sa.Numeric(precision=5, scale=2), nullable=False, server_default="40"),
        sa.Column("min_hours_per_week", sa.Numeric(precision=5, scale=2), nullable=False, server_default="0"),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("email", sa.String(length=200), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pos_employee_id", "first_name", "last_name", name="uq_employee_identity"),
    )
    op.create_index("ix_employees_status", "employees", ["status"], unique=False)

    # ── employee_availability ──────────────────────────────────────────
    op.create_table(
        "employee_availability",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("day_of_week", sa.Integer(), nullable=False),
        sa.Column("available_from", sa.Time(), nullable=True),
        sa.Column("available_until", sa.Time(), nullable=True),
        sa.Column("preference", sa.String(length=20), nullable=False, server_default="available"),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_avail_employee_dow", "employee_availability", ["employee_id", "day_of_week"], unique=False)

    # ── schedule_templates ─────────────────────────────────────────────
    op.create_table(
        "schedule_templates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False, unique=True),
        sa.Column("day_type", sa.String(length=30), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── schedule_template_shifts ───────────────────────────────────────
    op.create_table(
        "schedule_template_shifts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("template_id", sa.Integer(), sa.ForeignKey("schedule_templates.id"), nullable=False),
        sa.Column("role", sa.String(length=100), nullable=False),
        sa.Column("shift_start", sa.Time(), nullable=False),
        sa.Column("shift_end", sa.Time(), nullable=False),
        sa.Column("headcount", sa.Integer(), nullable=False, server_default="1"),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── schedule_entries ───────────────────────────────────────────────
    op.create_table(
        "schedule_entries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("schedule_date", sa.Date(), nullable=False),
        sa.Column("role", sa.String(length=100), nullable=True),
        sa.Column("shift_start", sa.Time(), nullable=False),
        sa.Column("shift_end", sa.Time(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="scheduled"),
        sa.Column("created_by", sa.String(length=200), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("employee_id", "schedule_date", name="uq_schedule_employee_day"),
    )
    op.create_index("ix_schedule_date", "schedule_entries", ["schedule_date"], unique=False)

    # ── external_events ────────────────────────────────────────────────
    op.create_table(
        "external_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("event_time", sa.Time(), nullable=True),
        sa.Column("venue", sa.String(length=50), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("event_name", sa.String(length=300), nullable=False),
        sa.Column("expected_impact", sa.String(length=20), nullable=False, server_default="medium"),
        sa.Column("estimated_attendance", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_date", "venue", "event_name", name="uq_event_date_venue_name"),
    )
    op.create_index("ix_events_date", "external_events", ["event_date"], unique=False)
    op.create_index("ix_events_venue", "external_events", ["venue"], unique=False)

    # ── scheduling_settings (single-row config) ───────────────────────
    op.create_table(
        "scheduling_settings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("target_splh", sa.Numeric(precision=8, scale=2), nullable=False, server_default="55"),
        sa.Column("min_bartenders", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("min_barbacks", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("default_shift_length_hours", sa.Numeric(precision=4, scale=2), nullable=False, server_default="7"),
        sa.Column("bartender_hour_ratio", sa.Numeric(precision=4, scale=2), nullable=False, server_default="0.65"),
        sa.Column("event_multiplier_thunder", sa.Numeric(precision=4, scale=2), nullable=False, server_default="1.80"),
        sa.Column("event_multiplier_concert", sa.Numeric(precision=4, scale=2), nullable=False, server_default="1.50"),
        sa.Column("event_multiplier_show", sa.Numeric(precision=4, scale=2), nullable=False, server_default="1.30"),
        sa.Column("event_multiplier_convention", sa.Numeric(precision=4, scale=2), nullable=False, server_default="1.15"),
        sa.Column("cut_threshold_per_bartender", sa.Numeric(precision=8, scale=2), nullable=False, server_default="100"),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        "INSERT INTO scheduling_settings (id) VALUES (1)"
    )


def downgrade() -> None:
    op.drop_table("scheduling_settings")
    op.drop_index("ix_events_venue", table_name="external_events")
    op.drop_index("ix_events_date", table_name="external_events")
    op.drop_table("external_events")
    op.drop_index("ix_schedule_date", table_name="schedule_entries")
    op.drop_table("schedule_entries")
    op.drop_table("schedule_template_shifts")
    op.drop_table("schedule_templates")
    op.drop_index("ix_avail_employee_dow", table_name="employee_availability")
    op.drop_table("employee_availability")
    op.drop_index("ix_employees_status", table_name="employees")
    op.drop_table("employees")
