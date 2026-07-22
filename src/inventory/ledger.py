"""
Daily Ledger Calculation Engine
================================
Computes theoretical inventory for each tracked item, each day:

    closing = opening + purchases - theoretical_usage + adjustments

Quantities are in each item's stock unit (``InvItem.unit_of_measure``).
Recipe/invoice lines are converted via ``src.inventory.uom`` before summing.

Also computes days_of_cover and sets reorder_alert flags.
"""

from datetime import date, timedelta
from decimal import Decimal
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.config import get_session
from src.inventory.uom import qty_to_stock_units
from src.models import InvDailyLedger, InvItem

ZERO = Decimal("0")
LOOKBACK_DAYS = 14  # rolling window for avg daily usage


def compute_ledger(target_date: date, session: Session = None) -> dict:
    """
    Compute the daily ledger for ALL active Tier-A/B inventory items
    for a given date.

    Returns a summary dict with counts (including conversion skips).
    """
    own_session = session is None
    if own_session:
        session = get_session()

    try:
        items = (
            session.query(InvItem)
            .filter(InvItem.status == "active")
            .filter(InvItem.inventory_tier.in_(["A", "B"]))
            .all()
        )

        created = 0
        updated = 0
        conversion_skipped = 0

        for item in items:
            result, skipped = _compute_item_ledger(session, item, target_date)
            conversion_skipped += skipped
            if result == "created":
                created += 1
            elif result == "updated":
                updated += 1

        session.commit()
        return {
            "date": target_date,
            "items_processed": len(items),
            "created": created,
            "updated": updated,
            "conversion_skipped": conversion_skipped,
        }

    finally:
        if own_session:
            session.close()


def _opening_qty_for_day(session: Session, item_id: int, target_date: date) -> Decimal:
    """
    Prefer a completed physical count on ``target_date`` as start-of-day opening;
    otherwise use previous day's closing (or 0).
    """
    count_opening = session.execute(
        text(
            """
            SELECT cl.counted_qty
            FROM inv_count_lines cl
            JOIN inv_counts c ON c.id = cl.count_id
            WHERE cl.inv_item_id = :item_id
              AND c.count_date = :target_date
              AND c.status = 'completed'
            ORDER BY c.id DESC
            LIMIT 1
            """
        ),
        {"item_id": item_id, "target_date": target_date},
    ).scalar()
    if count_opening is not None:
        return Decimal(str(count_opening))

    prev_date = target_date - timedelta(days=1)
    prev_ledger = (
        session.query(InvDailyLedger)
        .filter_by(inv_item_id=item_id, ledger_date=prev_date)
        .first()
    )
    opening_qty = prev_ledger.closing_qty if prev_ledger else ZERO
    return opening_qty if opening_qty is not None else ZERO


def _sum_purchases(session: Session, item: InvItem, target_date: date) -> tuple[Decimal, int]:
    rows = session.execute(
        text(
            """
            SELECT il.quantity, il.unit_of_measure
            FROM inv_invoice_lines il
            JOIN inv_invoices i ON il.invoice_id = i.id
            WHERE il.inv_item_id = :item_id
              AND i.invoice_date = :target_date
              AND i.status != 'cancelled'
              AND COALESCE(il.line_type, 'item') = 'item'
            """
        ),
        {"item_id": item.id, "target_date": target_date},
    ).fetchall()

    total = ZERO
    skipped = 0
    for qty, uom in rows:
        converted = qty_to_stock_units(
            qty,
            uom,
            stock_uom=item.unit_of_measure,
            bottle_size_ml=item.bottle_size_ml,
            pack_size=item.pack_size,
        )
        if converted is None:
            skipped += 1
            continue
        total += converted
    return total, skipped


def _sum_usage(session: Session, item: InvItem, target_date: date) -> tuple[Decimal, int]:
    rows = session.execute(
        text(
            """
            SELECT pm.qty_sold, rl.quantity, rl.unit_of_measure, rl.waste_factor
            FROM recipe_lines rl
            JOIN recipes r ON rl.recipe_id = r.id
            JOIN pos_product_mix pm ON pm.pos_item_id = r.pos_item_id
            WHERE rl.inv_item_id = :item_id
              AND r.status = 'active'
              AND pm.report_start_date = :target_date
              AND pm.report_end_date = :target_date
              AND pm.entry_type = 'Item'
            """
        ),
        {"item_id": item.id, "target_date": target_date},
    ).fetchall()

    total = ZERO
    skipped = 0
    for qty_sold, line_qty, uom, waste in rows:
        per_serving = qty_to_stock_units(
            line_qty,
            uom,
            stock_uom=item.unit_of_measure,
            bottle_size_ml=item.bottle_size_ml,
            pack_size=item.pack_size,
        )
        if per_serving is None:
            skipped += 1
            continue
        sold = Decimal(str(qty_sold or 0))
        factor = Decimal(str(waste if waste is not None else 1))
        total += sold * per_serving * factor
    return total, skipped


