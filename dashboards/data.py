"""
Cached data-access layer for the dashboards.

The query layer (``src.analytics.queries``) is deliberately Streamlit-agnostic,
so caching lives here. These thin wrappers add ``st.cache_data`` around the
read-only queries that are hit on many page loads (and often twice per load for
current-vs-prior windows). ``st.cache_data`` keys on the call arguments and
returns a fresh copy each call, so it is safe even for pages that mutate the
returned DataFrame (e.g. Product Mix adds derived columns).

Cache entries expire after ``CACHE_TTL_SECONDS`` so newly imported data shows up
without a restart; ``clear_data_cache()`` (wired to a sidebar button) forces an
immediate refresh.

Usage: import these instead of the raw query functions, e.g.
    from dashboards.data import get_daily_sales   # cached
"""

from __future__ import annotations

from datetime import date
from typing import Callable

import streamlit as st

from src.analytics import queries as _q

# 10 minutes: long enough to cache within a browsing session, short enough that a
# daily import becomes visible without anyone clearing the cache.
CACHE_TTL_SECONDS = 600


def _cached(fn: Callable) -> Callable:
    """Wrap a query function with ``st.cache_data`` while keeping its name."""

    @st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
    def wrapper(*args, **kwargs):
        return fn(*args, **kwargs)

    wrapper.__name__ = fn.__name__
    wrapper.__qualname__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    wrapper.__module__ = __name__
    return wrapper


# ── Date ranges / catalogs ───────────────────────────────────────────────────

get_sales_date_range = _cached(_q.get_sales_date_range)
get_all_trading_days = _cached(_q.get_all_trading_days)
get_payroll_date_range = _cached(_q.get_payroll_date_range)
get_reorder_items = _cached(_q.get_reorder_items)

# ── Sales / labor / mix (range or day) ───────────────────────────────────────

get_daily_sales = _cached(_q.get_daily_sales)
get_daypart_sales = _cached(_q.get_daypart_sales)
get_category_sales = _cached(_q.get_category_sales)
get_hourly_sales = _cached(_q.get_hourly_sales)
get_hourly_heatmap_data = _cached(_q.get_hourly_heatmap_data)
get_hourly_trend = _cached(_q.get_hourly_trend)
get_daily_labor = _cached(_q.get_daily_labor)
get_hourly_labor = _cached(_q.get_hourly_labor)
get_top_sellers = _cached(_q.get_top_sellers)
get_full_product_mix = _cached(_q.get_full_product_mix)
get_product_mix_trend = _cached(_q.get_product_mix_trend)
get_category_mix_summary = _cached(_q.get_category_mix_summary)

# ── Comps / voids ────────────────────────────────────────────────────────────

get_comp_daily_trend = _cached(_q.get_comp_daily_trend)
get_void_daily_trend = _cached(_q.get_void_daily_trend)
get_comps_with_cost = _cached(_q.get_comps_with_cost)
get_comp_summary_with_cost = _cached(_q.get_comp_summary_with_cost)
get_comp_daily_trend_with_cost = _cached(_q.get_comp_daily_trend_with_cost)
get_comp_by_employee_with_cost = _cached(_q.get_comp_by_employee_with_cost)
get_voids_with_cost = _cached(_q.get_voids_with_cost)
get_void_summary_with_cost = _cached(_q.get_void_summary_with_cost)
get_void_daily_trend_with_cost = _cached(_q.get_void_daily_trend_with_cost)

# ── Profitability / P&L / opex / COGS reads ──────────────────────────────────

get_prime_cost_data = _cached(_q.get_prime_cost_data)
get_category_profitability = _cached(_q.get_category_profitability)
get_pour_cost_by_category = _cached(_q.get_pour_cost_by_category)
get_splh_trend = _cached(_q.get_splh_trend)
get_full_pnl = _cached(_q.get_full_pnl)
get_expenses_by_type = _cached(_q.get_expenses_by_type)
get_expenses_by_category = _cached(_q.get_expenses_by_category)
get_untrusted_labor_rows = _cached(_q.get_untrusted_labor_rows)
get_untrusted_labor_details = _cached(_q.get_untrusted_labor_details)
get_cogs_trend = _cached(_q.get_cogs_trend)
get_cogs_vs_purchases = _cached(_q.get_cogs_vs_purchases)
get_cogs_by_category_trend = _cached(_q.get_cogs_by_category_trend)
get_top_cost_items = _cached(_q.get_top_cost_items)
get_worst_margin_items = _cached(_q.get_worst_margin_items)
get_cost_coverage_gaps = _cached(_q.get_cost_coverage_gaps)
get_vendor_spend_trend = _cached(_q.get_vendor_spend_trend)
get_vendor_spend_detail = _cached(_q.get_vendor_spend_detail)
get_invoice_totals = _cached(_q.get_invoice_totals)
get_vendor_names = _cached(_q.get_vendor_names)
get_shrinkage_summary = _cached(_q.get_shrinkage_summary)
get_high_variance_items = _cached(_q.get_high_variance_items)
get_adjustment_summary = _cached(_q.get_adjustment_summary)
get_adjustment_trend = _cached(_q.get_adjustment_trend)
get_cost_data_health = _cached(_q.get_cost_data_health)
get_cost_outlier_items = _cached(_q.get_cost_outlier_items)

# ── Payroll reads ────────────────────────────────────────────────────────────

get_payroll_settings = _cached(_q.get_payroll_settings)
get_payroll_daily_inputs = _cached(_q.get_payroll_daily_inputs)
get_payroll_daily_allocations = _cached(_q.get_payroll_daily_allocations)
get_payroll_employees_list = _cached(_q.get_payroll_employees_list)
get_payroll_employee_roles = _cached(_q.get_payroll_employee_roles)
get_payroll_employee_wages = _cached(_q.get_payroll_employee_wages)
get_payroll_cash_tips = _cached(_q.get_payroll_cash_tips)
get_payroll_employee_settings = _cached(_q.get_payroll_employee_settings)


def clear_data_cache() -> None:
    """Drop all cached query results (used by a manual 'Refresh data' control)."""
    st.cache_data.clear()
