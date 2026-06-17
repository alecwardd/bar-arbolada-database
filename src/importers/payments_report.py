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
from io import StringIO
from pathlib import Path

from sqlalchemy.orm import Session

from src.models import PosPayment
from src.importers.base import (
    file_hash,
    check_duplicate,
    create_import_log,
    read_csv_lines,
    parse_date_range_from_header,
    parse_datetime_str,
    parse_date_str,
    safe_decimal,
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

    count = 0
    for row in reader:
        status = row.get("Status", "").strip()
        if not status:
            continue

        payment_dt = parse_datetime_str(row.get("Date", ""))
        trading_day_val = parse_date_str(row.get("Trading Day", ""))

        payment = PosPayment(
            status=status,
            tender_type=row.get("Tender", "").strip() or None,
            tender_account=row.get("Tender Account", "").strip() or None,
            payment_date=payment_dt,
            check_number=row.get("Check No.", "").strip() or None,
            trading_day=trading_day_val or date_start,
            payment_amount=safe_decimal(row.get("Payment")),
            tip_amount=safe_decimal(row.get("Tip")),
            total_amount=safe_decimal(row.get("Total")),
            server=row.get("Server", "").strip() or None,
            import_log_id=log.id,
        )
        session.add(payment)
        count += 1

    log.row_count = count
    log.status = "success"
    session.commit()
    print(f"  [OK] Imported {count} payments for {date_start}")
    return count