def _sum_adjustments(session: Session, item: InvItem, target_date: date) -> tuple[Decimal, int]:
    rows = session.execute(
        text(
            """
            SELECT quantity, unit_of_measure
            FROM inv_adjustments
            WHERE inv_item_id = :item_id
              AND adjustment_date = :target_date
            """
        ),
        {"item_id": item.id, "target_date": target_date},
    ).fetchall()

    total = ZERO
    skipped = 0
    for qty, uom in rows:
        converted = qty_to_stock_units(
            qty,
            uom,
            stock_uom=item.unit_of_measure,
            bottle_size_ml=item.bottle_size_ml,
            pack_size=item.pack_size,
        )
        if converted is None:
            skipped += 1
            continue
        total += converted
    return total, skipped


def _compute_item_ledger(session: Session, item: InvItem, target_date: date) -> tuple[str, int]:
    """Compute ledger for a single item on a single day. Returns (status, skips)."""

    opening_qty = _opening_qty_for_day(session, item.id, target_date)
    purchases_qty, skip_p = _sum_purchases(session, item, target_date)
    theoretical_usage, skip_u = _sum_usage(session, item, target_date)
    adjustments_qty, skip_a = _sum_adjustments(session, item, target_date)
    skipped = skip_p + skip_u + skip_a

    closing_qty = opening_qty + purchases_qty - theoretical_usage + adjustments_qty

    lookback_start = target_date - timedelta(days=LOOKBACK_DAYS)
    avg_usage_result = session.execute(
        text(
            """
            SELECT AVG(theoretical_usage) AS avg_usage
            FROM inv_daily_ledger
            WHERE inv_item_id = :item_id
              AND ledger_date BETWEEN :start AND :end
              AND theoretical_usage > 0
            """
        ),
        {"item_id": item.id, "start": lookback_start, "end": target_date},
    )
    avg_daily_usage = avg_usage_result.scalar()
    if avg_daily_usage and float(avg_daily_usage) > 0:
        days_of_cover = closing_qty / Decimal(str(avg_daily_usage))
    else:
        days_of_cover = None

    reorder_alert = False
    if item.reorder_point is not None and closing_qty <= item.reorder_point:
        reorder_alert = True
    elif days_of_cover is not None and item.primary_vendor_id:
        vendor = item.vendor
        if vendor and vendor.lead_time_days:
            if days_of_cover <= Decimal(str(vendor.lead_time_days + 1)):
                reorder_alert = True

    existing = (
        session.query(InvDailyLedger)
        .filter_by(inv_item_id=item.id, ledger_date=target_date)
        .first()
    )

    if existing:
        existing.opening_qty = opening_qty
        existing.purchases_qty = purchases_qty
        existing.theoretical_usage = theoretical_usage
        existing.adjustments_qty = adjustments_qty
        existing.closing_qty = closing_qty
        existing.days_of_cover = days_of_cover
        existing.reorder_alert = reorder_alert
        return "updated", skipped

    ledger = InvDailyLedger(
        inv_item_id=item.id,
        ledger_date=target_date,
        opening_qty=opening_qty,
        purchases_qty=purchases_qty,
        theoretical_usage=theoretical_usage,
        adjustments_qty=adjustments_qty,
        closing_qty=closing_qty,
        days_of_cover=days_of_cover,
        reorder_alert=reorder_alert,
    )
    session.add(ledger)
    return "created", skipped


def compute_ledger_range(start: date, end: date, session: Session = None) -> list[dict]:
    """Compute ledger for a range of dates, day by day."""
    own_session = session is None
    if own_session:
        session = get_session()

    results = []
    try:
        current = start
        while current <= end:
            result = compute_ledger(current, session)
            results.append(result)
            current += timedelta(days=1)
        return results
    finally:
        if own_session:
            session.close()


def set_opening_from_count(
    inv_item_id: int,
    count_date: date,
    counted_qty: Decimal,
    session: Session = None,
) -> None:
    """
    Seed ledger opening (start-of-day stock) from a physical count.

    When ``session`` is provided, only flushes — the caller owns the commit.
    """
    own_session = session is None
    if own_session:
        session = get_session()

    try:
        existing = (
            session.query(InvDailyLedger)
            .filter_by(inv_item_id=inv_item_id, ledger_date=count_date)
            .first()
        )

        if existing:
            existing.opening_qty = counted_qty
            existing.closing_qty = (
                counted_qty
                + (existing.purchases_qty or ZERO)
                - (existing.theoretical_usage or ZERO)
                + (existing.adjustments_qty or ZERO)
            )
        else:
            ledger = InvDailyLedger(
                inv_item_id=inv_item_id,
                ledger_date=count_date,
                opening_qty=counted_qty,
                purchases_qty=ZERO,
                theoretical_usage=ZERO,
                adjustments_qty=ZERO,
                closing_qty=counted_qty,
            )
            session.add(ledger)

        if own_session:
            session.commit()
        else:
            session.flush()
    finally:
        if own_session:
            session.close()
