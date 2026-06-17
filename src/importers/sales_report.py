"""
Parser for Lightspeed Sales Report CSV.

This is the most complex CSV -- it has 10+ sections in one file.
We extract:
  - pos_daily_sales (aggregate totals)
  - pos_daily_sales_by_daypart (Happy Hour, Close, Open, None)
  - pos_daily_sales_by_category (category-level breakdown)

File structure (observed from sample):
  Line 1: "Sales Report - Bar Arbolada"
  Line 2: "02-04-2026 to 02-04-2026"
  Line 3: "Sales"
  Lines 4-8: Sales totals (key,value pairs)
  "Tax" section, "Tax Total" section, "Tax Exempt", "Non Revenue Receipts"
  "Sales Chart" section (day part gross/net)
  "Metrics" section (day part guest/check counts)
  "Metrics Chart" section (trading day summary)
  "Categories" section (category breakdown)
  "Revenue Centers" section
  "Payments" section
  "Refunds", "Void", "Comp", "Comps Summary", "Deposits Reconciliation"
"""

import csv
from io import StringIO
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from src.models import PosDailySales, PosDailySalesByDaypart, PosDailySalesByCategory
from src.importers.base import (
    file_hash,
    check_duplicate,
    create_import_log,
    read_csv_lines,
    parse_date_range_from_header,
    safe_decimal,
    safe_int,
)


def _find_section(lines: list[str], header: str) -> int:
    """Find the line index where a section header appears."""
    for i, line in enumerate(lines):
        if line.strip().startswith(header):
            return i
    return -1


def import_sales_report(session: Session, filepath: str | Path) -> int:
    """
    Import a Lightspeed Sales Report CSV.

    IMPORTANT: Multi-day reports (weekly/monthly) aggregate day-part and
    category data across the entire range, so we ONLY import those sections
    from single-day reports. However, the Metrics Chart section always has
    per-day rows, so we extract individual daily guest/check data from
    multi-day reports too.

    Returns total number of records created across all sub-tables.
    """
    filepath = Path(filepath)
    fhash = file_hash(filepath)

    if check_duplicate(session, fhash):
        print(f"  [SKIP] Already imported: {filepath.name}")
        return 0

    lines = read_csv_lines(filepath)
    if len(lines) < 3:
        print(f"  [ERROR] File too short: {filepath.name}")
        return 0

    # Parse date range from line 2
    date_start, date_end = parse_date_range_from_header(lines[1])
    if not date_start:
        print(f"  [ERROR] Could not parse date from: {lines[1]}")
        return 0

    is_single_day = (date_start == date_end)

    log = create_import_log(
        session, filepath.name, "sales", date_start, date_end, fhash
    )

    total_records = 0

    if is_single_day:
        # ----- Single-day: import everything -----
        trading_day = date_start

        # 1) Aggregate daily sales
        daily = _parse_aggregate_sales(lines, trading_day, log.id)
        if daily:
            existing = (
                session.query(PosDailySales)
                .filter(PosDailySales.trading_day == trading_day)
                .first()
            )
            if existing:
                for attr, val in daily.__dict__.items():
                    if not attr.startswith("_") and attr != "id":
                        setattr(existing, attr, val)
            else:
                session.add(daily)
            total_records += 1

        # 2) Day part breakdown
        dayparts = _parse_daypart_sales(lines, trading_day)
        for dp in dayparts:
            existing = (
                session.query(PosDailySalesByDaypart)
                .filter(
                    PosDailySalesByDaypart.trading_day == trading_day,
                    PosDailySalesByDaypart.day_part == dp.day_part,
                )
                .first()
            )
            if existing:
                for attr, val in dp.__dict__.items():
                    if not attr.startswith("_") and attr != "id":
                        setattr(existing, attr, val)
            else:
                session.add(dp)
            total_records += 1

        # 3) Category breakdown
        cats = _parse_category_sales(lines, trading_day)
        for cat in cats:
            existing = (
                session.query(PosDailySalesByCategory)
                .filter(
                    PosDailySalesByCategory.trading_day == trading_day,
                    PosDailySalesByCategory.category_name == cat.category_name,
                )
                .first()
            )
            if existing:
                for attr, val in cat.__dict__.items():
                    if not attr.startswith("_") and attr != "id":
                        setattr(existing, attr, val)
            else:
                session.add(cat)
            total_records += 1

    else:
        # ----- Multi-day: extract per-day data from Metrics Chart only -----
        # Day-part and category data are aggregated across the range and
        # cannot be attributed to individual days, so we skip those.
        per_day_records = _parse_metrics_chart_multiday(lines, log.id)
        for daily in per_day_records:
            existing = (
                session.query(PosDailySales)
                .filter(PosDailySales.trading_day == daily.trading_day)
                .first()
            )
            if existing:
                # Only fill in guest/check data if not already populated
                if existing.total_guests is None:
                    existing.total_guests = daily.total_guests
                if existing.total_checks is None:
                    existing.total_checks = daily.total_checks
                if existing.guest_avg is None:
                    existing.guest_avg = daily.guest_avg
                if existing.check_avg is None:
                    existing.check_avg = daily.check_avg
            else:
                session.add(daily)
                session.flush()
            total_records += 1

        print(
            f"  [INFO] Multi-day report ({date_start} to {date_end}): "
            f"extracted {total_records} per-day records from Metrics Chart. "
            f"Day-part and category data skipped (use single-day reports)."
        )

    # Data quality: warn if total_guests is 0 despite having checks
    if is_single_day and daily:
        if (daily.total_guests is not None and daily.total_guests == 0
                and daily.total_checks is not None and daily.total_checks > 0):
            print(
                f"  [WARN] total_guests=0 but total_checks={daily.total_checks}. "
                f"Guest counts are unreliable for this day -- use total_checks as traffic proxy."
            )

    log.row_count = total_records
    log.status = "success"
    session.commit()
    if is_single_day:
        print(f"  [OK] Imported sales report for {date_start}: {total_records} records")
    return total_records


