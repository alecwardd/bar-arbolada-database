"""
Tests that ImportLog now reflects reality: duplicate skips and failures are
persisted with honest statuses instead of vanishing.

Before the fix, import_logs only ever contained ``success`` rows — duplicate
skips returned before any log was written, and exceptions were rolled back
(discarding the ``pending`` row). The Import Operations page therefore never
showed a duplicate or an error.
"""

from pathlib import Path

import scripts.import_all as ia
from src.models import ImportLog
from src.importers.payments_report import import_payments_report


_HEADER = "Status,Tender,Tender Account,Date,Check No.,Trading Day,Payment,Tip,Total,Server"
_ROW = "Captured,Credit,Visa 4727,2/4/2026 10:55 pm,101,2/4/2026,50.00,10.00,60.00,Alice"


def _valid_payments_file(path: Path) -> Path:
    lines = [
        "Payments Report - Bar Arbolada",
        "02-04-2026 to 02-04-2026",
        "Totals", "a", "b", "c", "d", "e", "f",
        "Payments List",
        _HEADER,
        _ROW,
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def test_duplicate_file_records_duplicate_log(sqlite_session, tmp_path):
    f = _valid_payments_file(tmp_path / "payments-report--2026-02-04-to-2026-02-04--bar.csv")

    assert ia.import_file(sqlite_session, f, archive_dir=None) is True
    # Second pass: same bytes → recorded as a duplicate arrival, not re-imported.
    assert ia.import_file(sqlite_session, f, archive_dir=None) is True

    statuses = [row.status for row in sqlite_session.query(ImportLog).all()]
    assert statuses.count("success") == 1
    assert statuses.count("duplicate") == 1


def test_file_too_short_records_error_log(sqlite_session, tmp_path):
    f = tmp_path / "payments-report--2026-02-04-to-2026-02-04--bar.csv"
    f.write_text("Payments Report - Bar Arbolada\n02-04-2026 to 02-04-2026\nTotals\n", encoding="utf-8")

    assert import_payments_report(sqlite_session, f) == 0

    errors = sqlite_session.query(ImportLog).filter(ImportLog.status == "error").all()
    assert len(errors) == 1
    assert errors[0].import_type == "payments"
    assert "File too short" in (errors[0].error_message or "")


def test_errored_file_can_be_retried_after_resend(sqlite_session, tmp_path, monkeypatch):
    # A transient failure records an error row carrying the file hash. Re-sending
    # the IDENTICAL bytes must import (not be skipped as a duplicate) — otherwise a
    # one-off failure would poison that file forever.
    f = _valid_payments_file(tmp_path / "payments-report--2026-02-04-to-2026-02-04--bar.csv")

    def boom(session, filepath):
        raise ValueError("transient db blip")

    monkeypatch.setitem(ia.IMPORTERS, "payments", boom)
    assert ia.import_file(sqlite_session, f, archive_dir=None) is False  # error row (same hash)

    monkeypatch.undo()  # failure clears; same file arrives again
    assert ia.import_file(sqlite_session, f, archive_dir=None) is True
    assert sqlite_session.query(ImportLog).filter(ImportLog.status == "success").count() == 1


def test_import_file_exception_records_error_log(sqlite_session, tmp_path, monkeypatch):
    f = _valid_payments_file(tmp_path / "payments-report--2026-02-04-to-2026-02-04--bar.csv")

    def boom(session, filepath):
        raise ValueError("kaboom during import")

    monkeypatch.setitem(ia.IMPORTERS, "payments", boom)

    assert ia.import_file(sqlite_session, f, archive_dir=None) is False

    errors = sqlite_session.query(ImportLog).filter(ImportLog.status == "error").all()
    assert len(errors) == 1
    assert errors[0].import_type == "payments"
    assert "kaboom" in (errors[0].error_message or "")
