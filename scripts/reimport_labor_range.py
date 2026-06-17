"""
Re-import labor reports for a date range: delete existing pos_labor rows
for those trading days, then import the given CSV files.

Usage:
    python scripts/reimport_labor_range.py \\
        --start 2026-05-24 --end 2026-05-30 \\
        raw-csvs-before-pos-changes/labor-report--2026-05-24-to-2026-05-24--example-bar.csv \\
        ...
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import and_

from src.config import get_session
from src.models import ImportLog, PosLabor
from src.importers.base import check_duplicate, file_hash
from src.importers.labor_report import import_labor_report


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Delete and re-import labor CSVs for a date range.")
    p.add_argument("--start", required=True, type=date.fromisoformat, help="First trading day (YYYY-MM-DD)")
    p.add_argument("--end", required=True, type=date.fromisoformat, help="Last trading day (YYYY-MM-DD)")
    p.add_argument(
        "files",
        nargs="+",
        type=Path,
        help="Labor report CSV paths to import after delete",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted/imported without writing",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    files = [f.resolve() for f in args.files]
    for f in files:
        if not f.is_file():
            print(f"[ERROR] Not found: {f}")
            sys.exit(1)

    session = get_session()
    try:
        q = session.query(PosLabor).filter(
            and_(
                PosLabor.trading_day >= args.start,
                PosLabor.trading_day <= args.end,
            )
        )
        count = q.count()
        print(f"Trading days {args.start} .. {args.end}: {count} existing pos_labor row(s)")

        if args.dry_run:
            for f in sorted(files):
                print(f"  would import: {f.name}")
            return

        deleted = q.delete(synchronize_session=False)
        session.commit()
        print(f"Deleted {deleted} row(s)")

        total = 0
        for f in sorted(files):
            print(f"\n[LABOR] {f.name}")
            # Allow re-import when file content is unchanged (same hash as prior import).
            fhash = file_hash(f)
            prior = check_duplicate(session, fhash)
            if prior:
                session.delete(prior)
                session.commit()
                print("  [REIMPORT] Cleared prior import log (identical file hash)")
            n = import_labor_report(session, f)
            total += n

        print(f"\nDone. Imported/updated {total} timecard row(s) from {len(files)} file(s).")

        # Per-day summary
        from src.analytics.queries import _q

        summary = _q(
            """
            SELECT trading_day,
                   COUNT(*) AS shifts,
                   ROUND(SUM(total_pay)::numeric, 2) AS total_pay,
                   ROUND(SUM(reg_hours + COALESCE(ot_hours, 0))::numeric, 2) AS total_hours
            FROM pos_labor
            WHERE trading_day >= :start AND trading_day <= :end
            GROUP BY trading_day
            ORDER BY trading_day
            """,
            {"start": args.start, "end": args.end},
        )
        if summary.empty:
            print("\n[WARN] No labor rows remain in range after import.")
        else:
            print("\nPer-day totals (all pos_labor in range):")
            print(summary.to_string(index=False))
    finally:
        session.close()


if __name__ == "__main__":
    main()
