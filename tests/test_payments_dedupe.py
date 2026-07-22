"""
Regression tests for the payments double-insert bug.

Before the fix, the payments importer deduped only by file content hash, so the
same day arriving in both a daily and a weekly export (different bytes → different
hashes) double-inserted every payment row. These tests prove overlapping exports
no longer double-insert, while the file-hash fast-path still short-circuits an
identical re-send.
"""

from pathlib import Path

from src.models import PosPayment
from src.importers.payments_report import import_payments_report


_HEADER = "Status,Tender,Tender Account,Date,Check No.,Trading Day,Payment,Tip,Total,Server"
_ROW_101 = "Captured,Credit,Visa 4727,2/4/2026 10:55 pm,101,2/4/2026,50.00,10.00,60.00,Alice"
_ROW_102 = "Captured,Cash,,2/4/2026 11:10 pm,102,2/4/2026,50.00,10.00,60.00,Bob"
_ROW_103 = "Captured,Credit,MC 3655,2/5/2026 12:16 am,103,2/4/2026,30.00,5.00,35.00,Alice"


def _write(path: Path, header_range: str, rows: list[str]) -> Path:
    lines = [
        "Payments Report - Bar Arbolada",
        header_range,
        "Totals",
        "Total Payments,100.00",
        "Total Tips,20.00",
        "filler-a",
        "filler-b",
        "filler-c",
        "filler-d",
        "Payments List",
        _HEADER,
        *rows,
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def test_overlapping_daily_and_weekly_do_not_double_insert(sqlite_session, tmp_path):
    daily = _write(tmp_path / "payments-report--2026-02-04-to-2026-02-04--bar.csv",
                   "02-04-2026 to 02-04-2026", [_ROW_101, _ROW_102])
    weekly = _write(tmp_path / "payments-report--2026-02-01-to-2026-02-07--bar.csv",
                    "02-01-2026 to 02-07-2026", [_ROW_101, _ROW_102, _ROW_103])

    inserted_daily = import_payments_report(sqlite_session, daily)
    assert inserted_daily == 2
    assert sqlite_session.query(PosPayment).count() == 2

    # The weekly export repeats the two daily rows and adds one new one.
    inserted_weekly = import_payments_report(sqlite_session, weekly)
    assert inserted_weekly == 1  # only the genuinely-new row
    assert sqlite_session.query(PosPayment).count() == 3


def test_identical_file_is_hash_skipped(sqlite_session, tmp_path):
    daily = _write(tmp_path / "payments-report--2026-02-04-to-2026-02-04--bar.csv",
                   "02-04-2026 to 02-04-2026", [_ROW_101, _ROW_102])

    assert import_payments_report(sqlite_session, daily) == 2
    assert sqlite_session.query(PosPayment).count() == 2

    # Re-importing the exact same bytes is caught by the file-hash guard.
    assert import_payments_report(sqlite_session, daily) == 0
    assert sqlite_session.query(PosPayment).count() == 2
