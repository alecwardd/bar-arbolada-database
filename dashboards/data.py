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

import streamlit as st

from src.analytics import queries as _q

# 10 minutes: long enough to cache within a browsing session, short enough that a
# daily import becomes visible without anyone clearing the cache.
CACHE_TTL_SECONDS = 600


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def get_sales_date_range() -> tuple[date, date]:
    return _q.get_sales_date_range()


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def get_daily_sales(start: date, end: date):
    return _q.get_daily_sales(start, end)


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def get_full_pnl(start: date, end: date):
    return _q.get_full_pnl(start, end)


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def get_reorder_items():
    return _q.get_reorder_items()


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def get_full_product_mix(start: date, end: date):
    return _q.get_full_product_mix(start, end)


def clear_data_cache() -> None:
    """Drop all cached query results (used by a manual 'Refresh data' control)."""
    st.cache_data.clear()
