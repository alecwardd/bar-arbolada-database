"""
Import POS reports from an email source into the database.

This script downloads report CSV attachments, stores them in a staging folder,
reuses the existing CSV importer pipeline, and writes an import health snapshot.

Examples:
    python scripts/import_from_email.py
    python scripts/import_from_email.py --source local --local-source-dir raw-csvs-before-pos-changes
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.import_all import import_directory
from src.config import PROJECT_ROOT, get_session
from src.email_sources import LocalDirectoryEmailSource, ImapEmailSource, save_attachments
from src.operations.import_status import write_snapshot
from src.models import (
    ImportLog,
    PosCheck,
    PosDailySales,
    PosHourlySales,
    PosLabor,
    PosPayment,
    PosProductMix,
)


EXPECTED_REPORT_TYPES = ["sales", "checks", "product_mix", "comps", "voids", "payments", "labor"]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import daily POS reports from email attachments.")
    parser.add_argument(
        "--source",
        choices=["imap", "local"],
        default=os.getenv("EMAIL_SOURCE", "imap"),
        help="Email source provider (default from EMAIL_SOURCE or 'imap').",
    )
    parser.add_argument(
        "--staging-dir",
        default=os.getenv("EMAIL_STAGING_DIR", str(PROJECT_ROOT / "data" / "raw" / "email-inbox")),
        help="Where downloaded CSV attachments are written before import.",
    )
    parser.add_argument(
        "--local-source-dir",
        default=str(PROJECT_ROOT / "raw-csvs-before-pos-changes"),
        help="Directory used when --source local.",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=int(os.getenv("EMAIL_IMPORT_LOOKBACK_DAYS", "7")),
        help="Lookback window for missing-day checks.",
    )
    parser.add_argument(
        "--archive",
        dest="archive",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Archive imported staging CSVs into an imported/ subfolder (default: enabled).",
    )
    parser.add_argument(
        "--archive-subdir",
        default="imported",
        help="Archive subfolder name inside staging-dir (default: imported).",
    )
    parser.add_argument(
        "--mark-processed",
        dest="mark_processed",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Mark source messages processed after import (default: enabled).",
    )
    parser.add_argument(
        "--status-file",
        default=str(PROJECT_ROOT / "reports" / "email_import_status.json"),
        help="Path for JSON status output.",
    )
    return parser.parse_args()


def _build_source(args: argparse.Namespace):
    if args.source == "local":
        return LocalDirectoryEmailSource(Path(args.local_source_dir))

    host = os.getenv("EMAIL_IMAP_HOST", "").strip()
    user = os.getenv("EMAIL_IMAP_USER", "").strip()
    password = os.getenv("EMAIL_IMAP_PASSWORD", "").strip()
    mailbox = os.getenv("EMAIL_IMAP_MAILBOX", "INBOX")
    subject_filter = os.getenv("EMAIL_SUBJECT_FILTER")
    port = int(os.getenv("EMAIL_IMAP_PORT", "993"))

    if not host or not user or not password:
        raise ValueError(
            "IMAP source selected, but EMAIL_IMAP_HOST/EMAIL_IMAP_USER/EMAIL_IMAP_PASSWORD are not fully set."
        )

    return ImapEmailSource(
        host=host,
        username=user,
        password=password,
        port=port,
        mailbox=mailbox,
        subject_contains=subject_filter,
    )


def _date_window(lookback_days: int) -> tuple[date, date]:
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=max(0, lookback_days - 1))
    return start, end


def _missing_report_days(lookback_days: int) -> dict[str, list[str]]:
    start, end = _date_window(lookback_days)
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]

    session = get_session()
    try:
        # For core datasets, infer missing days from destination tables.
        # For comps/voids (which may legitimately have zero rows on a day),
        # infer from import logs to avoid false gaps.
        gaps: dict[str, list[str]] = {}
        table_presence_fields = {
            "sales": PosDailySales.trading_day,
            "checks": PosCheck.trading_day,
            "product_mix": PosProductMix.report_end_date,
            "payments": PosPayment.trading_day,
            "labor": PosLabor.shift_date,
        }

        for rtype, field in table_presence_fields.items():
            present = {
                d
                for (d,) in (
                    session.query(field)
                    .filter(field >= start, field <= end)
                    .distinct()
                    .all()
                )
                if d is not None
            }
            gaps[rtype] = [d.isoformat() for d in days if d not in present]

        for rtype in ("comps", "voids"):
            present = {
                d
                for (d,) in (
                    session.query(ImportLog.report_date_end)
                    .filter(
                        ImportLog.import_type == rtype,
                        ImportLog.status == "success",
                        ImportLog.report_date_end >= start,
                        ImportLog.report_date_end <= end,
                    )
                    .distinct()
                    .all()
                )
                if d is not None
            }
            gaps[rtype] = [d.isoformat() for d in days if d not in present]

        return gaps
    finally:
        session.close()


def _coverage_snapshot() -> dict[str, str | None]:
    session = get_session()
    try:
        return {
            "daily_sales_max": _iso(session.query(func.max(PosDailySales.trading_day)).scalar()),
            "hourly_sales_max": _iso(session.query(func.max(PosHourlySales.trading_day)).scalar()),
            "checks_max": _iso(session.query(func.max(PosCheck.trading_day)).scalar()),
            "payments_max": _iso(session.query(func.max(PosPayment.trading_day)).scalar()),
            "labor_max": _iso(session.query(func.max(PosLabor.shift_date)).scalar()),
        }
    finally:
        session.close()


def _iso(d) -> str | None:
    return d.isoformat() if d else None


def main() -> None:
    args = _parse_args()
    source = _build_source(args)
    staging_root = Path(args.staging_dir)
    staging_root.mkdir(parents=True, exist_ok=True)
    run_staging_dir = staging_root / f"run-{date.today().isoformat()}-{uuid4().hex[:8]}"
    run_staging_dir.mkdir(parents=True, exist_ok=True)

    print(f"[INFO] Source: {args.source}")
    print(f"[INFO] Staging root: {staging_root}")
    print(f"[INFO] Run staging dir: {run_staging_dir}")

    messages = source.list_new_messages()
    saved_paths, processed_message_ids = save_attachments(messages, run_staging_dir)

    print(f"[INFO] Messages fetched: {len(messages)}")
    print(f"[INFO] CSV attachments saved: {len(saved_paths)}")

    if saved_paths:
        import_directory(run_staging_dir, archive=args.archive, archive_subdir=args.archive_subdir)

        if args.mark_processed:
            source.mark_processed(processed_message_ids)
            print(f"[INFO] Marked {len(processed_message_ids)} message(s) as processed")
    else:
        print("[INFO] No new CSV attachments to import")

    status_payload = {
        "source": args.source,
        "staging_root": str(staging_root),
        "run_staging_dir": str(run_staging_dir),
        "messages_fetched": len(messages),
        "csv_attachments_saved": len(saved_paths),
        "lookback_days": args.lookback_days,
        "coverage_max_dates": _coverage_snapshot(),
        "missing_report_days": _missing_report_days(args.lookback_days),
        "generated_on": date.today().isoformat(),
    }

    status_file = Path(args.status_file)
    status_file.parent.mkdir(parents=True, exist_ok=True)
    status_file.write_text(json.dumps(status_payload, indent=2), encoding="utf-8")
    print(f"[INFO] Wrote status snapshot: {status_file}")

    snapshot_session = get_session()
    try:
        write_snapshot(snapshot_session, status_payload)
        print("[INFO] Wrote import status snapshot to database")
    finally:
        snapshot_session.close()


if __name__ == "__main__":
    main()
