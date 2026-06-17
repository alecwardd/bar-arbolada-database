"""
Parsers for Lightspeed Comps Report and Voids Report CSVs.

Both have similar structure:
  Line 1: "[Report Name] - Bar Arbolada"
  Line 2: "02-04-2026 to 02-04-2026"
  Line 3: "Details"
  Line 4: (blank)
  Line 5: Column headers
  Lines 6+: Data rows

Comps columns: Date,Comp reason,Check owner,Authorized by,Check Number,Type,Item,Amount,Note
Voids columns: Date,Void reason,Check owner,Authorized by,Check Number,Item,Amount,Note
"""

import csv
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta
from io import StringIO
from pathlib import Path

from sqlalchemy.orm import Session

from src.models import PosComp, PosVoid
from src.importers.base import (
    file_hash,
    check_duplicate,
    create_import_log,
    read_csv_lines,
    parse_date_range_from_header,
    parse_datetime_str,
    safe_decimal,
)


def _derive_trading_day(dt, fallback_date):
    """
    Derive the trading day from a comp/void datetime.

    Bar trading days end around 4-6am, so events between midnight and
    6am belong to the PREVIOUS calendar day's trading period.
    """
    if dt is None:
        return fallback_date
    if dt.hour < 6:
        return (dt - timedelta(days=1)).date()
    return dt.date()


def _norm(s: str | None) -> str:
    return (s or "").strip()


