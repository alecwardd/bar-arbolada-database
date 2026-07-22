"""
Base importer utilities.

Shared logic for all CSV parsers:
  - File hash calculation (SHA-256) for deduplication
  - Report date extraction from filenames and headers
  - Import log creation
  - Section detection for multi-section Lightspeed CSVs
"""

import hashlib
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional, Union

from sqlalchemy.orm import Session

from src.models import ImportLog


def file_hash(filepath: str | Path) -> str:
    """Compute SHA-256 hash of file contents for deduplication."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def check_duplicate(session: Session, fhash: str) -> Optional[ImportLog]:
    """
    Check if a file has already been imported (by content hash).

    Only ``success``/``duplicate`` rows count as "already imported". A prior
    ``error`` row must NOT block a retry: re-sending the identical bytes should
    import again, matching the pre-honest-logging behaviour where a failed import
    was rolled back and left no trace.
    """
    return (
        session.query(ImportLog)
        .filter(
            ImportLog.file_hash == fhash,
            ImportLog.status.in_(("success", "duplicate")),
        )
        .first()
    )


def find_successful_import(session: Session, fhash: str) -> Optional[ImportLog]:
    """
    Return an existing *successful* import for this content hash, if any.

    ``check_duplicate`` also matches ``duplicate`` rows, so archiving and
    "already imported cleanly" decisions must look specifically for a success.
    """
    return (
        session.query(ImportLog)
        .filter(ImportLog.file_hash == fhash, ImportLog.status == "success")
        .first()
    )


def create_import_log(
    session: Session,
    filename: str,
    import_type: str,
    report_date_start: Optional[date] = None,
    report_date_end: Optional[date] = None,
    file_hash_val: Optional[str] = None,
) -> ImportLog:
    """Create a new import log entry."""
    log = ImportLog(
        filename=filename,
        import_type=import_type,
        report_date_start=report_date_start,
        report_date_end=report_date_end,
        file_hash=file_hash_val,
        status="pending",
    )
    session.add(log)
    session.flush()  # Get the ID without committing
    return log


def record_duplicate_log(
    session: Session,
    filename: str,
    import_type: str,
    file_hash_val: Optional[str] = None,
) -> ImportLog:
    """
    Persist a ``status='duplicate'`` ImportLog row for a file skipped by the
    content-hash guard.

    Importers return early (before ``create_import_log``) when a file has already
    been imported, so without this the Import Operations page never learns a
    duplicate arrived. Committed in its own right so it survives regardless of the
    caller's transaction state.
    """
    log = ImportLog(
        filename=filename,
        import_type=import_type,
        file_hash=file_hash_val,
        status="duplicate",
        row_count=0,
    )
    session.add(log)
    session.commit()
    return log


def record_error_log(
    session: Session,
    filename: str,
    import_type: str,
    error_message: str,
    file_hash_val: Optional[str] = None,
) -> ImportLog:
    """
    Persist a ``status='error'`` ImportLog row (with ``error_message``) for a file
    that failed to import.

    Failures were previously rolled back (discarding the ``pending`` row) or
    returned early with only a console print, so the Import Operations page showed
    only successes. This is committed on its own transaction; callers that hit an
    exception should ``rollback()`` their data work first, then call this.
    """
    log = ImportLog(
        filename=filename,
        import_type=import_type,
        file_hash=file_hash_val,
        status="error",
        error_message=(error_message or "")[:2000],
        row_count=0,
    )
    session.add(log)
    session.commit()
    return log


def parse_date_range_from_header(line: str) -> tuple[Optional[date], Optional[date]]:
    """
    Parse date range from Lightspeed CSV header line.

    Examples:
        '02-04-2026 to 02-04-2026'  -> (date(2026, 2, 4), date(2026, 2, 4))
    """
    match = re.search(r"(\d{2}-\d{2}-\d{4})\s+to\s+(\d{2}-\d{2}-\d{4})", line)
    if match:
        start = datetime.strptime(match.group(1), "%m-%d-%Y").date()
        end = datetime.strptime(match.group(2), "%m-%d-%Y").date()
        return start, end
    return None, None


def parse_date_range_from_filename(filename: str) -> tuple[Optional[date], Optional[date]]:
    """
    Parse date range from Lightspeed export filename.

    Examples:
        'sales-report--2026-02-04-to-2026-02-04--example-bar.csv'
            -> (date(2026, 2, 4), date(2026, 2, 4))
        'Category list - 2026-02-06 - Example Bar.csv'
            -> (date(2026, 2, 6), date(2026, 2, 6))
    """
    # Pattern 1: report--YYYY-MM-DD-to-YYYY-MM-DD--
    match = re.search(r"(\d{4}-\d{2}-\d{2})-to-(\d{4}-\d{2}-\d{2})", filename)
    if match:
        start = datetime.strptime(match.group(1), "%Y-%m-%d").date()
        end = datetime.strptime(match.group(2), "%Y-%m-%d").date()
        return start, end

    # Pattern 2: list - YYYY-MM-DD - (catalog exports, single date)
    match = re.search(r"(\d{4}-\d{2}-\d{2})", filename)
    if match:
        d = datetime.strptime(match.group(1), "%Y-%m-%d").date()
        return d, d

    return None, None


def parse_datetime_str(s: str) -> Optional[datetime]:
    """
    Parse Lightspeed datetime strings.

    Examples:
        '2/4/2026 10:55 pm' -> datetime(2026, 2, 4, 22, 55)
        '2/5/2026 12:16 am' -> datetime(2026, 2, 5, 0, 16)
    """
    if not s or not s.strip():
        return None
    s = s.strip()

    for fmt in [
        "%m/%d/%Y %I:%M %p",
        "%m/%d/%Y %I:%M:%S %p",
        "%m/%d/%Y %H:%M",
        "%m/%d/%Y",
        "%Y-%m-%d",
    ]:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def parse_date_str(s: str) -> Optional[date]:
    """Parse date string (YYYY-MM-DD or M/D/YYYY)."""
    dt = parse_datetime_str(s)
    return dt.date() if dt else None


def safe_decimal(val: Union[str, int, float, Decimal, None]) -> Optional[Decimal]:
    """Safely convert a CSV/cell value to Decimal, returning None for empty/invalid.

    Uses Decimal(string) — never float — so money and hours keep exact scale
    into Numeric columns.
    """
    if val is None:
        return None
    if isinstance(val, Decimal):
        return val
    if isinstance(val, bool):
        return None
    if isinstance(val, int):
        return Decimal(val)
    s = str(val).strip().replace(",", "")
    if not s:
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def safe_int(val: Union[str, int, float, Decimal, None]) -> Optional[int]:
    """Safely convert string to int, returning None for empty/invalid."""
    d = safe_decimal(val)
    return int(d) if d is not None else None


def safe_bool(val: str) -> Optional[bool]:
    """Convert Lightspeed Yes/No/0/1 to boolean."""
    if val is None:
        return None
    val = str(val).strip().lower()
    if val in ("yes", "1", "true"):
        return True
    if val in ("no", "0", "false"):
        return False
    return None


def read_csv_lines(filepath: str | Path) -> list[str]:
    """Read CSV file and return lines, handling BOM and encoding issues."""
    filepath = Path(filepath)
    for encoding in ["utf-8-sig", "utf-8", "latin-1"]:
        try:
            return filepath.read_text(encoding=encoding).splitlines()
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Could not decode file: {filepath}")


def detect_report_type(filepath: str | Path) -> str:
    """
    Detect report type from filename or first line.

    Returns one of:
      'categories', 'items', 'modifier_groups', 'modifiers',
      'display_groups', 'sales', 'checks', 'product_mix',
      'comps', 'voids', 'payments', 'labor'
    """
    name = Path(filepath).name.lower()

    type_map = {
        "category list": "categories",
        "item list": "items",
        "modifier groups": "modifier_groups",
        "modifier list": "modifiers",
        "display groups": "display_groups",
        "sales-report": "sales",
        "checks-report": "checks",
        "product-mix-report": "product_mix",
        "comps-report": "comps",
        "voids-report": "voids",
        "payments-report": "payments",
        "labor-report": "labor",
    }

    for pattern, rtype in type_map.items():
        if pattern in name:
            return rtype

    # Fallback: check first line
    lines = read_csv_lines(filepath)
    if lines:
        first = lines[0].lower()
        for keyword in ["sales report", "check detail", "product mix", "comps report",
                        "voids report", "payments report", "labor report"]:
            if keyword in first:
                for pattern, rtype in type_map.items():
                    if keyword.split()[0] in pattern:
                        return rtype

    return "unknown"
