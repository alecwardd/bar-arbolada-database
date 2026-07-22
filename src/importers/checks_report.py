"""
Parser for Lightspeed Check Detail Report CSV.

File structure:
  Line 1: "Check Detail Report - Bar Arbolada"
  Line 2: "02-04-2026 to 02-04-2026"
  Line 3: Column headers (#, Name, Server, Date, Status, Guests, ...)
  Lines 4+: One row per check

Also derives pos_hourly_sales from check timestamps.
"""

import csv
from collections import defaultdict
from datetime import timedelta
from io import StringIO
from pathlib import Path

from sqlalchemy.orm import Session

from src.models import PosCheck, PosHourlySales
from src.importers.base import (
    file_hash,
    check_duplicate,
    create_import_log,
    read_csv_lines,
    parse_date_range_from_header,
    parse_datetime_str,
    safe_decimal,
    safe_int,
)


def import_checks_report(session: Session, filepath: str | Path) -> int:
    """
    Import a Lightspeed Check Detail Report CSV.

    Also computes and stores hourly sales aggregation.
    Returns number of check records imported.
    """
    filepath = Path(filepath)
    fhash = file_hash(filepath)

    if check_duplicate(session, fhash):
        print(f"  [SKIP] Already imported: {filepath.name}")
        return 0

    lines = read_csv_lines(filepath)
    if len(lines) < 4:
        # Raise (do not return 0): import_file treats count>=0 as success, which
        # would mark the IMAP message \\Seen and permanently drop a bad attachment.
        raise ValueError(f"File too short: {filepath.name}")

    date_start, date_end = parse_date_range_from_header(lines[1])
    is_single_day = (date_start == date_end)
    log = create_import_log(
        session, filepath.name, "checks", date_start, date_end, fhash
    )

    # Parse the header to get column positions
    # Header is line 3 (index 2)
    header_line = lines[2]
    reader = csv.reader(StringIO(header_line))
    headers = next(reader)
    headers = [h.strip() for h in headers]

    # Parse data rows
    count = 0
    seen_checks = set()  # Track (check_number, trading_day, opened_at, name) within this batch
    # For multi-day reports, bucket hourly data by (trading_day, hour)
    hourly_data = defaultdict(lambda: {
        "net_sales": 0.0,
        "gross_sales": 0.0,
        "check_count": 0,
        "guest_count": 0,
        "tips": 0.0,
    })

    for line in lines[3:]:
        if not line.strip():
            continue

        reader = csv.reader(StringIO(line))
        try:
            values = next(reader)
        except StopIteration:
            continue

        if len(values) < 10:
            continue

        # Build dict from headers + values
        row = {}
        for i, h in enumerate(headers):
            row[h] = values[i].strip() if i < len(values) else ""

        check_number = row.get("#", "").strip()
        if not check_number:
            continue

        opened_at = parse_datetime_str(row.get("Date", ""))

        # Determine the effective trading day from each check's date.
        # For single-day reports, use the header date as fallback.
        # For multi-day reports, derive from the check's opened_at timestamp.
        # Bar trading days typically end at ~4-6am, so checks between
        # midnight and 6am belong to the PREVIOUS calendar day's trading day.
        if is_single_day:
            check_trading_day = date_start
        elif opened_at:
            if opened_at.hour < 6:
                # After-midnight check: belongs to previous day's trading period
                check_trading_day = (opened_at - timedelta(days=1)).date()
            else:
                check_trading_day = opened_at.date()
        else:
            check_trading_day = date_start

        # Revenue center field is at the end; may contain just whitespace
        revenue_center = row.get("Revenue Center", "").strip()

        check = PosCheck(
            check_number=check_number,
            check_name=row.get("Name", "").strip() or None,
            server=row.get("Server", "").strip() or None,
            opened_at=opened_at,
            status=row.get("Status", "").strip() or None,
            guests=safe_int(row.get("Guests")),
            comps=safe_decimal(row.get("Comps")),
            voids=safe_decimal(row.get("Voids")),
            net_sales=safe_decimal(row.get("Net Sales")),
            auto_grat=safe_decimal(row.get("Auto Grat")),
            total_tax=safe_decimal(row.get("Total Tax")),
            bill_total=safe_decimal(row.get("Bill Total")),
            payment_total=safe_decimal(row.get("Payment")),
            tips_total=safe_decimal(row.get("Tips")),
            cash_payment=safe_decimal(row.get("Cash")),
            cash_tips=safe_decimal(row.get("Cash Tips")),
            credit_payment=safe_decimal(row.get("Credit")),
            credit_tips=safe_decimal(row.get("Credit Tips")),
            revenue_center=revenue_center if revenue_center else None,
            trading_day=check_trading_day,
            import_log_id=log.id,
        )

        # Build a dedup key -- split checks have same check_number + time
        # but different names (e.g., "KING, DUSTIN/A" vs "ROUDYBUSH, JAY")
        dedup_key = (check_number, str(check_trading_day), str(opened_at), check.check_name or "")

        if dedup_key in seen_checks:
            continue  # Skip in-batch duplicates

        # Check for duplicates already in database
        existing = (
            session.query(PosCheck)
            .filter(
                PosCheck.check_number == check_number,
                PosCheck.trading_day == check_trading_day,
                PosCheck.opened_at == opened_at,
                PosCheck.check_name == (check.check_name or ""),
            )
            .first()
        )
        if existing:
            # Update existing record
            for attr in [
                "server", "status", "guests", "comps", "voids",
                "net_sales", "auto_grat", "total_tax", "bill_total",
                "payment_total", "tips_total", "cash_payment", "cash_tips",
                "credit_payment", "credit_tips", "revenue_center",
            ]:
                setattr(existing, attr, getattr(check, attr))
        else:
            session.add(check)
            session.flush()  # Flush immediately to avoid batch conflicts

        seen_checks.add(dedup_key)

        count += 1

        # Accumulate hourly data for pos_hourly_sales
        # Key by (trading_day, hour) to support multi-day reports
        if opened_at and check.net_sales is not None:
            hour = opened_at.hour
            hkey = (check_trading_day, hour)
            net = float(check.net_sales or 0)
            tips = float(check.tips_total or 0)
            guests = int(check.guests or 0)

            hourly_data[hkey]["net_sales"] += net
            hourly_data[hkey]["gross_sales"] += float(check.bill_total or 0)
            hourly_data[hkey]["check_count"] += 1
            hourly_data[hkey]["guest_count"] += guests
            hourly_data[hkey]["tips"] += tips

    # Store hourly sales
    hourly_count = 0
    for (h_trading_day, hour), data in hourly_data.items():
        existing_hourly = (
            session.query(PosHourlySales)
            .filter(
                PosHourlySales.trading_day == h_trading_day,
                PosHourlySales.hour_of_day == hour,
            )
            .first()
        )

        check_count = data["check_count"]
        avg_check = data["net_sales"] / check_count if check_count > 0 else 0

        if existing_hourly:
            existing_hourly.net_sales = data["net_sales"]
            existing_hourly.gross_sales = data["gross_sales"]
            existing_hourly.check_count = check_count
            existing_hourly.guest_count = data["guest_count"]
            existing_hourly.avg_check = avg_check
            existing_hourly.tips = data["tips"]
        else:
            hourly = PosHourlySales(
                trading_day=h_trading_day,
                hour_of_day=hour,
                net_sales=data["net_sales"],
                gross_sales=data["gross_sales"],
                check_count=check_count,
                guest_count=data["guest_count"],
                avg_check=avg_check,
                tips=data["tips"],
            )
            session.add(hourly)
        hourly_count += 1

    # Data quality: warn if all guest counts are 0 (POS default not set)
    total_guest_sum = sum(d["guest_count"] for d in hourly_data.values())
    if count > 0 and total_guest_sum == 0:
        print(
            f"  [WARN] All {count} checks have guests=0. "
            f"Guest counts are unreliable -- use check_count as traffic proxy. "
            f"(POS guest default was likely 0 before ~Dec 2022.)"
        )

    log.row_count = count
    log.status = "success"
    session.commit()
    trading_days_covered = len(set(k[0] for k in hourly_data.keys())) if hourly_data else 1
    print(
        f"  [OK] Imported {count} checks + {hourly_count} hourly buckets "
        f"across {trading_days_covered} trading day(s) ({date_start} to {date_end})"
    )
    return count