def _amount_key(val) -> int | None:
    """
    Normalize amount for deduping.

    DB stores amounts as Numeric(10,2). CSV parsing uses floats.
    Convert to integer cents using decimal quantization to avoid float noise.
    """
    if val is None:
        return None
    try:
        d = Decimal(str(val)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        return None
    return int(d * 100)


def _void_key(
    void_dt,
    void_reason: str | None,
    check_owner: str | None,
    authorized_by: str | None,
    check_number: str | None,
    item_name: str | None,
    amount,
    note: str | None,
) -> tuple:
    return (
        void_dt.isoformat(sep=" ") if void_dt else None,
        _norm(void_reason),
        _norm(check_owner),
        _norm(authorized_by),
        _norm(check_number),
        _norm(item_name),
        _amount_key(amount),
        _norm(note),
    )


def _comp_key(
    comp_dt,
    comp_reason: str | None,
    check_owner: str | None,
    authorized_by: str | None,
    check_number: str | None,
    comp_type: str | None,
    item_name: str | None,
    amount,
    note: str | None,
) -> tuple:
    return (
        comp_dt.isoformat(sep=" ") if comp_dt else None,
        _norm(comp_reason),
        _norm(check_owner),
        _norm(authorized_by),
        _norm(check_number),
        _norm(comp_type),
        _norm(item_name),
        _amount_key(amount),
        _norm(note),
    )


def import_comps_report(session: Session, filepath: str | Path) -> int:
    """Import a Lightspeed Comps Report CSV."""
    filepath = Path(filepath)
    fhash = file_hash(filepath)

    if check_duplicate(session, fhash):
        print(f"  [SKIP] Already imported: {filepath.name}")
        return 0

    lines = read_csv_lines(filepath)
    if len(lines) < 5:
        print(f"  [WARN] No comp data in: {filepath.name}")
        return 0

    date_start, date_end = parse_date_range_from_header(lines[1])
    log = create_import_log(
        session, filepath.name, "comps", date_start, date_end, fhash
    )

    # Find the header line (starts with "Date,Comp reason")
    header_idx = None
    for i, line in enumerate(lines):
        if line.strip().startswith("Date,Comp reason"):
            header_idx = i
            break

    if header_idx is None:
        log.status = "success"
        log.row_count = 0
        session.commit()
        print(f"  [OK] No comps found in {filepath.name}")
        return 0

    # Parse CSV from header line onward
    csv_text = "\n".join(lines[header_idx:])
    reader = csv.DictReader(StringIO(csv_text))

    # Row-level dedupe: annual/weekly/daily exports can overlap.
    # Files can also contain rows outside the header range, so use a buffer.
    # Use a large window because some Lightspeed exports include rows
    # outside the stated header date range (often spilling into next year).
    buffer_days = 400
    existing_keys = set()
    try:
        start_dt = (date_start - timedelta(days=buffer_days)) if date_start else None
        end_dt = (date_end + timedelta(days=buffer_days)) if date_end else None
        if start_dt and end_dt:
            existing_rows = (
                session.query(PosComp)
                .with_entities(
                    PosComp.comp_date,
                    PosComp.comp_reason,
                    PosComp.check_owner,
                    PosComp.authorized_by,
                    PosComp.check_number,
                    PosComp.comp_type,
                    PosComp.item_name,
                    PosComp.amount,
                    PosComp.note,
                )
                .filter(PosComp.comp_date.isnot(None))
                .filter(PosComp.comp_date >= start_dt)
                .filter(PosComp.comp_date <= end_dt)
                .all()
            )
            for r in existing_rows:
                existing_keys.add(
                    _comp_key(
                        r[0],
                        r[1],
                        r[2],
                        r[3],
                        r[4],
                        r[5],
                        r[6],
                        r[7],
                        r[8],
                    )
                )
    except Exception:
        existing_keys = set()

    count = 0
    skipped = 0
    for row in reader:
        comp_date_str = row.get("Date", "").strip()
        if not comp_date_str:
            continue

        comp_dt = parse_datetime_str(comp_date_str)
        amount = safe_decimal(row.get("Amount"))
        key = _comp_key(
            comp_dt,
            row.get("Comp reason"),
            row.get("Check owner"),
            row.get("Authorized by"),
            row.get("Check Number"),
            row.get("Type"),
            row.get("Item"),
            amount,
            row.get("Note"),
        )
        if key in existing_keys:
            skipped += 1
            continue
        existing_keys.add(key)

        comp = PosComp(
            comp_date=comp_dt,
            comp_reason=row.get("Comp reason", "").strip() or None,
            check_owner=row.get("Check owner", "").strip() or None,
            authorized_by=row.get("Authorized by", "").strip() or None,
            check_number=row.get("Check Number", "").strip() or None,
            comp_type=row.get("Type", "").strip() or None,
            item_name=row.get("Item", "").strip() or None,
            amount=amount,
            note=row.get("Note", "").strip() or None,
            trading_day=_derive_trading_day(comp_dt, date_start),
            import_log_id=log.id,
        )
        session.add(comp)
        count += 1

    log.row_count = count
    log.status = "success"
    session.commit()
    if skipped:
        print(
            f"  [OK] Imported {count} comps for {date_start} "
            f"(skipped {skipped} duplicates)"
        )
    else:
        print(f"  [OK] Imported {count} comps for {date_start}")
    return count


def import_voids_report(session: Session, filepath: str | Path) -> int:
    """Import a Lightspeed Voids Report CSV."""
    filepath = Path(filepath)
    fhash = file_hash(filepath)

    if check_duplicate(session, fhash):
        print(f"  [SKIP] Already imported: {filepath.name}")
        return 0

    lines = read_csv_lines(filepath)
    if len(lines) < 5:
        print(f"  [WARN] No void data in: {filepath.name}")
        return 0

    date_start, date_end = parse_date_range_from_header(lines[1])
    log = create_import_log(
        session, filepath.name, "voids", date_start, date_end, fhash
    )

    # Find the header line (starts with "Date,Void reason")
    header_idx = None
    for i, line in enumerate(lines):
        if line.strip().startswith("Date,Void reason"):
            header_idx = i
            break

    if header_idx is None:
        log.status = "success"
        log.row_count = 0
        session.commit()
        print(f"  [OK] No voids found in {filepath.name}")
        return 0

    # Parse CSV from header line onward
    csv_text = "\n".join(lines[header_idx:])
    reader = csv.DictReader(StringIO(csv_text))

    # Row-level dedupe: annual/weekly/daily exports can overlap.
    # Files can also contain rows outside the header range, so use a buffer.
    # Use a large window because some Lightspeed exports include rows
    # outside the stated header date range (often spilling into next year).
    buffer_days = 400
    existing_keys = set()
    try:
        start_dt = (date_start - timedelta(days=buffer_days)) if date_start else None
        end_dt = (date_end + timedelta(days=buffer_days)) if date_end else None
        if start_dt and end_dt:
            existing_rows = (
                session.query(PosVoid)
                .with_entities(
                    PosVoid.void_date,
                    PosVoid.void_reason,
                    PosVoid.check_owner,
                    PosVoid.authorized_by,
                    PosVoid.check_number,
                    PosVoid.item_name,
                    PosVoid.amount,
                    PosVoid.note,
                )
                .filter(PosVoid.void_date.isnot(None))
                .filter(PosVoid.void_date >= start_dt)
                .filter(PosVoid.void_date <= end_dt)
                .all()
            )
            for r in existing_rows:
                existing_keys.add(
                    _void_key(
                        r[0],
                        r[1],
                        r[2],
                        r[3],
                        r[4],
                        r[5],
                        r[6],
                        r[7],
                    )
                )
    except Exception:
        existing_keys = set()

    count = 0
    skipped = 0
    for row in reader:
        void_date_str = row.get("Date", "").strip()
        if not void_date_str:
            continue

        void_dt = parse_datetime_str(void_date_str)
        amount = safe_decimal(row.get("Amount"))
        key = _void_key(
            void_dt,
            row.get("Void reason"),
            row.get("Check owner"),
            row.get("Authorized by"),
            row.get("Check Number"),
            row.get("Item"),
            amount,
            row.get("Note"),
        )
        if key in existing_keys:
            skipped += 1
            continue
        existing_keys.add(key)

        void = PosVoid(
            void_date=void_dt,
            void_reason=row.get("Void reason", "").strip() or None,
            check_owner=row.get("Check owner", "").strip() or None,
            authorized_by=row.get("Authorized by", "").strip() or None,
            check_number=row.get("Check Number", "").strip() or None,
            item_name=row.get("Item", "").strip() or None,
            amount=amount,
            note=row.get("Note", "").strip() or None,
            trading_day=_derive_trading_day(void_dt, date_start),
            import_log_id=log.id,
        )
        session.add(void)
        count += 1

    log.row_count = count
    log.status = "success"
    session.commit()
    if skipped:
        print(
            f"  [OK] Imported {count} voids for {date_start} "
            f"(skipped {skipped} duplicates)"
        )
    else:
        print(f"  [OK] Imported {count} voids for {date_start}")
    return count
