"""
Run Daily Ledger Calculation
=============================
Computes theoretical inventory for today (or a specified date).

Usage:
    python scripts/run_ledger.py                   # today
    python scripts/run_ledger.py 2026-02-05         # specific date
    python scripts/run_ledger.py 2026-01-01 2026-01-31  # date range
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import date, datetime

from src.inventory.ledger import compute_ledger, compute_ledger_range


def main():
    args = sys.argv[1:]

    if len(args) == 0:
        # Run for today
        target = date.today()
        print(f"Computing ledger for {target}...")
        result = compute_ledger(target)
        print(f"  Items processed: {result['items_processed']}")
        print(f"  Created: {result['created']}")
        print(f"  Updated: {result['updated']}")

    elif len(args) == 1:
        # Run for a specific date
        target = datetime.strptime(args[0], "%Y-%m-%d").date()
        print(f"Computing ledger for {target}...")
        result = compute_ledger(target)
        print(f"  Items processed: {result['items_processed']}")
        print(f"  Created: {result['created']}")
        print(f"  Updated: {result['updated']}")

    elif len(args) == 2:
        # Run for a date range
        start = datetime.strptime(args[0], "%Y-%m-%d").date()
        end = datetime.strptime(args[1], "%Y-%m-%d").date()
        print(f"Computing ledger for {start} to {end}...")
        results = compute_ledger_range(start, end)
        total_created = sum(r["created"] for r in results)
        total_updated = sum(r["updated"] for r in results)
        print(f"  Days processed: {len(results)}")
        print(f"  Total created: {total_created}")
        print(f"  Total updated: {total_updated}")

    else:
        print("Usage:")
        print("  python scripts/run_ledger.py                      # today")
        print("  python scripts/run_ledger.py 2026-02-05            # specific date")
        print("  python scripts/run_ledger.py 2026-01-01 2026-01-31 # date range")
        sys.exit(1)


if __name__ == "__main__":
    main()
