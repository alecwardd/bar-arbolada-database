"""
Generate a reorder report grouped by vendor with order deadlines.

Usage:
    python scripts/reorder_report.py
    python scripts/reorder_report.py --threshold 2  (show items with qty <= 2)
"""

import sys
import argparse
from pathlib import Path
from datetime import date
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import get_session
from sqlalchemy import text

WEEKDAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']

def days_until(target_day_name, from_date=None):
    """Days from from_date until the next occurrence of target_day_name."""
    if not target_day_name:
        return None
    from_date = from_date or date.today()
    today_idx = from_date.weekday()
    try:
        target_idx = WEEKDAYS.index(target_day_name.lower())
    except ValueError:
        return None
    diff = (target_idx - today_idx) % 7
    return diff if diff > 0 else 7


def run_report(threshold=None):
    session = get_session()

    rows = session.execute(text("""
        SELECT i.id, i.name, i.category, i.subcategory, i.current_qty,
               i.unit_cost, i.menu_price, i.inventory_tier, i.bottle_size_ml,
               i.par_level, i.reorder_point,
               v.id as vendor_id, v.name as vendor_name,
               v.order_deadline_day, v.delivery_days, v.lead_time_days
        FROM inv_items i
        LEFT JOIN inv_vendors v ON i.primary_vendor_id = v.id
        WHERE i.status = 'active'
        ORDER BY v.name NULLS LAST, i.category, i.subcategory, i.name
    """)).fetchall()

    today = date.today()
    day_name = WEEKDAYS[today.weekday()]

    print(f"=== REORDER REPORT  ({today.strftime('%A %b %d, %Y')}) ===\n")

    by_vendor = defaultdict(list)
    no_vendor = []

    for r in rows:
        qty = float(r.current_qty) if r.current_qty is not None else 0

        if threshold is not None and qty > threshold:
            continue

        item_data = {
            "id": r.id,
            "name": r.name,
            "category": f"{r.category}/{r.subcategory}",
            "qty": qty,
            "cost": float(r.unit_cost) if r.unit_cost else 0,
            "price": float(r.menu_price) if r.menu_price else 0,
            "tier": r.inventory_tier,
            "par": float(r.par_level) if r.par_level else None,
        }

        if r.vendor_name:
            vendor_key = (r.vendor_id, r.vendor_name, r.order_deadline_day, r.delivery_days)
            by_vendor[vendor_key].append(item_data)
        else:
            no_vendor.append(item_data)

    for (vid, vname, deadline, delivery), items in sorted(by_vendor.items(), key=lambda x: x[0][0]):
        days_left = days_until(deadline) if deadline else None
        urgency = ""
        if days_left is not None:
            if days_left <= 1:
                urgency = " *** ORDER TODAY ***"
            elif days_left <= 2:
                urgency = " ** ORDER TOMORROW **"

        print(f"--- {vname} ---")
        print(f"    Order by: {deadline or '?'}{urgency}")
        print(f"    Delivery: {delivery or '?'}")

        if not items:
            print("    (no items below threshold)")
        else:
            total_cost = 0
            for it in sorted(items, key=lambda x: x["qty"]):
                par_info = f"  par={it['par']:.0f}" if it['par'] else ""
                print(f"    [{it['id']:>3}] {it['name']:<28} qty={it['qty']:<6.1f} ${it['cost']:<8.2f} tier={it['tier']}{par_info}")
                total_cost += it["cost"]
        print()

    if no_vendor:
        print("--- NO VENDOR ASSIGNED ---")
        for it in sorted(no_vendor, key=lambda x: x["qty"]):
            print(f"    [{it['id']:>3}] {it['name']:<28} qty={it['qty']:<6.1f} ${it['cost']:<8.2f} tier={it['tier']}")
        print()

    # Low stock summary
    all_items = [item for items in by_vendor.values() for item in items] + no_vendor
    critical = [i for i in all_items if i["qty"] <= 0.5]
    low = [i for i in all_items if 0.5 < i["qty"] <= 1.5]

    if critical or low:
        print("=" * 60)
        print("PRIORITY SUMMARY")
        if critical:
            print(f"\n  CRITICAL (qty <= 0.5): {len(critical)} items")
            for it in critical:
                print(f"    {it['name']:<28} qty={it['qty']:.1f}")
        if low:
            print(f"\n  LOW (qty 0.5-1.5): {len(low)} items")
            for it in low:
                print(f"    {it['name']:<28} qty={it['qty']:.1f}")

    session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold", "-t", type=float, default=None,
                        help="Only show items with qty <= threshold")
    args = parser.parse_args()
    run_report(args.threshold)
