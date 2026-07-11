"""
Frose All Day — Expected Product Mix Report
=============================================

Generates a full-menu forecast for Jones Assembly Frose-scale volume at
Bar Arbolada, using historical Frose / spike-Saturday product mix and
current business trajectory.

Usage:
    python scripts/frose_product_mix_report.py
    python scripts/frose_product_mix_report.py --date 2026-07-11
    python scripts/frose_product_mix_report.py --date 2026-07-11 --extra-date 2025-07-12

Output:
    reports/frose_product_mix_YYYY-MM-DD.csv
    reports/frose_product_mix_YYYY-MM-DD.html
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

from src.analytics.frose_forecast import (
    KNOWN_FROSE_DATES,
    build_frose_product_mix_forecast,
    detect_high_sales_mid_july_saturdays,
    get_frose_events_from_db,
    resolve_frose_reference_days,
)
from src.analytics.queries import get_sales_date_range


def _fmt_money(v) -> str:
    try:
        return f"${float(v):,.0f}"
    except (TypeError, ValueError):
        return "—"


def _build_html(target: date, forecast: pd.DataFrame, meta: dict) -> str:
    ref_days = meta.get("reference_days", [])
    ref_day_str = ", ".join(d.isoformat() for d in ref_days) if ref_days else "none found"

    rows_html = ""
    if not forecast.empty:
        display = forecast.copy()
        for col in ("weighted_avg_qty", "expected_qty", "share_of_units", "avg_unit_price"):
            if col in display.columns:
                display[col] = pd.to_numeric(display[col], errors="coerce").fillna(0)
        for _, row in display.iterrows():
            qty = int(row.get("expected_qty", 0) or 0)
            hist = float(row.get("weighted_avg_qty", 0) or 0)
            share = float(row.get("share_of_units", 0) or 0) * 100
            rev = float(row.get("expected_revenue", 0) or 0)
            rows_html += f"""
            <tr>
                <td>{row.get('category_name') or '—'}</td>
                <td>{row.get('item_name')}</td>
                <td class="num">{hist:.1f}</td>
                <td class="num highlight"><strong>{qty}</strong></td>
                <td class="num">{share:.1f}%</td>
                <td class="num">${rev:,.0f}</td>
            </tr>"""

    error_block = ""
    if meta.get("error"):
        error_block = f'<div class="error">{meta["error"]}</div>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Frose Product Mix Forecast — {target.isoformat()}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
           background: #0f172a; color: #e2e8f0; margin: 0; padding: 2rem; }}
    .wrap {{ max-width: 1200px; margin: 0 auto; }}
    h1 {{ margin-bottom: 0.25rem; }}
    .sub {{ color: #94a3b8; margin-bottom: 1.5rem; }}
    .kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 1rem; margin: 1rem 0 2rem; }}
    .kpi {{ background: #1e293b; border-radius: 10px; padding: 1rem; }}
    .kpi .v {{ font-size: 1.5rem; font-weight: 700; }}
    .kpi .l {{ color: #94a3b8; font-size: 0.85rem; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
    th {{ background: #1e293b; text-align: left; padding: 0.6rem; position: sticky; top: 0; }}
    td {{ padding: 0.55rem 0.6rem; border-bottom: 1px solid #1e293b; }}
    tr:hover td {{ background: #172033; }}
    .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .highlight {{ color: #4ade80; }}
    .section {{ background: #1e293b; border-radius: 10px; padding: 1rem 1.25rem; margin: 1rem 0; }}
    .error {{ background: #450a0a; border-left: 4px solid #ef4444; padding: 1rem; margin: 1rem 0; }}
    .scroll {{ max-height: 70vh; overflow: auto; border-radius: 10px; }}
  </style>
</head>
<body>
<div class="wrap">
  <h1>Frose Day Product Mix Forecast</h1>
  <p class="sub">Bar Arbolada — target date <strong>{target.strftime('%A, %B %d, %Y')}</strong>
     (Jones Assembly All Day Frosé next door)</p>
  {error_block}
  <div class="kpis">
    <div class="kpi"><div class="v">{_fmt_money(meta.get('expected_net_sales', 0))}</div><div class="l">Expected Net Sales</div></div>
    <div class="kpi"><div class="v">{meta.get('total_expected_units', 0):,}</div><div class="l">Expected Units</div></div>
    <div class="kpi"><div class="v">{meta.get('items_with_expected_sales', 0):,}</div><div class="l">Items w/ Expected Sales</div></div>
    <div class="kpi"><div class="v">{meta.get('volume_scale_factor', 1):.2f}x</div><div class="l">Volume vs Avg Frose</div></div>
  </div>

  <div class="section">
    <h2>Methodology</h2>
    <p><strong>Reference Frose days used:</strong> {ref_day_str}</p>
    <p>Historical Frose avg sales: {_fmt_money(meta.get('historical_frose_avg_sales', 0))} ·
       Recent Saturday avg: {_fmt_money(meta.get('recent_saturday_avg_sales', 0))} ·
       Saturday ratio: {meta.get('saturday_ratio', 1):.2f} ·
       Trend: {meta.get('trend_factor', 1):.2f} ·
       July seasonal: {meta.get('seasonal_factor', 1):.2f}</p>
    <p>Expected qty per item = sales-weighted historical Frose qty × volume scale factor
       (blends scaled Frose history with demand forecast). Prep quantities are rounded up.</p>
  </div>

  <h2>Full Menu — Expected Sales</h2>
  <div class="scroll">
    <table>
      <thead>
        <tr>
          <th>Category</th>
          <th>Item</th>
          <th class="num">Hist Frose Avg</th>
          <th class="num">Expected Qty</th>
          <th class="num">Mix %</th>
          <th class="num">Est Revenue</th>
        </tr>
      </thead>
      <tbody>{rows_html}</tbody>
    </table>
  </div>

  <p class="sub" style="margin-top:2rem">Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} · Bar Arbolada Analytics</p>
</div>
</body>
</html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Frose day product mix forecast")
    parser.add_argument(
        "--date",
        default=date.today().isoformat(),
        help="Target trading day (YYYY-MM-DD). Default: today.",
    )
    parser.add_argument(
        "--extra-date",
        action="append",
        default=[],
        help="Additional reference day(s) to include (repeatable).",
    )
    parser.add_argument(
        "--min-year",
        type=int,
        default=2023,
        help="Earliest year for Frose reference days (default: 2023).",
    )
    parser.add_argument(
        "--list-reference-days",
        action="store_true",
        help="Print candidate Frose reference days and exit.",
    )
    args = parser.parse_args()

    target = datetime.strptime(args.date, "%Y-%m-%d").date()
    extras = [datetime.strptime(d, "%Y-%m-%d").date() for d in args.extra_date]

    try:
        min_d, max_d = get_sales_date_range()
        print(f"Sales data range: {min_d} to {max_d}")
    except Exception as exc:
        print(f"Warning: could not read sales date range: {exc}")

    if args.list_reference_days:
        print("\n=== Known Frose dates (fallback) ===")
        for d in KNOWN_FROSE_DATES:
            print(f"  {d.isoformat()}")

        print("\n=== external_events (frose/jones) ===")
        ev = get_frose_events_from_db()
        if ev.empty:
            print("  (none)")
        else:
            for _, r in ev.iterrows():
                print(f"  {r['event_date']}  {r['event_name']}")

        print("\n=== Auto-detected mid-July spike Saturdays ===")
        det = detect_high_sales_mid_july_saturdays(min_year=args.min_year)
        if det.empty:
            print("  (none)")
        else:
            for _, r in det.iterrows():
                print(
                    f"  {r['trading_day']}  sales={_fmt_money(r['net_sales'])}  "
                    f"vs_sat_avg={r['vs_sat_avg']}x"
                )

        ref, meta = resolve_frose_reference_days(extras, min_year=args.min_year)
        print("\n=== Resolved reference days (with product mix) ===")
        if not ref:
            print("  (none — import product mix CSVs for Frose dates)")
        else:
            for d in ref:
                print(f"  {d.isoformat()}")
        return 0

    print(f"\nBuilding Frose product mix forecast for {target.isoformat()}...")
    forecast, meta = build_frose_product_mix_forecast(
        target_date=target,
        extra_reference_days=extras or None,
        min_reference_year=args.min_year,
        include_zero_sellers=True,
    )

    reports_dir = Path(__file__).parent.parent / "reports"
    reports_dir.mkdir(exist_ok=True)
    stem = f"frose_product_mix_{target.isoformat()}"

    if forecast.empty:
        print("\nERROR:", meta.get("error", "No forecast produced."))
        print("\nRun with --list-reference-days to diagnose reference dates.")
        print("Ensure product mix CSVs are imported for prior Frose Saturdays.")
        html = _build_html(target, forecast, meta)
        (reports_dir / f"{stem}.html").write_text(html, encoding="utf-8")
        return 1

    # CSV export
    export_cols = [
        c for c in [
            "category_name", "item_name", "frose_day_count", "total_historical_qty",
            "weighted_avg_qty", "share_of_units", "expected_qty", "avg_unit_price",
            "expected_revenue",
        ]
        if c in forecast.columns
    ]
    csv_path = reports_dir / f"{stem}.csv"
    forecast[export_cols].to_csv(csv_path, index=False)

    html_path = reports_dir / f"{stem}.html"
    html_path.write_text(_build_html(target, forecast, meta), encoding="utf-8")

    print("\n=== Frose Day Forecast Summary ===")
    print(f"Target date:           {target.isoformat()}")
    print(f"Reference days:        {', '.join(d.isoformat() for d in meta.get('reference_days', []))}")
    print(f"Hist Frose avg sales:  {_fmt_money(meta.get('historical_frose_avg_sales', 0))}")
    print(f"Expected net sales:    {_fmt_money(meta.get('expected_net_sales', 0))}")
    print(f"Volume scale:          {meta.get('volume_scale_factor', 1):.2f}x")
    print(f"Expected units:        {meta.get('total_expected_units', 0):,}")
    print(f"Items w/ sales > 0:    {meta.get('items_with_expected_sales', 0):,} / {meta.get('item_count', 0):,}")

    print("\nTop 25 expected sellers:")
    top = forecast.nlargest(25, "expected_qty")
    for _, row in top.iterrows():
        print(
            f"  {int(row['expected_qty']):>4}  {row.get('category_name', '—'):<20}  "
            f"{row['item_name']}"
        )

    print(f"\nFull report saved:")
    print(f"  CSV:  {csv_path}")
    print(f"  HTML: {html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
