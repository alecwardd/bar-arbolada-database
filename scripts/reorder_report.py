"""
Generate a reorder report grouped by vendor with order deadlines.

On-hand quantity comes from ``inv_daily_ledger.closing_qty`` (ledger = source
of truth), the same store dashboards use via ``queries.get_reorder_items``.
``inv_items.current_qty`` is intentionally not used.

Usage:
    python scripts/reorder_report.py
    python scripts/reorder_report.py --threshold 2  (show items with ledger qty <= 2)
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from src.analytics.queries import get_reorder_items
from src.config import get_session

WEEKDAYS = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]


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


def _row_from_mapping(r) -> dict:
    """Normalize a ledger-backed mapping / Series into a print row."""
    qty = r.get("closing_qty")
    par = r.get("par_level")
    cost = r.get("unit_cost")
    return {
        "name": r.get("item_name") or r.get("name"),
        "category": r.get("category"),
        "qty": float(qty) if qty is not None else 0.0,
        "cost": float(cost) if cost is not None else 0.0,
        "tier": r.get("inventory_tier"),
        "par": float(par) if par is not None else None,
        "vendor_name": r.get("vendor_name"),
        "order_deadline_day": r.get("order_deadline_day"),
        "delivery_days": r.get("delivery_days"),
        "lead_time_days": r.get("lead_time_days"),
        "days_of_cover": r.get("days_of_cover"),
    }


def load_ledger_reorder_rows(threshold: float | None = None) -> list[dict]:
    """
    Load reorder candidates from the daily ledger (SoT).

    - No threshold: same set as ``get_reorder_items()`` (latest ledger date,
      ``reorder_alert = TRUE``).
    - With threshold: latest ledger rows whose ``closing_qty <= threshold``
      (still ledger-backed; still ignores ``inv_items.current_qty``).
    """
    if threshold is None:
        df = get_reorder_items()
        if df is None or df.empty:
            return []
        return [_row_from_mapping(row) for _, row in df.iterrows()]

    session = get_session()
    try:
        # Mirror get_reorder_items' ledger join; filter by closing_qty instead of alert.
        result = session.execute(
            text(
                """
                SELECT
                    i.name AS item_name,
                    i.category,
                    i.unit_cost,
                    i.inventory_tier,
                    i.par_level,
                    l.closing_qty,
                    l.days_of_cover,
                    v.name AS vendor_name,
                    v.order_deadline_day,
                    v.delivery_days,
                    v.lead_time_days
                FROM inv_daily_ledger l
                JOIN inv_items i ON l.inv_item_id = i.id
                LEFT JOIN inv_vendors v ON i.primary_vendor_id = v.id
                WHERE l.ledger_date = (SELECT MAX(ledger_date) FROM inv_daily_ledger)
                  AND i.status = 'active'
                  AND l.closing_qty <= :threshold
                ORDER BY v.name NULLS LAST, l.closing_qty ASC NULLS FIRST, i.name
                """
            ),
            {"threshold": threshold},
        )
        return [_row_from_mapping(dict(r)) for r in result.mappings()]
    finally:
        session.close()


def run_report(threshold=None):
    today = date.today()
    print(f"=== REORDER REPORT  ({today.strftime('%A %b %d, %Y')}) ===")
    print("Source: inv_daily_ledger.closing_qty (ledger SoT)\n")

    items = load_ledger_reorder_rows(threshold)

    if not items:
        if threshold is None:
            print("No items flagged for reorder on the latest ledger date.")
            print("(Run the daily ledger, or set reorder points / wait for usage history.)")
        else:
            print(f"No ledger rows with closing_qty <= {threshold} on the latest ledger date.")
        return

    by_vendor = defaultdict(list)
    no_vendor = []

    for it in items:
        if it["vendor_name"]:
            key = (
                it["vendor_name"],
                it.get("order_deadline_day"),
                it.get("delivery_days"),
            )
            by_vendor[key].append(it)
        else:
            no_vendor.append(it)

    for (vname, deadline, delivery), vendor_items in sorted(
        by_vendor.items(), key=lambda x: x[0][0] or ""
    ):
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

        for it in sorted(vendor_items, key=lambda x: x["qty"]):
            par_info = f"  par={it['par']:.0f}" if it["par"] is not None else ""
            cover = it.get("days_of_cover")
            cover_info = f"  cover={float(cover):.1f}d" if cover is not None else ""
            tier = it["tier"] or "?"
            print(
                f"    {it['name']:<28} qty={it['qty']:<6.1f} "
                f"${it['cost']:<8.2f} tier={tier}{par_info}{cover_info}"
            )
        print()

    if no_vendor:
        print("--- NO VENDOR ASSIGNED ---")
        for it in sorted(no_vendor, key=lambda x: x["qty"]):
            tier = it["tier"] or "?"
            print(
                f"    {it['name']:<28} qty={it['qty']:<6.1f} "
                f"${it['cost']:<8.2f} tier={tier}"
            )
        print()

    critical = [i for i in items if i["qty"] <= 0.5]
    low = [i for i in items if 0.5 < i["qty"] <= 1.5]

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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Reorder report from inv_daily_ledger (not inv_items.current_qty)."
    )
    parser.add_argument(
        "--threshold",
        "-t",
        type=float,
        default=None,
        help="Only show items with ledger closing_qty <= threshold "
        "(default: items with reorder_alert on latest ledger date).",
    )
    args = parser.parse_args()
    run_report(args.threshold)
