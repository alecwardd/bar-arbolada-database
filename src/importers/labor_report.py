"""
Parser for Lightspeed Labor Report CSV.

File structure:
  Line 1: "Labor Report - Bar Arbolada"
  Line 2: "02-04-2026 to 02-04-2026"
  Line 3: "Employee Totals"
  Line 4: Employee Totals column headers
  Lines 5+: Employee total rows (one per employee)
  (blank line)
  "Timecards" line
  Timecards column headers
  Timecard rows (individual shifts) with employee total rows interspersed

We import only the Timecards section (individual shift data).
The Employee Totals are summary rows derivable from timecards.

Key challenge: Timecard data has "total" summary rows interspersed
  (e.g., ",,,,,BAR 2 BAR 2 Total,,14.21,...")
  These rows have empty Employee ID and "Total" in the name.
  We skip them.
"""

import csv
from io import StringIO
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.models import PosLabor
from src.importers.base import (
    file_hash,
    check_duplicate,
    create_import_log,
    read_csv_lines,
    parse_date_range_from_header,
    parse_datetime_str,
    parse_date_str,
    safe_decimal,
    safe_int,
)


def normalize_role(value: str | None) -> str:
    """Normalize role strings so importer and DB dedupe use the same key."""
    return (value or "").strip()


def import_labor_report(session: Session, filepath: str | Path) -> int:
    """Import individual timecard records from Lightspeed Labor Report."""
    filepath = Path(filepath)
    fhash = file_hash(filepath)

    if check_duplicate(session, fhash):
        print(f"  [SKIP] Already imported: {filepath.name}")
        return 0

    lines = read_csv_lines(filepath)
    if len(lines) < 5:
        # Raise (do not return 0): import_file treats count>=0 as success, which
        # would mark the IMAP message \\Seen and permanently drop a bad attachment.
        raise ValueError(f"File too short: {filepath.name}")

    date_start, date_end = parse_date_range_from_header(lines[1])
    log = create_import_log(
        session, filepath.name, "labor", date_start, date_end, fhash
    )

    # Find "Timecards" section
    timecards_idx = None
    for i, line in enumerate(lines):
        if line.strip() == "Timecards":
            timecards_idx = i
            break

    if timecards_idx is None:
        log.status = "success"
        log.row_count = 0
        session.commit()
        print(f"  [WARN] No Timecards section found in {filepath.name}")
        return 0

    # Header is the line after "Timecards"
    header_line = lines[timecards_idx + 1]

    # Collect data lines, skipping blank and "Total" rows
    data_lines = []
    for line in lines[timecards_idx + 2:]:
        stripped = line.strip()
        if not stripped:
            continue
        # Skip total rows: they start with "," (empty employee ID) and contain "Total"
        if stripped.startswith(",") and "Total" in stripped:
            continue
        data_lines.append(line)

    csv_text = header_line + "\n" + "\n".join(data_lines)
    reader = csv.DictReader(StringIO(csv_text))

    count = 0
    seen_shifts = set()  # Track dedup keys within this batch
    seen_shift_roles: dict[tuple[str, str, str, str, str], set[str]] = {}

    for row in reader:
        last_name = row.get("Last Name", "").strip()
        first_name = row.get("First Name", "").strip()

        # Skip if no name (empty/total row that slipped through)
        if not last_name and not first_name:
            continue

        employee_id = row.get("Employee ID", "").strip() or None
        shift_date = parse_date_str(row.get("Date", ""))

        # Handle "No-Shift" entries (employee has sales but no clock-in)
        shift_start_raw = row.get("ShiftStart", "").strip()
        shift_end_raw = row.get("ShiftEnd", "").strip()
        shift_start = None if shift_start_raw.lower() == "no-shift" else parse_datetime_str(shift_start_raw)
        shift_end = None if shift_end_raw.lower() == "no-shift" else parse_datetime_str(shift_end_raw)
        normalized_role = normalize_role(row.get("Role"))

        shift_identity = (employee_id or "", last_name, first_name, str(shift_date), str(shift_start))
        prior_roles = seen_shift_roles.setdefault(shift_identity, set())
        if prior_roles and normalized_role not in prior_roles:
            prior_roles_label = ", ".join(
                role if role else "(blank role)" for role in sorted(prior_roles)
            )
            current_role_label = normalized_role or "(blank role)"
            print(
                "  [WARN] Multiple roles for same shift key: "
                f"{first_name} {last_name} on {shift_date} at {shift_start} "
                f"({prior_roles_label} -> {current_role_label})"
            )
        prior_roles.add(normalized_role)

        # In-batch dedup: skip only if we've already seen this exact shift+role
        dedup_key = shift_identity + (normalized_role,)
        if dedup_key in seen_shifts:
            continue

        labor = PosLabor(
            employee_id=employee_id,
            last_name=last_name,
            first_name=first_name,
            role=normalized_role or None,
            shift_date=shift_date,
            shift_start=shift_start,
            shift_end=shift_end,
            reg_hours=safe_decimal(row.get("Reg Hrs")),
            ot_hours=safe_decimal(row.get("1.5x Hrs")),
            pay_per_hour=safe_decimal(row.get("PayPerHour")),
            blended_pay_per_hour=safe_decimal(row.get("Blended Pay/Hr")),
            total_pay=safe_decimal(row.get("Total Pay")),
            net_sales=safe_decimal(row.get("Net Sales")),
            cash_tips=safe_decimal(row.get("Cash Tips")),
            credit_tips=safe_decimal(row.get("Credit Tips")),
            total_tips=safe_decimal(row.get("Total Tips")),
            trading_day=shift_date or date_start,
            import_log_id=log.id,
        )

        # Dedup check against database
        existing = (
            session.query(PosLabor)
            .filter(
                PosLabor.employee_id == employee_id,
                PosLabor.last_name == last_name,
                PosLabor.first_name == first_name,
                PosLabor.shift_date == shift_date,
                PosLabor.shift_start == shift_start,
                func.coalesce(func.trim(PosLabor.role), "") == normalized_role,
            )
            .first()
        )

        if existing:
            # Update
            for attr in [
                "role", "shift_end", "reg_hours", "ot_hours",
                "pay_per_hour", "blended_pay_per_hour", "total_pay", "net_sales",
                "cash_tips", "credit_tips", "total_tips",
            ]:
                setattr(existing, attr, getattr(labor, attr))
        else:
            session.add(labor)
            session.flush()  # Flush to prevent in-batch unique violations

        seen_shifts.add(dedup_key)
        count += 1

    log.row_count = count
    log.status = "success"
    session.commit()
    print(f"  [OK] Imported {count} timecards for {date_start}")
    return count
