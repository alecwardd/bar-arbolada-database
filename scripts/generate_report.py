"""
Owner Presentation Report Generator
======================================
Generates a comprehensive business insights report as both
HTML (for viewing) and structured data (for further analysis).

Usage:
    python scripts/generate_report.py                    # full date range
    python scripts/generate_report.py 2026-01-01 2026-01-31  # custom range

Output: reports/owner_report_YYYY-MM-DD.html
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import date, datetime, timedelta
import pandas as pd

from src.analytics.queries import (
    get_daily_sales,
    get_sales_date_range,
    get_prime_cost_data,
    get_category_profitability,
    get_pour_cost_by_category,
    get_splh_trend,
    get_full_product_mix,
    get_comp_summary,
    get_void_summary,
    get_invoice_totals,
    get_inv_items,
    get_vendors,
    get_recipes,
)


def generate_report(start: date = None, end: date = None) -> str:
    """Generate owner report as HTML string."""

    if not start or not end:
        start, end = get_sales_date_range()

    num_days = (end - start).days + 1

    # ── Gather Data ───────────────────────────────────────────────────────

    sales_df = get_daily_sales(start, end)
    prime_df = get_prime_cost_data(start, end)
    cat_prof = get_category_profitability(start, end)
    pour_cost = get_pour_cost_by_category(start, end)
    splh_df = get_splh_trend(start, end)
    mix_df = get_full_product_mix(start, end)
    comp_df = get_comp_summary(start, end)
    void_df = get_void_summary(start, end)
    invoice_totals = get_invoice_totals()
    inv_items = get_inv_items()
    vendors = get_vendors()
    recipes = get_recipes()

    # ── Compute Metrics ───────────────────────────────────────────────────

    if not sales_df.empty:
        for col in ["net_sales", "total_checks",
                     "check_avg", "total_comps", "total_voids", "total_tips"]:
            if col in sales_df.columns:
                sales_df[col] = pd.to_numeric(sales_df[col], errors="coerce").fillna(0)

        total_revenue = sales_df["net_sales"].sum()
        total_checks = int(sales_df["total_checks"].sum())
        avg_daily = total_revenue / len(sales_df) if len(sales_df) > 0 else 0
        avg_check = sales_df["check_avg"].mean()
        total_comps = sales_df["total_comps"].sum()
        total_voids = sales_df["total_voids"].sum()
        total_tips = sales_df["total_tips"].sum()
        comp_pct = (total_comps / total_revenue * 100) if total_revenue > 0 else 0

        best_day = sales_df.loc[sales_df["net_sales"].idxmax()]
        worst_day = sales_df.loc[sales_df["net_sales"].idxmin()]

        # Day of week analysis
        sales_df["dow"] = pd.to_datetime(sales_df["trading_day"]).dt.day_name()
        dow_avg = sales_df.groupby("dow")["net_sales"].mean().reindex(
            ["Monday", "Tuesday", "Wednesday", "Thursday",
             "Friday", "Saturday", "Sunday"]
        )
    else:
        total_revenue = avg_daily = avg_check = 0
        total_checks = 0
        total_comps = total_voids = total_tips = comp_pct = 0
        best_day = worst_day = None
        dow_avg = pd.Series()

    if not prime_df.empty:
        prime_df["labor_cost"] = pd.to_numeric(prime_df["labor_cost"], errors="coerce").fillna(0)
        prime_df["labor_hours"] = pd.to_numeric(prime_df["labor_hours"], errors="coerce").fillna(0)
        total_labor = prime_df["labor_cost"].sum()
        total_hours = prime_df["labor_hours"].sum()
        labor_pct = (total_labor / total_revenue * 100) if total_revenue > 0 else 0
        avg_splh = (total_revenue / total_hours) if total_hours > 0 else 0
    else:
        total_labor = total_hours = labor_pct = avg_splh = 0

    # Top sellers
    if not mix_df.empty:
        mix_df["total_sold"] = pd.to_numeric(mix_df["total_sold"], errors="coerce").fillna(0).astype(int)
        mix_df["net_revenue"] = pd.to_numeric(mix_df["net_revenue"], errors="coerce").fillna(0)
        top_by_qty = mix_df.nlargest(10, "total_sold")
        top_by_rev = mix_df.nlargest(10, "net_revenue")
    else:
        top_by_qty = top_by_rev = pd.DataFrame()

    # ── Build HTML ────────────────────────────────────────────────────────

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bar Arbolada - Owner Report</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
               background: #0f172a; color: #e2e8f0; line-height: 1.6; padding: 2rem; }}
        .container {{ max-width: 1000px; margin: 0 auto; }}
        h1 {{ font-size: 2.2rem; color: #f1f5f9; margin-bottom: 0.5rem; }}
        h2 {{ font-size: 1.5rem; color: #94a3b8; margin: 2rem 0 1rem; border-bottom: 1px solid #334155; padding-bottom: 0.5rem; }}
        h3 {{ font-size: 1.2rem; color: #cbd5e1; margin: 1.5rem 0 0.5rem; }}
        .subtitle {{ color: #64748b; margin-bottom: 2rem; }}
        .kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 1rem; margin: 1rem 0; }}
        .kpi {{ background: #1e293b; border-radius: 12px; padding: 1.2rem; text-align: center; }}
        .kpi-value {{ font-size: 1.8rem; font-weight: 700; color: #f1f5f9; }}
        .kpi-label {{ font-size: 0.85rem; color: #94a3b8; margin-top: 0.3rem; }}
        .kpi-good {{ border-left: 4px solid #22c55e; }}
        .kpi-warn {{ border-left: 4px solid #f59e0b; }}
        .kpi-bad {{ border-left: 4px solid #ef4444; }}
        table {{ width: 100%; border-collapse: collapse; margin: 1rem 0; }}
        th {{ background: #1e293b; color: #94a3b8; padding: 0.75rem; text-align: left; font-weight: 600; font-size: 0.85rem; }}
        td {{ padding: 0.75rem; border-bottom: 1px solid #1e293b; }}
        tr:hover td {{ background: #1e293b; }}
        .highlight {{ color: #22c55e; font-weight: 600; }}
        .warn {{ color: #f59e0b; }}
        .bad {{ color: #ef4444; }}
        .section {{ background: #1e293b; border-radius: 12px; padding: 1.5rem; margin: 1.5rem 0; }}
        .insight {{ background: #172554; border-left: 4px solid #3b82f6; padding: 1rem 1.5rem; margin: 1rem 0; border-radius: 0 8px 8px 0; }}
        .footer {{ text-align: center; color: #475569; margin-top: 3rem; padding-top: 1rem; border-top: 1px solid #1e293b; }}
    </style>
</head>
<body>
<div class="container">

<h1>Bar Arbolada</h1>
<p class="subtitle">Owner Report &mdash; {start.strftime('%b %d')} to {end.strftime('%b %d, %Y')} ({num_days} days)</p>

<h2>Executive Summary</h2>
<div class="kpi-grid">
    <div class="kpi kpi-good">
        <div class="kpi-value">${total_revenue:,.0f}</div>
        <div class="kpi-label">Total Net Revenue</div>
    </div>
    <div class="kpi">
        <div class="kpi-value">${avg_daily:,.0f}</div>
        <div class="kpi-label">Avg Daily Sales</div>
    </div>
    <div class="kpi">
        <div class="kpi-value">{total_checks:,}</div>
        <div class="kpi-label">Total Checks</div>
    </div>
    <div class="kpi">
        <div class="kpi-value">${avg_check:.2f}</div>
        <div class="kpi-label">Avg Check</div>
    </div>
    <div class="kpi {'kpi-good' if labor_pct < 20 else 'kpi-warn' if labor_pct < 25 else 'kpi-bad'}">
        <div class="kpi-value">{labor_pct:.1f}%</div>
        <div class="kpi-label">Labor %</div>
    </div>
    <div class="kpi">
        <div class="kpi-value">${avg_splh:,.0f}</div>
        <div class="kpi-label">Avg SPLH</div>
    </div>
</div>
"""

    # Best/worst days
    if best_day is not None:
        html += f"""
<div class="section">
    <h3>Peak Performance</h3>
    <p><span class="highlight">Best Day:</span> {best_day['trading_day']} &mdash; ${float(best_day['net_sales']):,.2f} net sales, {int(best_day['total_checks'])} checks</p>
    <p><span class="warn">Slowest Day:</span> {worst_day['trading_day']} &mdash; ${float(worst_day['net_sales']):,.2f} net sales, {int(worst_day['total_checks'])} checks</p>
</div>
"""

    # Day of week
    if not dow_avg.empty:
        html += "<h2>Sales by Day of Week</h2>\n<table><tr><th>Day</th><th>Avg Sales</th></tr>\n"
        for day, avg in dow_avg.items():
            if pd.notna(avg):
                html += f"<tr><td>{day}</td><td>${avg:,.0f}</td></tr>\n"
        html += "</table>\n"

    # Top sellers
    if not top_by_qty.empty:
        html += "<h2>Top 10 Items by Volume</h2>\n<table><tr><th>#</th><th>Item</th><th>Category</th><th>Qty Sold</th><th>Revenue</th></tr>\n"
        for i, (_, row) in enumerate(top_by_qty.iterrows()):
            html += f"<tr><td>{i+1}</td><td>{row['item_name']}</td><td>{row['category_name']}</td><td>{int(row['total_sold']):,}</td><td>${row['net_revenue']:,.2f}</td></tr>\n"
        html += "</table>\n"

    if not top_by_rev.empty:
        html += "<h2>Top 10 Items by Revenue</h2>\n<table><tr><th>#</th><th>Item</th><th>Category</th><th>Revenue</th><th>Qty Sold</th></tr>\n"
        for i, (_, row) in enumerate(top_by_rev.iterrows()):
            html += f"<tr><td>{i+1}</td><td>{row['item_name']}</td><td>{row['category_name']}</td><td>${row['net_revenue']:,.2f}</td><td>{int(row['total_sold']):,}</td></tr>\n"
        html += "</table>\n"

    # Category breakdown
    if not cat_prof.empty:
        html += "<h2>Category Performance</h2>\n<table><tr><th>Category</th><th>Items</th><th>Revenue</th><th>Cost</th><th>Gross Profit</th></tr>\n"
        for _, row in cat_prof.iterrows():
            rev = float(row.get("net_revenue", 0) or 0)
            cost = float(row.get("total_cost", 0) or 0)
            profit = float(row.get("gross_profit", 0) or 0)
            html += f"<tr><td>{row['category_name']}</td><td>{int(row.get('unique_items', 0))}</td><td>${rev:,.2f}</td><td>${cost:,.2f}</td><td>${profit:,.2f}</td></tr>\n"
        html += "</table>\n"

    # Comps & Voids
    html += f"""
<h2>Comp & Void Summary</h2>
<div class="kpi-grid">
    <div class="kpi {'kpi-good' if comp_pct < 3 else 'kpi-warn' if comp_pct < 5 else 'kpi-bad'}">
        <div class="kpi-value">${total_comps:,.2f}</div>
        <div class="kpi-label">Total Comps ({comp_pct:.1f}% of sales)</div>
    </div>
    <div class="kpi">
        <div class="kpi-value">${total_voids:,.2f}</div>
        <div class="kpi-label">Total Voids</div>
    </div>
</div>
"""

    if not comp_df.empty:
        html += "<h3>Comps by Reason</h3>\n<table><tr><th>Reason</th><th>Count</th><th>Total</th></tr>\n"
        for _, row in comp_df.iterrows():
            html += f"<tr><td>{row.get('comp_reason', 'Unknown')}</td><td>{int(row.get('comp_count', 0))}</td><td>${float(row.get('total_amount', 0)):,.2f}</td></tr>\n"
        html += "</table>\n"

    # System status
    html += f"""
<h2>System Status</h2>
<div class="section">
    <p><span class="highlight">Vendors:</span> {len(vendors)} configured</p>
    <p><span class="highlight">Inventory Items:</span> {len(inv_items)} tracked</p>
    <p><span class="highlight">Recipes:</span> {len(recipes) if not recipes.empty else 0} defined</p>
    <p><span class="highlight">Days of Data:</span> {len(sales_df)} trading days</p>
</div>
"""

    # Insights / recommendations
    insights = []
    if labor_pct > 25:
        insights.append(f"Labor cost is {labor_pct:.1f}% of sales (target: &lt;20%). Review staffing levels, especially on slower days.")
    if comp_pct > 3:
        insights.append(f"Comp rate is {comp_pct:.1f}% (target: &lt;3%). Review comp reasons and approval process.")
    if len(inv_items) == 0:
        insights.append("No inventory items tracked yet. Add your top 20 items by cost to start theoretical inventory tracking.")
    if recipes.empty or len(recipes) == 0:
        insights.append("No recipes defined. Map your top 10 cocktails to enable automatic depletion tracking.")
    if not dow_avg.empty:
        slowest_day = dow_avg.idxmin()
        fastest_day = dow_avg.idxmax()
        if pd.notna(slowest_day) and pd.notna(fastest_day):
            insights.append(f"Strongest day: {fastest_day} (${dow_avg[fastest_day]:,.0f} avg). Weakest: {slowest_day} (${dow_avg[slowest_day]:,.0f} avg). Consider promotions or reduced staffing on {slowest_day}s.")

    if insights:
        html += "<h2>Key Insights & Recommendations</h2>\n"
        for insight in insights:
            html += f'<div class="insight"><p>{insight}</p></div>\n'

    html += f"""
<div class="footer">
    <p>Bar Arbolada Analytics System &mdash; Report generated {datetime.now().strftime('%B %d, %Y at %I:%M %p')}</p>
</div>

</div>
</body>
</html>"""

    return html


def main():
    args = sys.argv[1:]

    if len(args) == 2:
        start = datetime.strptime(args[0], "%Y-%m-%d").date()
        end = datetime.strptime(args[1], "%Y-%m-%d").date()
    else:
        start = end = None

    print("Generating owner report...")
    html = generate_report(start, end)

    # Save to reports directory
    reports_dir = Path(__file__).parent.parent / "reports"
    reports_dir.mkdir(exist_ok=True)

    filename = f"owner_report_{date.today().isoformat()}.html"
    filepath = reports_dir / filename

    filepath.write_text(html, encoding="utf-8")
    print(f"Report saved to: {filepath}")
    print(f"Open in browser: file:///{filepath.resolve()}")


if __name__ == "__main__":
    main()
