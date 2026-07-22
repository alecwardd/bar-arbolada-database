"""
Parser for Lightspeed Payments Report CSV.

File structure:
  Line 1: "Payments Report - Bar Arbolada"
  Line 2: "02-04-2026 to 02-04-2026"
  Line 3: "Totals"
  Lines 4-15: Totals summary section
  Line 16: "Payments List"
  Line 17: Column headers (Status,Tender,Tender Account,Date,Check No.,Trading Day,Payment,Tip,Total,Server)
  Lines 18+: Individual payment rows
  "Refunds" section: at end

We import only the Payments List (individual payment rows).
The Totals section data is already captured from the Sales Report.
"""

import csv
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta
from io import StringIO
from pathlib import Path

from sqlalchemy.orm import Session

from src.models import PosPayment
from src.importers.base import (
    file_hash,
    check_duplicate,
    create_import_log,
    record_error_log,
    read_csv_lines,
    parse_date_range_from_header,
    parse_datetime_str,
    parse_date_str,
    safe_decimal,
)


def _norm(s: str | None) -> str:
    return (s or "").strip()


def _amount_key(val) -> int | None:
    """
    Normalize a money value for deduping.

    DB stores amounts as Numeric(10,2); CSV parsing yields floats. Convert to
    integer cents via decimal quantization so float noise never splits a match.
    """
    if val is None:
        return None
    try:
        d = Decimal(str(val)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        return None
    return int(d * 100)


def _payment_key(
    payment_dt,
    check_number: str | None,
    tender_type: str | None,
    tender_account: str | None,
    status: str | None,
    payment_amount,
    tip_amount,
    total_amount,
    server: str | None,
) -> tuple:
    """
    Content key identifying one payment transaction.

    Used to skip rows that already exist in the DB. This protects against the
    same day arriving in both a daily and a weekly/annual export: those files
    have different SHA-256 hashes, so the file-hash guard does not catch them,
    but the individual payment rows are identical and must not double-insert.
    Mirrors the row-level dedupe used for comps/voids.
    """
    return (
        payment_dt.isoformat(sep=" ") if payment_dt else None,
        _norm(check_number),
        _norm(tender_type),
        _norm(tender_account),
        _norm(status),
        _amount_key(payment_amount),
        _amount_key(tip_amount),
        _amount_key(total_amount),
        _norm(server),
    )


def import_payments_report(session: Session, filepath: str | Path) -> int:
    """Import individual payment records from Lightspeed Payments Report."""
    filepath = Path(filepath)
    fhash = file_hash(filepath)

    if check_duplicate(session, fhash):
        print(f"  [SKIP] Already imported: {filepath.name}")
        return 0

    lines = read_csv_lines(filepath)
    if len(lines) < 10:
        print(f"  [ERROR] File too short: {filepath.name}")
        record_error_log(session, filepath.name, "payments", "File too short", fhash)
        return 0

    date_start, date_end = parse_date_range_from_header(lines[1])
    log = create_import_log(
        session, filepath.name, "payments", date_start, date_end, fhash
    )

    # Find "Payments List" section
    payments_idx = None
    for i, line in enumerate(lines):
        if line.strip() == "Payments List":
            payments_idx = i
            break

    if payments_idx is None:
        log.status = "success"
        log.row_count = 0
        session.commit()
        print(f"  [WARN] No Payments List section found in {filepath.name}")
        return 0

    # Parse from header line (payments_idx + 1) to end or "Refunds" section
    end_idx = len(lines)
    for i in range(payments_idx + 1, len(lines)):
        if lines[i].strip().startswith("Refunds"):
            end_idx = i
            break

    csv_text = "\n".join(lines[payments_idx + 1 : end_idx])
    reader = csv.DictReader(StringIO(csv_text))

    # Row-level dedupe: daily and weekly/annual exports overlap, and those files
    # have distinct hashes so the file-hash guard above does not catch them.
    # Load existing payment keys within a wide trading-day window (Lightspeed
    # exports can include rows outside the stated header range) and skip matches.
    buffer_days = 400
    existing_keys: set[tuple] = set()
    try:
        start_dt = (date_start - timedelta(days=buffer_days)) if date_start else None
        end_dt = (date_end + timedelta(days=buffer_days)) if date_end else None
        if start_dt and end_dt:
            existing_rows = (
                session.query(PosPayment)
                .with_entities(
                    PosPayment.payment_date,
                    PosPayment.check_number,
                    PosPayment.tender_type,
                    PosPayment.tender_account,
                    PosPayment.status,
                    PosPayment.payment_amount,
                    PosPayment.tip_amount,
                    PosPayment.total_amount,
                    PosPayment.server,
                )
                .filter(PosPayment.trading_day.isnot(None))
                .filter(PosPayment.trading_day >= start_dt)
                .filter(PosPayment.trading_day <= end_dt)
                .all()
            )
            for r in existing_rows:
                existing_keys.add(
                    _payment_key(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8])
                )
    except Exception:
        existing_keys = set()

    count = 0
    skipped = 0
    for row in reader:
        status = row.get("Status", "").strip()
        if not status:
            continue

        payment_dt = parse_datetime_str(row.get("Date", ""))
        trading_day_val = parse_date_str(row.get("Trading Day", ""))
        payment_amount = safe_decimal(row.get("Payment"))
        tip_amount = safe_decimal(row.get("Tip"))
        total_amount = safe_decimal(row.get("Total"))
        check_number = row.get("Check No.", "").strip() or None
        tender_type = row.get("Tender", "").strip() or None
        tender_account = row.get("Tender Account", "").strip() or None
        server = row.get("Server", "").strip() or None

        key = _payment_key(
            payment_dt,
            check_number,
            tender_type,
            tender_account,
            status,
            payment_amount,
            tip_amount,
            total_amount,
            server,
        )
        if key in existing_keys:
            skipped += 1
            continue
        existing_keys.add(key)

        payment = PosPayment(
            status=status,
            tender_type=tender_type,
            tender_account=tender_account,
            payment_date=payment_dt,
            check_number=check_number,
            trading_day=trading_day_val or date_start,
            payment_amount=payment_amount,
            tip_amount=tip_amount,
            total_amount=total_amount,
            server=server,
            import_log_id=log.id,
        )
        session.add(payment)
        count += 1

    log.row_count = count
    log.status = "success"
    session.commit()
    if skipped:
        print(
            f"  [OK] Imported {count} payments for {date_start} "
            f"(skipped {skipped} duplicates)"
        )
    else:
        print(f"  [OK] Imported {count} payments for {date_start}")
    return count
