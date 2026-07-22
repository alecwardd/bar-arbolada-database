"""
Record a physical inventory count into the database.

Usage:
    python scripts/record_physical_count.py <csv_file>

CSV format (simple two-column):
    item_id,counted_qty
    2,30.5
    123,35
    108,18

Or run interactively:
    python scripts/record_physical_count.py --interactive

Creates an inv_counts header + inv_count_lines for each item, updates
inv_items.current_qty (convenience UI field), and seeds
inv_daily_ledger opening for count_date via set_opening_from_count
(ledger = source of truth — see docs/adr/0001).

Counted qty is treated as **start-of-day opening** for count_date. A later
ledger recompute on that date keeps the count opening (does not wipe it).
"""

import sys
import csv
import argparse
from pathlib import Path
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import get_session
from src.inventory.ledger import set_opening_from_count
from src.models import InvItem, InvCount, InvCountLine
from sqlalchemy import text


def create_count_from_dict(session, counts_dict, counted_by="Owner", notes=None, count_type="full"):
    """
    counts_dict: {inv_item_id: Decimal(counted_qty), ...}
    Returns the InvCount record.
    """
    count = InvCount(
        count_date=date.today(),
        count_type=count_type,
        counted_by=counted_by,
        notes=notes or f"Physical count recorded {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        status="completed",
    )
    session.add(count)
    session.flush()

    updated = 0
    for item_id, qty in counts_dict.items():
        item = session.query(InvItem).filter(InvItem.id == item_id).first()
        if not item:
            print(f"  WARNING: item id={item_id} not found, skipping")
            continue

        old_qty = item.current_qty or Decimal("0")
        variance = qty - old_qty

        line = InvCountLine(
            count_id=count.id,
            inv_item_id=item_id,
            counted_qty=qty,
            unit_of_measure=item.unit_of_measure,
            theoretical_qty=old_qty,
            variance=variance,
            variance_pct=round((variance / old_qty * 100), 2) if old_qty else None,
        )
        session.add(line)

        # Convenience catalog field (non-authoritative).
        item.current_qty = qty
        item.updated_at = datetime.utcnow()

        # Seed ledger opening for this count date (caller owns commit).
        set_opening_from_count(item_id, count.count_date, qty, session=session)

        updated += 1

        direction = "+" if variance > 0 else ""
        print(f"  [{item.id:>3}] {item.name:<28} {float(old_qty):.1f} -> {float(qty):.1f}  ({direction}{float(variance):.1f})")

    session.commit()
    print(f"\nCount #{count.id} saved: {updated} items updated (ledger openings seeded)")
    return count


def load_from_csv(csv_path):
    counts = {}
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            item_id = int(row["item_id"].strip())
            qty = Decimal(row["counted_qty"].strip())
            counts[item_id] = qty
    return counts


def interactive_mode():
    session = get_session()

    rows = session.execute(text("""
        SELECT i.id, i.name, i.category, i.subcategory, i.current_qty
        FROM inv_items i
        WHERE i.status = 'active'
        ORDER BY i.category, i.subcategory, i.name
    """)).fetchall()

    print("=== Interactive Inventory Count ===")
    print("Enter new quantity for each item, or:")
    print("  ENTER = keep current quantity (no change)")
    print("  0     = item is empty")
    print("  s     = skip this category")
    print("  q     = finish and save\n")

    counts = {}
    current_cat = None

    for r in rows:
        label = f"{r.category}/{r.subcategory}".upper()
        if label != current_cat:
            current_cat = label
            print(f"\n--- {label} ---")

        old_qty = float(r.current_qty) if r.current_qty else 0
        prompt = f"  [{r.id:>3}] {r.name:<28} (was {old_qty:.1f}): "

        try:
            raw = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            break

        if raw.lower() == "q":
            break
        if raw.lower() == "s":
            current_cat = None
            continue
        if raw == "":
            continue

        try:
            counts[r.id] = Decimal(raw)
        except InvalidOperation:
            print(f"    Invalid number '{raw}', skipping")

    session.close()

    if not counts:
        print("No counts entered, nothing to save.")
        return

    print(f"\nSaving {len(counts)} counted items...")
    session = get_session()
    create_count_from_dict(session, counts)
    session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Record physical inventory count")
    parser.add_argument("csv_file", nargs="?", help="CSV file with item_id,counted_qty columns")
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive entry mode")
    args = parser.parse_args()

    if args.interactive:
        interactive_mode()
    elif args.csv_file:
        print(f"Loading counts from {args.csv_file}")
        counts = load_from_csv(args.csv_file)
        print(f"Found {len(counts)} items in CSV")
        session = get_session()
        create_count_from_dict(session, counts)
        session.close()
    else:
        parser.print_help()
