"""
Bookkeeper P&L vs. Internal Database Comparison
=================================================
Reads a QuickBooks-style P&L export (CSV or Excel) from raw-pl-reports/,
pulls the same period from our database, and prints a side-by-side
discrepancy report.

QuickBooks CSV exports (Reports > Profit and Loss > Export to CSV) work
out of the box. Excel exports from most other accounting platforms usually
do too -- just make sure the file has a header row with account names in
one column and dollar amounts in another.

Usage:
    # Auto-detects dates from the file header
    python scripts/compare_bookkeeper_pl.py raw-pl-reports/pl_jan_2026.csv

    # Override date range manually
    python scripts/compare_bookkeeper_pl.py raw-pl-reports/pl_jan_2026.csv \\
        --start 2026-01-01 --end 2026-01-31

    # Save report to HTML
    python scripts/compare_bookkeeper_pl.py raw-pl-reports/pl_jan_2026.csv \\
        --output reports/pl_comparison_jan_2026.html
"""

import sys
import re
import argparse
from pathlib import Path
from datetime import date, datetime
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

from src.analytics.queries import get_full_pnl, get_expenses_by_type


# ── QuickBooks line-item labels we recognize ─────────────────────────────────
# Maps patterns found in QBO exports → our internal P&L keys.
# Add more aliases here as you discover what your bookkeeper uses.

REVENUE_PATTERNS = [
    r"^total\s+income",
    r"^total\s+revenue",
    r"^net\s+revenue",
    r"^total\s+sales",
    r"^gross\s+receipts",
]

COGS_PATTERNS = [
    r"^total\s+cost\s+of\s+goods\s+sold",
    r"^total\s+cogs",
    r"^total\s+cost\s+of\s+sales",
    r"^cost\s+of\s+goods\s+sold",
]

GROSS_PROFIT_PATTERNS = [
    r"^gross\s+profit",
    r"^gross\s+margin",
]

TOTAL_EXPENSES_PATTERNS = [
    r"^total\s+expenses",
    r"^total\s+operating\s+expenses",
]

LABOR_PATTERNS = [
    r"payroll",
    r"labor",
    r"wages",
    r"salaries",
]

NET_INCOME_PATTERNS = [
    r"^net\s+(income|profit|loss|earnings)",
]

# Expense-type groupings that appear in bookkeeper files and map to our types
OPEX_CATEGORY_MAP = {
    "occupancy":          [r"rent", r"lease"],
    "energy_utility":     [r"electric", r"gas", r"water", r"sewer", r"utilities"],
    "internet_telecom":   [r"internet", r"telecom", r"cable", r"cox", r"wifi"],
    "pos_technology":     [r"lightspeed", r"pos", r"payment\s+terminal", r"square", r"toast"],
    "cc_processing":      [r"credit\s+card", r"merchant\s+services", r"processing\s+fee"],
    "cleaning":           [r"grease", r"hood\s+clean", r"cleaning\s+service"],
    "trash_waste":        [r"trash", r"dumpster", r"waste"],
    "insurance":          [r"insurance", r"liability", r"workers\s+comp"],
    "licensing":          [r"license", r"permit", r"ascap", r"bmi", r"music"],
    "repairs_maintenance": [r"repair", r"maintenance", r"hvac", r"plumbing"],
    "marketing":          [r"marketing", r"advertising", r"promo"],
    "professional_services": [r"accounting", r"bookkeeping", r"legal", r"professional"],
    "supplies_non_inventory": [r"supplies", r"cleaning\s+supplies", r"paper\s+goods"],
    "miscellaneous":      [r"misc", r"other"],
}


# ── File parsing ──────────────────────────────────────────────────────────────

def _clean_amount(raw) -> Optional[float]:
    """Convert '$1,234.56' or '(1,234.56)' or '-1234.56' to float. None if blank."""
    if raw is None:
        return None
    s = str(raw).strip().replace(",", "").replace("$", "").replace(" ", "")
    if not s or s == "-" or s.lower() in ("nan", "none", ""):
        return None
    # Parentheses = negative (accounting notation)
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except ValueError:
        return None