def _parse_metrics_chart_multiday(lines: list[str], import_log_id: int) -> list[PosDailySales]:
    """
    Parse the Metrics Chart section from a multi-day sales report.

    Metrics Chart has per-day rows:
        Trading Day,Total Guests,Total Checks,Guest Avg,Check Avg,Turns per Table
        2026-01-01,10,10,20.00,20.00,0
        2026-01-02,12,12,22.00,22.00,0
        ...

    We create one PosDailySales per row with guest/check metrics.
    Revenue totals are NOT available per-day from multi-day reports.
    """
    from src.importers.base import parse_date_str

    results = []
    metrics_idx = _find_section(lines, "Metrics Chart")
    if metrics_idx < 0:
        return results

    # Skip the header line (Trading Day,Total Guests,...)
    for line in lines[metrics_idx + 2:]:
        stripped = line.strip()
        if not stripped:
            break  # End of section

        parts = [p.strip().strip('"') for p in stripped.split(",")]
        if len(parts) < 5:
            continue

        trading_day = parse_date_str(parts[0])
        if not trading_day:
            continue

        daily = PosDailySales(
            trading_day=trading_day,
            import_log_id=import_log_id,
            total_guests=safe_int(parts[1]),
            total_checks=safe_int(parts[2]),
            guest_avg=safe_decimal(parts[3]),
            check_avg=safe_decimal(parts[4]),
        )
        results.append(daily)

    return results


def _parse_aggregate_sales(lines: list[str], trading_day, import_log_id: int) -> Optional[PosDailySales]:
    """Parse the top-level sales aggregate numbers."""
    daily = PosDailySales(
        trading_day=trading_day,
        import_log_id=import_log_id,
    )

    # Sales section (lines after "Sales" header)
    for line in lines[3:20]:
        parts = [p.strip().strip('"') for p in line.split(",")]
        if len(parts) < 2:
            continue

        label = parts[0].lower() if parts[0] else (parts[0] if len(parts) > 0 else "")
        value = parts[-1]

        # Handle key-value pairs where key might be in col 0 or col 1
        if not label and len(parts) >= 2:
            label = parts[0].lower()
            value = parts[1]

        if "receipts" in label:
            daily.total_receipts = safe_decimal(value)
        elif label == "gross" or (label == "" and "gross" in line.lower()):
            # Need to check this isn't "Gross without Tax"
            if "without" not in line.lower():
                daily.gross_sales = safe_decimal(value)
        elif "gross without" in label or "gross without" in line.lower():
            daily.gross_without_tax = safe_decimal(value)
        elif label == "net" or (label == "" and parts[0] == "" and "Net" in line):
            daily.net_sales = safe_decimal(value)

    # Simpler approach: scan the labeled lines
    for i, line in enumerate(lines):
        parts = [p.strip().strip('"') for p in line.split(",")]
        if len(parts) >= 2:
            key = parts[0].strip().strip('"')
            val = parts[1].strip().strip('"') if len(parts) > 1 else ""

            if key == "Receipts":
                daily.total_receipts = safe_decimal(val)
            elif key == "Gross" and i < 10:
                daily.gross_sales = safe_decimal(val)
            elif key == "Gross without Tax":
                daily.gross_without_tax = safe_decimal(val)
            elif key == "Net" and i < 10:
                daily.net_sales = safe_decimal(val)
            elif key == "Tax on Comps":
                daily.tax_on_comps = safe_decimal(val)
            elif key == "Total Tax":
                daily.total_tax = safe_decimal(val)

        # Tax line items
        if len(parts) >= 3 and parts[0].strip().strip('"') == "Exclusive":
            tax_name = parts[1].strip().strip('"')
            tax_amount = parts[2].strip().strip('"')
            if "Liquor Tax" in tax_name:
                daily.liquor_tax = safe_decimal(tax_amount)
            elif "Sales Tax" in tax_name:
                daily.sales_tax = safe_decimal(tax_amount)
            elif "Fees" in tax_name:
                daily.fees = safe_decimal(tax_amount)

    # Metrics Chart section - trading day totals
    metrics_idx = _find_section(lines, "Metrics Chart")
    if metrics_idx >= 0 and metrics_idx + 2 < len(lines):
        # Header: Trading Day,Total Guests,Total Checks,Guest Avg,Check Avg,...
        # Data: 2026-02-04,10,10,20.00,20.00,0
        data_line = lines[metrics_idx + 2]
        parts = [p.strip().strip('"') for p in data_line.split(",")]
        if len(parts) >= 5:
            daily.total_guests = safe_int(parts[1])
            daily.total_checks = safe_int(parts[2])
            daily.guest_avg = safe_decimal(parts[3])
            daily.check_avg = safe_decimal(parts[4])

    # Payments section - extract cash/credit/tips
    payments_idx = _find_section(lines, "Payments")
    if payments_idx >= 0:
        for line in lines[payments_idx:]:
            parts = [p.strip().strip('"') for p in line.split(",")]
            if len(parts) >= 3:
                label = parts[0].strip()
                if label == "Cash":
                    daily.cash_payments = safe_decimal(parts[1])
                    daily.cash_tips = safe_decimal(parts[2])
                elif label == "Credit Total":
                    daily.credit_payments = safe_decimal(parts[1])
                    daily.credit_tips = safe_decimal(parts[2])
                elif label == "Total" and len(parts) >= 3:
                    # This is the grand total line
                    total_tips = safe_decimal(parts[2])
                    if total_tips is not None and daily.total_tips is None:
                        daily.total_tips = total_tips

    # Comp section
    comp_idx = _find_section(lines, "Comp")
    if comp_idx >= 0:
        for line in lines[comp_idx:]:
            parts = [p.strip().strip('"') for p in line.split(",")]
            if len(parts) >= 2 and parts[0] == "Total":
                daily.total_comps = safe_decimal(parts[1])
                break

    # Void section
    void_idx = _find_section(lines, "Void")
    if void_idx >= 0:
        for line in lines[void_idx:]:
            parts = [p.strip().strip('"') for p in line.split(",")]
            if len(parts) >= 2 and parts[0] == "Total":
                daily.total_voids = safe_decimal(parts[1])
                break

    return daily


