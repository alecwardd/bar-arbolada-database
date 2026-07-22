"""
Read-only detector for duplicated payment rows.

Historically the payments importer deduped only by file content hash, so a day
that arrived in both a daily and a weekly/annual export could double-insert every
payment row (the files differ, so their hashes differ). The importer now dedupes
at row level, but rows inserted BEFORE that fix may still be duplicated.

This script groups existing ``pos_payments`` rows by the same natural key the
importer uses and reports any group with more than one row. It is strictly
READ-ONLY: it never updates or deletes anything. Review the output, and if you
want the surviving-vs-duplicate rows cleaned up, decide on that separately.

Usage:
    python scripts/find_duplicate_payments.py
    python scripts/find_duplicate_payments.py --csv reports/payment_duplicates.csv
    python scripts/find_duplicate_payments.py --start 2026-01-01 --end 2026-03-31
"""

import sys
import csv as csv_mod
import argparse
from pathlib import Path
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import get_session
from src.models import PosPayment


def _norm(s) -> str:
    return (s or "").strip() if isinstance(s, str) else ("" if s is None else str(s).strip())


def _cents(val) -> int | None:
    if val is None:
        return None
    try:
        return int(Decimal(str(val)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100)
    except Exception:
        return None


def _key(p: PosPayment) -> tuple:
    """Same natural key the importer uses to identify one payment transaction."""
    return (
        p.payment_date.isoformat(sep=" ") if p.payment_date else None,
        _norm(p.check_number),
        _norm(p.tender_type),
        _norm(p.tender_account),
        _norm(p.status),
        _cents(p.payment_amount),
        _cents(p.tip_amount),
        _cents(p.total_amount),
        _norm(p.server),
    )


def find_duplicates(start=None, end=None):
    session = get_session()
    try:
        query = session.query(PosPayment)
        if start:
            query = query.filter(PosPayment.trading_day >= start)
        if end:
            query = query.filter(PosPayment.trading_day <= end)

        groups: dict[tuple, list[PosPayment]] = defaultdict(list)
        total = 0
        for p in query.all():
            total += 1
            groups[_key(p)].append(p)

        dupes = {k: rows for k, rows in groups.items() if len(rows) > 1}
        return total, dupes
    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser(
        description="READ-ONLY report of duplicate pos_payments rows (no changes are made)."
    )
    parser.add_argument("--start", help="Only inspect trading_day >= this ISO date (YYYY-MM-DD).")
    parser.add_argument("--end", help="Only inspect trading_day <= this ISO date (YYYY-MM-DD).")
    parser.add_argument("--csv", help="Optional path to write a CSV of the duplicate rows.")
    args = parser.parse_args()

    total, dupes = find_duplicates(args.start, args.end)

    dup_groups = len(dupes)
    extra_rows = sum(len(rows) - 1 for rows in dupes.values())

    print("=" * 70)
    print("Payment duplicate report (READ-ONLY — nothing was modified)")
    print("=" * 70)
    print(f"Rows inspected:        {total}")
    print(f"Duplicate key groups:  {dup_groups}")
    print(f"Redundant extra rows:  {extra_rows}")
    print("=" * 70)

    if not dupes:
        print("No duplicate payment rows detected.")
        return

    for key, rows in sorted(
        dupes.items(), key=lambda kv: kv[0][0] or "", reverse=True
    ):
        ids = ", ".join(str(r.id) for r in sorted(rows, key=lambda r: r.id))
        payment_dt, check_no, tender, _acct, status, pay_c, _tip, _tot, server = key
        amount = f"{pay_c / 100:.2f}" if pay_c is not None else "?"
        print(
            f"  x{len(rows)}  {payment_dt}  check {check_no or '-'}  {tender or '-'}  "
            f"${amount}  {status or '-'}  server={server or '-'}  ids=[{ids}]"
        )

    if args.csv:
        out = Path(args.csv)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", newline="", encoding="utf-8") as fh:
            writer = csv_mod.writer(fh)
            writer.writerow(
                [
                    "id", "trading_day", "payment_date", "check_number",
                    "tender_type", "tender_account", "status",
                    "payment_amount", "tip_amount", "total_amount", "server",
                    "import_log_id", "group_size",
                ]
            )
            for rows in dupes.values():
                for r in sorted(rows, key=lambda r: r.id):
                    writer.writerow(
                        [
                            r.id, r.trading_day, r.payment_date, r.check_number,
                            r.tender_type, r.tender_account, r.status,
                            r.payment_amount, r.tip_amount, r.total_amount, r.server,
                            r.import_log_id, len(rows),
                        ]
                    )
        print(f"\nWrote duplicate detail to: {out}")


if __name__ == "__main__":
    main()
