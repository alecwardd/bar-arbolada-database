"""
Seed the employees table from distinct pos_labor records.

Finds every unique (employee_id, first_name, last_name) combination in
pos_labor (trusted imports only) and inserts them into the employees master
table. Skips placeholder profiles (e.g. BAR 2) and blank names.

Assigns primary_role based on the role most frequently worked.
Sets hire_date to the earliest shift_date on record.

Safe to re-run: uses INSERT ... ON CONFLICT DO NOTHING.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from src.config import engine


def seed_employees() -> int:
    """Insert distinct employees from pos_labor into employees table.
    Returns number of rows inserted."""

    sql = text("""
        WITH ranked AS (
            SELECT
                COALESCE(pl.employee_id, '') AS pos_employee_id,
                TRIM(pl.first_name) AS first_name,
                TRIM(pl.last_name) AS last_name,
                pl.role,
                MIN(pl.shift_date) AS earliest_shift,
                COUNT(*) AS shift_count,
                ROW_NUMBER() OVER (
                    PARTITION BY COALESCE(pl.employee_id, ''),
                                 TRIM(pl.first_name),
                                 TRIM(pl.last_name)
                    ORDER BY COUNT(*) DESC
                ) AS rn
            FROM pos_labor pl
            JOIN import_logs il ON il.id = pl.import_log_id
            WHERE il.import_type = 'labor'
              AND il.status = 'success'
              AND NOT (UPPER(TRIM(pl.first_name)) = 'BAR 2'
                       AND UPPER(TRIM(pl.last_name)) = 'BAR 2')
              AND TRIM(COALESCE(pl.first_name, '')) <> ''
              AND TRIM(COALESCE(pl.last_name, '')) <> ''
            GROUP BY COALESCE(pl.employee_id, ''),
                     TRIM(pl.first_name),
                     TRIM(pl.last_name),
                     pl.role
        )
        INSERT INTO employees (pos_employee_id, first_name, last_name,
                               primary_role, hire_date, status)
        SELECT
            pos_employee_id,
            first_name,
            last_name,
            role AS primary_role,
            earliest_shift AS hire_date,
            'active'
        FROM ranked
        WHERE rn = 1
        ON CONFLICT (pos_employee_id, first_name, last_name) DO NOTHING
    """)

    with engine.begin() as conn:
        result = conn.execute(sql)
        return result.rowcount


if __name__ == "__main__":
    count = seed_employees()
    print(f"Seeded {count} employees into employees table.")