def _parse_daypart_sales(lines: list[str], trading_day) -> list[PosDailySalesByDaypart]:
    """Parse Sales Chart + Metrics sections to build day-part records."""
    results = []

    # Sales Chart: Day Part, Gross, Net
    chart_idx = _find_section(lines, "Sales Chart")
    metrics_idx = _find_section(lines, "Metrics")

    if chart_idx < 0:
        return results

    # Build dict of day parts from Sales Chart
    daypart_data = {}
    for line in lines[chart_idx + 2:]:  # skip header
        if not line.strip() or line.strip().startswith("Metrics"):
            break
        parts = [p.strip().strip('"') for p in line.split(",")]
        if len(parts) >= 3:
            dp_name = parts[0].strip().strip('"')
            if dp_name and dp_name not in ("Day Part",):
                daypart_data[dp_name] = {
                    "gross_sales": safe_decimal(parts[1]),
                    "net_sales": safe_decimal(parts[2]),
                }

    # Enrich with Metrics section
    if metrics_idx >= 0:
        for line in lines[metrics_idx + 2:]:  # skip header
            if not line.strip() or not line.strip().startswith('"'):
                break
            parts = [p.strip().strip('"') for p in line.split(",")]
            if len(parts) >= 5:
                dp_name = parts[0].strip().strip('"')
                if dp_name in daypart_data:
                    daypart_data[dp_name]["guests"] = safe_int(parts[1])
                    daypart_data[dp_name]["checks"] = safe_int(parts[2])
                    daypart_data[dp_name]["guest_avg"] = safe_decimal(parts[3])
                    daypart_data[dp_name]["check_avg"] = safe_decimal(parts[4])

    # Create model instances
    for dp_name, data in daypart_data.items():
        dp = PosDailySalesByDaypart(
            trading_day=trading_day,
            day_part=dp_name,
            gross_sales=data.get("gross_sales"),
            net_sales=data.get("net_sales"),
            guests=data.get("guests"),
            checks=data.get("checks"),
            guest_avg=data.get("guest_avg"),
            check_avg=data.get("check_avg"),
        )
        results.append(dp)

    return results


def _parse_category_sales(lines: list[str], trading_day) -> list[PosDailySalesByCategory]:
    """Parse Categories section from Sales Report."""
    results = []
    cat_idx = _find_section(lines, "Categories")
    if cat_idx < 0:
        return results

    # Header line: ,Gross,Comps,Total Tax,Net,Receipt Total
    for line in lines[cat_idx + 2:]:  # skip section label + header
        if not line.strip() or line.startswith("Total") or line.startswith("Revenue"):
            break

        parts = [p.strip().strip('"') for p in line.split(",")]
        if len(parts) >= 6:
            cat_name = parts[0].strip().strip('"')
            if not cat_name:
                continue

            cat = PosDailySalesByCategory(
                trading_day=trading_day,
                category_name=cat_name,
                gross_sales=safe_decimal(parts[1]),
                comps=safe_decimal(parts[2]),
                total_tax=safe_decimal(parts[3]),
                net_sales=safe_decimal(parts[4]),
                receipt_total=safe_decimal(parts[5]),
            )
            results.append(cat)

    return results