def _matches(text: str, patterns: list[str]) -> bool:
    t = text.strip().lower()
    return any(re.search(p, t) for p in patterns)


def _parse_qbo_csv(path: Path) -> tuple[dict, Optional[date], Optional[date]]:
    """
    Parse a QuickBooks Profit and Loss CSV export.

    QBO exports look like:
        Row 0: Company name
        Row 1: "Profit and Loss"
        Row 2: Date range string, e.g. "January 2026"
        Row 3: blank
        Row 4+: Account, Amount columns (indented subcategories with leading space)

    Returns (line_items dict, start_date, end_date).
    line_items maps lowercased label → float amount.
    """
    raw = pd.read_csv(path, header=None, dtype=str, keep_default_na=False)

    # Try to detect date range from first few rows
    start_date = end_date = None
    header_text = " ".join(str(v) for v in raw.iloc[:4].values.flatten()).lower()
    date_range_match = re.search(
        r"(\w+ \d{4})\s+(?:through|to|-)\s+(\w+ \d{4})", header_text
    )
    if date_range_match:
        try:
            d1 = datetime.strptime(date_range_match.group(1), "%B %Y")
            d2 = datetime.strptime(date_range_match.group(2), "%B %Y")
            start_date = d1.date().replace(day=1)
            # last day of end month
            import calendar
            last_day = calendar.monthrange(d2.year, d2.month)[1]
            end_date = d2.date().replace(day=last_day)
        except ValueError:
            pass
    else:
        # Single-month format
        single_match = re.search(r"(\w+ \d{4})", header_text)
        if single_match:
            try:
                import calendar
                d = datetime.strptime(single_match.group(1), "%B %Y")
                start_date = d.date().replace(day=1)
                last_day = calendar.monthrange(d.year, d.month)[1]
                end_date = d.date().replace(day=last_day)
            except ValueError:
                pass

    # Find the first row that looks like a data row (label + number)
    line_items: dict[str, float] = {}
    for _, row in raw.iterrows():
        vals = [str(v) for v in row if str(v).strip()]
        if len(vals) < 2:
            continue
        label = vals[0].strip()
        # Amount is the last non-empty cell
        amount_raw = vals[-1]
        amount = _clean_amount(amount_raw)
        if label and amount is not None:
            line_items[label.lower()] = amount

    return line_items, start_date, end_date


def _parse_excel(path: Path) -> tuple[dict, Optional[date], Optional[date]]:
    """
    Parse an Excel P&L export. Tries to find label/amount columns automatically.
    Works with QuickBooks Excel exports and most bookkeeper-generated spreadsheets.
    """
    xls = pd.read_excel(path, header=None, dtype=str, keep_default_na=False)

    start_date = end_date = None
    header_text = " ".join(str(v) for v in xls.iloc[:6].values.flatten()).lower()
    date_range_match = re.search(
        r"(\w+ \d{4})\s+(?:through|to|-)\s+(\w+ \d{4})", header_text
    )
    if date_range_match:
        try:
            import calendar
            d1 = datetime.strptime(date_range_match.group(1), "%B %Y")
            d2 = datetime.strptime(date_range_match.group(2), "%B %Y")
            start_date = d1.date().replace(day=1)
            last_day = calendar.monthrange(d2.year, d2.month)[1]
            end_date = d2.date().replace(day=last_day)
        except ValueError:
            pass

    line_items: dict[str, float] = {}
    for _, row in xls.iterrows():
        vals = [str(v).strip() for v in row if str(v).strip() and str(v).strip().lower() != "nan"]
        if len(vals) < 2:
            continue
        label = vals[0]
        amount = _clean_amount(vals[-1])
        if label and amount is not None:
            line_items[label.lower()] = amount

    return line_items, start_date, end_date


def load_bookkeeper_pl(path: Path) -> tuple[dict, Optional[date], Optional[date]]:
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xls"):
        return _parse_excel(path)
    elif suffix == ".csv":
        return _parse_qbo_csv(path)
    else:
        raise ValueError(f"Unsupported file type: {suffix}. Use .csv or .xlsx")


