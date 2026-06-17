"""
Parser for Lightspeed Product Mix Report CSV.

File structure:
  Line 1: "Product Mix Report - Bar Arbolada"
  Line 2: "02-04-2026 to 02-04-2026"
  Line 3: Column headers (Type,ID,Name,Sold,Void,Comp,Price,Cost,Gross,...)
  Lines 4+: Data rows (Type = 'Category', 'Item', or 'Modifier')

This is the KEY report for theoretical inventory -- tells us how many
of each item were sold.
"""

import csv
from decimal import Decimal
from io import StringIO
from pathlib import Path

from sqlalchemy.orm import Session

from src.models import PosItem, PosProductMix
from src.importers.base import (
    file_hash,
    check_duplicate,
    create_import_log,
    read_csv_lines,
    parse_date_range_from_header,
    safe_decimal,
    safe_int,
)


def _load_pos_item_costs(session: Session) -> dict[str, "Decimal"]:
    """Build name -> unit cost lookup from pos_items for cost override."""
    rows = (
        session.query(PosItem.name, PosItem.cost)
        .filter(PosItem.cost.isnot(None), PosItem.cost > 0)
        .all()
    )
    return {name: cost for name, cost in rows}


def _check_daily_overlap(session: Session, date_start, date_end) -> bool:
    """
    Return True if single-day records already exist for every date in [date_start, date_end].

    A multi-day report (e.g. a monthly summary) that overlaps with existing daily records
    would cause double-counting in aggregation queries, because the unique constraint is
    keyed on (report_start_date, report_end_date, …) so monthly and daily rows for the
    same item are stored as separate, non-conflicting records.
    """
    from sqlalchemy import text
    from datetime import timedelta

    if date_start == date_end:
        return False  # Single-day report — no overlap risk

    span_days = (date_end - date_start).days
    dates_to_check = [date_start + timedelta(days=i) for i in range(span_days + 1)]

    result = session.execute(
        text("""
            SELECT COUNT(DISTINCT report_start_date)
            FROM pos_product_mix
            WHERE report_start_date = report_end_date
              AND report_start_date = ANY(:dates)
        """),
        {"dates": dates_to_check},
    )
    covered = result.scalar() or 0
    return covered > 0


def import_product_mix_report(session: Session, filepath: str | Path) -> int:
    """Import a Lightspeed Product Mix Report CSV."""
    filepath = Path(filepath)
    fhash = file_hash(filepath)

    if check_duplicate(session, fhash):
        print(f"  [SKIP] Already imported: {filepath.name}")
        return 0

    lines = read_csv_lines(filepath)
    if len(lines) < 4:
        print(f"  [ERROR] File too short: {filepath.name}")
        return 0

    date_start, date_end = parse_date_range_from_header(lines[1])
    if not date_start:
        print(f"  [ERROR] Could not parse date from: {lines[1]}")
        return 0

    if date_start != date_end and _check_daily_overlap(session, date_start, date_end):
        print(
            f"  [SKIP] Multi-day report ({date_start} to {date_end}) overlaps with "
            f"existing daily records — skipping to prevent double-counting. "
            f"Delete the daily records first if you need the summary report."
        )
        return 0

    log = create_import_log(
        session, filepath.name, "product_mix", date_start, date_end, fhash
    )

    # Parse CSV starting at line 3 (header) + line 4+ (data)
    csv_text = "\n".join(lines[2:])
    reader = csv.DictReader(StringIO(csv_text))

    # pos_items.cost is the source of truth; override Lightspeed CSV values
    db_costs = _load_pos_item_costs(session)

    count = 0
    for row in reader:
        entry_type = row.get("Type", "").strip()
        pos_item_id = row.get("ID", "").strip()
        item_name = row.get("Name", "").strip()

        if not item_name:
            continue

        # Check for existing record (include item_name for split category UUIDs)
        existing = (
            session.query(PosProductMix)
            .filter(
                PosProductMix.report_start_date == date_start,
                PosProductMix.report_end_date == date_end,
                PosProductMix.entry_type == entry_type,
                PosProductMix.pos_item_id == pos_item_id,
                PosProductMix.item_name == item_name,
            )
            .first()
        )

        pmix = existing or PosProductMix()

        pmix.report_start_date = date_start
        pmix.report_end_date = date_end
        pmix.entry_type = entry_type
        pmix.pos_item_id = pos_item_id if pos_item_id else None
        pmix.item_name = item_name
        pmix.qty_sold = safe_int(row.get("Sold"))
        pmix.qty_void = safe_int(row.get("Void"))
        pmix.qty_comp = safe_int(row.get("Comp"))
        pmix.avg_price = safe_decimal(row.get("Price"))
        pmix.gross_sales = safe_decimal(row.get("Gross"))
        pmix.comp_amount = safe_decimal(row.get("Comps"))
        pmix.total_tax = safe_decimal(row.get("Total Tax"))
        pmix.net_sales = safe_decimal(row.get("Net"))
        pmix.receipt_total = safe_decimal(row.get("Receipt Total"))
        pmix.category_name = (row.get("Category Name") or "").strip() or None
        pmix.category_id = (row.get("Category ID") or "").strip() or None
        pmix.item_identifier = (row.get("Identifier") or "").strip() or None
        pmix.import_log_id = log.id

        # Use database cost (pos_items.cost) when available; fall back to CSV
        # Normalize to Decimal so we never mix float and Decimal (safe_decimal returns float).
        unit_cost = db_costs.get(item_name)
        if unit_cost and pmix.qty_sold:
            pmix.cost = pmix.qty_sold * unit_cost
            net = Decimal(str(pmix.net_sales)) if pmix.net_sales is not None else Decimal("0")
            pmix.gross_profit = net - pmix.cost
        else:
            pmix.cost = safe_decimal(row.get("Cost"))
            pmix.gross_profit = safe_decimal(row.get("Gross Profit"))

        if not existing:
            session.add(pmix)
            session.flush()  # Flush to avoid batch conflicts on shared UUIDs

        count += 1

    log.row_count = count
    log.status = "success"
    session.commit()
    print(f"  [OK] Imported {count} product mix rows for {date_start}")
    return count
