"""
Daily Ledger Calculation Engine
================================
Computes theoretical inventory for each tracked item, each day:

    closing = opening + purchases - theoretical_usage + adjustments

Also computes days_of_cover and sets reorder_alert flags.
"""

from datetime import date, timedelta
from decimal import Decimal
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.config import get_session
from src.models import InvDailyLedger, InvItem, InvInvoiceLine, InvAdjustment

ZERO = Decimal("0")
LOOKBACK_DAYS = 14  # rolling window for avg daily usage


def compute_ledger(target_date: date, session: Session = None) -> dict:
    """
    Compute the daily ledger for ALL active Tier-A/B inventory items
    for a given date.

    Returns a summary dict with counts.
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

        for item in items:
            result = _compute_item_ledger(session, item, target_date)
            if result == "created":
                created += 1
            elif result == "updated":
                updated += 1

        session.commit()
        return {"date": target_date, "items_processed": len(items),
                "created": created, "updated": updated}

    finally:
        if own_session:
            session.close()


def _compute_item_ledger(session: Session, item: InvItem, target_date: date) -> str:
    """Compute ledger for a single item on a single day."""

    # 1. Get opening qty (= previous day's closing, or 0 if first day)
    prev_date = target_date - timedelta(days=1)
    prev_ledger = (
        session.query(InvDailyLedger)
        .filter_by(inv_item_id=item.id, ledger_date=prev_date)
        .first()
    )
    opening_qty = prev_ledger.closing_qty if prev_ledger else ZERO
    if opening_qty is None:
        opening_qty = ZERO

    # 2. Get purchases for this date (from invoice lines)
    purchases_result = session.execute(
        text("""
            SELECT COALESCE(SUM(il.quantity), 0) AS total_qty
            FROM inv_invoice_lines il
            JOIN inv_invoices i ON il.invoice_id = i.id
            WHERE il.inv_item_id = :item_id
              AND i.invoice_date = :target_date
              AND i.status != 'cancelled'
              AND COALESCE(il.line_type, 'item') = 'item'
        """),
        {"item_id": item.id, "target_date": target_date},
    )
    purchases_qty = Decimal(str(purchases_result.scalar() or 0))

    # 3. Get theoretical usage (from recipes x product mix)
    #    This joins recipe_lines -> recipes -> pos_product_mix
    usage_result = session.execute(
        text("""
            SELECT COALESCE(SUM(
                pm.qty_sold * rl.quantity * rl.waste_factor
            ), 0) AS total_usage
            FROM recipe_lines rl
            JOIN recipes r ON rl.recipe_id = r.id
            JOIN pos_product_mix pm ON pm.pos_item_id = r.pos_item_id
            WHERE rl.inv_item_id = :item_id
              AND r.status = 'active'
              AND pm.report_start_date = :target_date
              AND pm.report_end_date = :target_date
              AND pm.entry_type = 'Item'
        """),
        {"item_id": item.id, "target_date": target_date},
    )
    theoretical_usage = Decimal(str(usage_result.scalar() or 0))

    # 4. Get adjustments for this date
    adj_result = session.execute(
        text("""
            SELECT COALESCE(SUM(quantity), 0) AS total_adj
            FROM inv_adjustments
            WHERE inv_item_id = :item_id
              AND adjustment_date = :target_date
        """),
        {"item_id": item.id, "target_date": target_date},
    )
    adjustments_qty = Decimal(str(adj_result.scalar() or 0))

    # 5. Calculate closing
    closing_qty = opening_qty + purchases_qty - theoretical_usage + adjustments_qty

    # 6. Calculate days of cover (avg daily usage over lookback period)
    lookback_start = target_date - timedelta(days=LOOKBACK_DAYS)
    avg_usage_result = session.execute(
        text("""
            SELECT AVG(theoretical_usage) AS avg_usage
            FROM inv_daily_ledger
            WHERE inv_item_id = :item_id
              AND ledger_date BETWEEN :start AND :end
              AND theoretical_usage > 0
        """),
        {"item_id": item.id, "start": lookback_start, "end": target_date},
    )
    avg_daily_usage = avg_usage_result.scalar()
    if avg_daily_usage and float(avg_daily_usage) > 0:
        days_of_cover = closing_qty / Decimal(str(avg_daily_usage))
    else:
        days_of_cover = None  # can't calculate without usage history

    # 7. Determine reorder alert
    reorder_alert = False
    if item.reorder_point is not None and closing_qty <= item.reorder_point:
        reorder_alert = True
    elif days_of_cover is not None and item.primary_vendor_id:
        # Alert if days_of_cover <= lead_time + 1
        vendor = item.vendor
        if vendor and vendor.lead_time_days:
            if days_of_cover <= Decimal(str(vendor.lead_time_days + 1)):
                reorder_alert = True

    # 8. Upsert ledger entry
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
        return "updated"
    else:
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
        return "created"


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


def set_opening_from_count(inv_item_id: int, count_date: date,
                           counted_qty: Decimal, session: Session = None) -> None:
    """
    Set the opening inventory for an item from a physical count.
    Creates or updates the ledger entry for that date with the counted qty
    as the opening and closing (purchases/usage will adjust from there).
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

        session.commit()
    finally:
        if own_session:
            session.close()