# ── Extraction helpers ────────────────────────────────────────────────────────

def _extract(line_items: dict, patterns: list[str]) -> Optional[float]:
    """Return the first line_items value whose label matches any pattern."""
    for label, amount in line_items.items():
        if _matches(label, patterns):
            return amount
    return None


def _extract_labor(line_items: dict) -> Optional[float]:
    """
    Labor in QBO can be:
    - A single 'Payroll' line
    - Multiple role lines under Payroll (hourly, manager, etc.)
    We sum all labor-matched lines UNLESS a 'Total Payroll' / 'Total Labor' exists.
    """
    total = _extract(line_items, [r"^total\s+(payroll|labor|wages|salaries)"])
    if total is not None:
        return total
    # Fall back: sum all matching lines
    matched = [v for k, v in line_items.items() if _matches(k, LABOR_PATTERNS)]
    return sum(matched) if matched else None


def _extract_opex_by_type(line_items: dict) -> dict[str, float]:
    """Map bookkeeper line items to our expense_type categories."""
    result: dict[str, float] = {}
    for exp_type, patterns in OPEX_CATEGORY_MAP.items():
        matched = sum(v for k, v in line_items.items() if _matches(k, patterns))
        if matched:
            result[exp_type] = matched
    return result


# ── Comparison ────────────────────────────────────────────────────────────────

def _pct_diff(our: float, theirs: float) -> str:
    if theirs == 0:
        return "N/A"
    return f"{((our - theirs) / abs(theirs)) * 100:+.1f}%"


def _flag(our: float, theirs: float, threshold_pct: float = 3.0, threshold_abs: float = 200.0) -> str:
    """Return a warning flag if the discrepancy is material."""
    if theirs == 0:
        return "⚠ " if our != 0 else ""
    diff_pct = abs((our - theirs) / abs(theirs)) * 100
    diff_abs = abs(our - theirs)
    if diff_pct > threshold_pct and diff_abs > threshold_abs:
        return "⚠ "
    return ""


