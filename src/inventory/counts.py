"""
Physical inventory counts.

Creates ``inv_counts`` + ``inv_count_lines``, updates the non-authoritative
``inv_items.current_qty`` convenience field, and seeds ledger openings via
``set_opening_from_count`` (ledger = on-hand source of truth — ADR 0001).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from src.inventory.ledger import set_opening_from_count
from src.models import InvCount, InvCountLine, InvItem


def create_count_from_dict(
    session: Session,
    counts_dict: dict[int, Decimal],
    *,
    counted_by: str = "Owner",
    notes: str | None = None,
    count_type: str = "full",
    count_date: date | None = None,
    verbose: bool = True,
) -> InvCount:
    """
    Persist a completed physical count.

    ``counts_dict`` maps ``inv_item_id -> counted_qty`` (stock UOM).
    Caller owns the outer transaction only if they need to — this function
    commits before returning (same contract as the CLI script).
    """
    if not counts_dict:
        raise ValueError("counts_dict is empty")

    count = InvCount(
        count_date=count_date or date.today(),
        count_type=count_type,
        counted_by=counted_by,
        notes=notes
        or f"Physical count recorded {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        status="completed",
    )
    session.add(count)
    session.flush()

    updated = 0
    for item_id, qty in counts_dict.items():
        item = session.query(InvItem).filter(InvItem.id == item_id).first()
        if not item:
            if verbose:
                print(f"  WARNING: item id={item_id} not found, skipping")
            continue

        old_qty = item.current_qty or Decimal("0")
        variance = qty - old_qty

        session.add(
            InvCountLine(
                count_id=count.id,
                inv_item_id=item_id,
                counted_qty=qty,
                unit_of_measure=item.unit_of_measure,
                theoretical_qty=old_qty,
                variance=variance,
                variance_pct=round((variance / old_qty * 100), 2) if old_qty else None,
            )
        )

        # Convenience catalog field (non-authoritative).
        item.current_qty = qty
        item.updated_at = datetime.utcnow()

        set_opening_from_count(item_id, count.count_date, qty, session=session)
        updated += 1

        if verbose:
            direction = "+" if variance > 0 else ""
            print(
                f"  [{item.id:>3}] {item.name:<28} "
                f"{float(old_qty):.1f} -> {float(qty):.1f}  "
                f"({direction}{float(variance):.1f})"
            )

    session.commit()
    if verbose:
        print(
            f"\nCount #{count.id} saved: {updated} items updated "
            f"(ledger openings seeded)"
        )
    return count