def compare(
    bk_path: Path,
    start: Optional[date] = None,
    end: Optional[date] = None,
    output: Optional[Path] = None,
):
    print(f"\nLoading bookkeeper P&L from: {bk_path}")
    bk_items, detected_start, detected_end = load_bookkeeper_pl(bk_path)

    # Use detected dates unless overridden
    start = start or detected_start
    end = end or detected_end

    if not start or not end:
        print(
            "\n⚠  Could not auto-detect date range from file header.\n"
            "   Pass --start YYYY-MM-DD --end YYYY-MM-DD to set it manually."
        )
        sys.exit(1)

    print(f"Date range: {start} → {end}\n")

    # ── Bookkeeper figures ────────────────────────────────────────────────────
    bk_revenue   = _extract(bk_items, REVENUE_PATTERNS)
    bk_cogs      = _extract(bk_items, COGS_PATTERNS)
    bk_gross     = _extract(bk_items, GROSS_PROFIT_PATTERNS)
    bk_labor     = _extract_labor(bk_items)
    bk_total_exp = _extract(bk_items, TOTAL_EXPENSES_PATTERNS)
    bk_net       = _extract(bk_items, NET_INCOME_PATTERNS)
    bk_opex      = _extract_opex_by_type(bk_items)

    # If gross profit not explicit, compute it
    if bk_gross is None and bk_revenue is not None and bk_cogs is not None:
        bk_gross = bk_revenue - bk_cogs

    # ── Our database figures ──────────────────────────────────────────────────
    print("Pulling P&L from database...")
    db_pnl = get_full_pnl(start, end)
    our_opex_df = get_expenses_by_type(start, end)
    our_opex: dict[str, float] = {}
    if not our_opex_df.empty:
        for _, row in our_opex_df.iterrows():
            our_opex[row["expense_type"]] = float(row["total_amount"])

    # ── Build comparison rows ─────────────────────────────────────────────────
    SECTION = object()  # sentinel for section headers

    rows = [
        # (label, our_value, bk_value, is_section_header)
        ("REVENUE", SECTION, SECTION),
        ("  Net Sales (POS)",        db_pnl["net_sales"],   bk_revenue),
        ("  Gross Sales (POS)",      db_pnl["gross_sales"],  None),

        ("COST OF GOODS SOLD", SECTION, SECTION),
        ("  COGS (theoretical)",     db_pnl["cogs"],         bk_cogs),

        ("GROSS PROFIT", SECTION, SECTION),
        ("  Gross Profit",           db_pnl["gross_profit"], bk_gross),
        ("  Gross Margin %",         db_pnl["gross_margin_pct"], None),

        ("LABOR", SECTION, SECTION),
        ("  Labor (POS hourly)",     db_pnl["labor_cost_pos"],   None),
        ("  Labor (fixed/salaried)", db_pnl["labor_cost_fixed"],  None),
        ("  Total Labor",            db_pnl["labor_cost"],        bk_labor),
        ("  Labor %",                db_pnl["labor_pct"],         None),

        ("PRIME COST", SECTION, SECTION),
        ("  Prime Cost",             db_pnl["prime_cost"],       None),
        ("  Prime Cost %",           db_pnl["prime_cost_pct"],   None),

        ("OPERATING EXPENSES", SECTION, SECTION),
    ]

    # Add opex by type
    all_exp_types = sorted(set(list(our_opex.keys()) + list(bk_opex.keys())))
    for exp_type in all_exp_types:
        our_val = our_opex.get(exp_type, 0.0)
        bk_val  = bk_opex.get(exp_type)
        label = f"  {exp_type.replace('_', ' ').title()}"
        rows.append((label, our_val, bk_val))

    rows += [
        ("  Total OpEx",             db_pnl["total_opex"],       bk_total_exp),
        ("  OpEx %",                 db_pnl["opex_pct"],         None),

        ("NET OPERATING INCOME", SECTION, SECTION),
        ("  Net Operating Income",   db_pnl["net_operating_income"], bk_net),
        ("  NOI %",                  db_pnl["noi_pct"],          None),

        ("BELOW THE LINE", SECTION, SECTION),
        ("  Distributions",          db_pnl["distributions"],    None),
        ("  Retained Cash",          db_pnl["retained_cash"],    None),
    ]

    # ── Print report ──────────────────────────────────────────────────────────
    lines = []
    sep  = "─" * 82
    head = f"{'Line Item':<35}  {'Our DB':>12}  {'Bookkeeper':>12}  {'Diff $':>10}  {'Diff %':>7}  {'':>2}"
    banner = f"\n{'='*82}\n  P&L COMPARISON  |  {start} → {end}\n{'='*82}"

    lines.append(banner)
    lines.append(f"\n  Source file: {bk_path.name}\n")

    unmatched_bk: list[str] = []

    lines.append(sep)
    lines.append(head)
    lines.append(sep)

    for row in rows:
        label, our_val, bk_val = row
        if our_val is SECTION:
            lines.append(f"\n{label}")
            continue

        # Format our value
        if our_val is None:
            our_str = "—"
        elif isinstance(our_val, float) and our_val == int(our_val) and abs(our_val) < 1000:
            # looks like a percentage
            our_str = f"{our_val:.1f}%"
        elif "%" in label or label.strip().endswith("%"):
            our_str = f"{our_val:.1f}%"
        else:
            our_str = f"${our_val:,.2f}"

        # Format bookkeeper value
        if bk_val is None:
            bk_str = "—"
            diff_str = ""
            pct_str  = ""
            flag_str = ""
        else:
            bk_str = f"${bk_val:,.2f}"
            if our_val is not None and "%" not in label:
                diff = our_val - bk_val
                diff_str = f"${diff:+,.2f}"
                pct_str  = _pct_diff(our_val, bk_val)
                flag_str = _flag(our_val, bk_val)
            else:
                diff_str = ""
                pct_str  = ""
                flag_str = ""

        lines.append(
            f"{label:<35}  {our_str:>12}  {bk_str:>12}  {diff_str:>10}  {pct_str:>7}  {flag_str}"
        )

    lines.append(sep)

    # ── Unmatched bookkeeper lines ────────────────────────────────────────────
    matched_patterns = (
        REVENUE_PATTERNS + COGS_PATTERNS + GROSS_PROFIT_PATTERNS
        + LABOR_PATTERNS + TOTAL_EXPENSES_PATTERNS + NET_INCOME_PATTERNS
        + [p for patterns in OPEX_CATEGORY_MAP.values() for p in patterns]
        + [r"^total\s+(payroll|labor|wages|salaries)"]
    )
    for label, amount in bk_items.items():
        if not _matches(label, matched_patterns):
            # Filter out obvious header/total lines
            if not re.search(r"^(total\s+)?(income|expenses|profit|loss|revenue)", label):
                unmatched_bk.append(f"  {label!r:<45}  ${amount:,.2f}")

    if unmatched_bk:
        lines.append("\n⚠  BOOKKEEPER LINES NOT MAPPED TO ANY CATEGORY:")
        lines.append("   (These amounts are NOT included in our OpEx totals above)")
        for u in unmatched_bk[:30]:
            lines.append(u)
        if len(unmatched_bk) > 30:
            lines.append(f"   ... and {len(unmatched_bk) - 30} more")

    lines.append("")
    lines.append("NOTES ON EXPECTED DISCREPANCIES:")
    lines.append("  COGS: Our figure is THEORETICAL (product mix cost). Bookkeeper uses")
    lines.append("        ACTUAL invoice purchases. Difference = waste / theft / shrinkage.")
    lines.append("  Labor: Our figure comes from POS clock-in data + fixed salaries.")
    lines.append("         Bookkeeper uses actual payroll. Difference = payroll taxes,")
    lines.append("         benefits, owner draws classified as payroll, timing accruals.")
    lines.append("  OpEx: We only track expenses entered into our system. Any expense the")
    lines.append("        bookkeeper records that you haven't entered here will show as a gap.")
    lines.append(sep)

    report_text = "\n".join(lines)
    print(report_text)

    # ── Optional HTML output ──────────────────────────────────────────────────
    if output:
        html = _render_html(report_text, start, end, bk_path)
        output.write_text(html, encoding="utf-8")
        print(f"\nReport saved to: {output}")

    return report_text


def _render_html(text: str, start: date, end: date, source: Path) -> str:
    escaped = (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("⚠", "<span style='color:#e67e22;font-weight:bold'>⚠</span>")
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>P&L Comparison {start} – {end}</title>
<style>
  body {{ font-family: 'Courier New', monospace; background: #1a1a2e; color: #e0e0e0;
         padding: 2rem; max-width: 960px; margin: auto; }}
  pre {{ white-space: pre-wrap; line-height: 1.6; font-size: 0.88rem; }}
  h2  {{ color: #a8dadc; }}
</style>
</head>
<body>
<h2>Bar Arbolada — P&L Comparison</h2>
<p style="color:#aaa">Source: {source.name} &nbsp;|&nbsp; Period: {start} → {end}</p>
<pre>{escaped}</pre>
</body>
</html>"""


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Compare bookkeeper P&L export against Bar Arbolada database."
    )
    parser.add_argument(
        "file",
        type=Path,
        help="Path to bookkeeper P&L file (.csv or .xlsx)",
    )
    parser.add_argument(
        "--start",
        type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
        help="Start date YYYY-MM-DD (overrides auto-detection)",
    )
    parser.add_argument(
        "--end",
        type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
        help="End date YYYY-MM-DD (overrides auto-detection)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path for HTML report output",
    )
    args = parser.parse_args()

    if not args.file.exists():
        print(f"Error: File not found: {args.file}")
        sys.exit(1)

    compare(args.file, start=args.start, end=args.end, output=args.output)


if __name__ == "__main__":
    main()
