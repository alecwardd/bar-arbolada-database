"""
Shared period (date-range) control for the analytics dashboards.

Every page used to roll its own ``st.date_input`` block with a different default
(30d here, 90d there, YTD elsewhere), so switching pages silently changed the
window you were looking at. This module provides one selector with a single
default and session-scoped memory: pick "Last 60 Days" on one page and every
other page that uses this control shows the same window.

Usage::

    from dashboards.period import period_selector
    p = period_selector(min_date, max_date)
    df = get_daily_sales(p.start, p.end)
    df_prior = get_daily_sales(p.prior_start, p.prior_end)  # same-length prior window
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

DEFAULT_LOOKBACK_DAYS = 30
DEFAULT_LABEL = "Last 30 Days"

# label -> lookback days (None = Year to Date, -1 = All Time, 0 = Custom Range)
_PERIOD_OPTIONS: dict[str, int | None] = {
    "Last 30 Days": 30,
    "Last 60 Days": 60,
    "Last 90 Days": 90,
    "Year to Date": None,
    "All Time": -1,
    "Custom Range": 0,
}

# Shared widget keys → selection persists across pages within a session.
_CHOICE_KEY = "shared_period_choice"
_START_KEY = "shared_period_start"
_END_KEY = "shared_period_end"
# Resolved window (always updated) — used by pages that need a day default
# without requiring Custom Range widget keys to be set.
_RESOLVED_END_KEY = "shared_period_resolved_end"


def get_shared_period_end() -> date | None:
    """Return the last resolved period end from session state, if any."""
    try:
        import streamlit as st
    except ImportError:
        return None
    end = st.session_state.get(_RESOLVED_END_KEY)
    return end if isinstance(end, date) else None


def _clamp_date(d: date, min_date: date, max_date: date) -> date:
    return min(max(d, min_date), max_date)


@dataclass(frozen=True)
class Period:
    """Resolved date window plus the immediately-preceding same-length window."""

    start: date
    end: date
    prior_start: date
    prior_end: date
    label: str
    min_date: date
    max_date: date

    @property
    def length_days(self) -> int:
        return (self.end - self.start).days + 1


def period_selector(min_date: date, max_date: date, *, location: str = "sidebar") -> Period:
    """
    Render the shared period control and return the resolved :class:`Period`.

    The selection is stored under shared session keys, so all pages using this
    control stay in sync. ``location`` is ``"sidebar"`` (default) or ``"main"``.
    Custom-range dates stored from another page are clamped into this page's
    ``[min_date, max_date]`` so Streamlit does not raise on out-of-bounds values.
    """
    import streamlit as st

    container = st.sidebar if location == "sidebar" else st
    container.header("Period")

    labels = list(_PERIOD_OPTIONS)
    stored = st.session_state.get(_CHOICE_KEY, DEFAULT_LABEL)
    default_index = labels.index(stored) if stored in labels else labels.index(DEFAULT_LABEL)
    choice = container.radio(
        "Select period",
        labels,
        index=default_index,
        key=_CHOICE_KEY,
        label_visibility="collapsed",
    )

    if choice == "Custom Range":
        fallback_start = max(min_date, max_date - timedelta(days=DEFAULT_LOOKBACK_DAYS - 1))
        fallback_end = max_date
        # Clamp any previously shared custom dates into this page's bounds
        # before the widgets read session state (avoids StreamlitAPIException).
        stored_start = st.session_state.get(_START_KEY)
        stored_end = st.session_state.get(_END_KEY)
        if isinstance(stored_start, date):
            st.session_state[_START_KEY] = _clamp_date(stored_start, min_date, max_date)
        if isinstance(stored_end, date):
            st.session_state[_END_KEY] = _clamp_date(stored_end, min_date, max_date)

        start = container.date_input(
            "Start",
            value=st.session_state.get(_START_KEY, fallback_start),
            min_value=min_date,
            max_value=max_date,
            key=_START_KEY,
        )
        end = container.date_input(
            "End",
            value=st.session_state.get(_END_KEY, fallback_end),
            min_value=min_date,
            max_value=max_date,
            key=_END_KEY,
        )
        if start > end:
            start, end = end, start
    elif choice == "All Time":
        start, end = min_date, max_date
    elif choice == "Year to Date":
        end = max_date
        start = max(date(max_date.year, 1, 1), min_date)
    else:
        days = _PERIOD_OPTIONS[choice] or DEFAULT_LOOKBACK_DAYS
        end = max_date
        start = max(max_date - timedelta(days=days - 1), min_date)

    length = (end - start).days + 1
    prior_end = start - timedelta(days=1)
    # Do not clamp to min_date: clamping when start == min_date (e.g. All Time)
    # inverts the interval (prior_start > prior_end). Keep a same-length prior
    # window even when it predates available data; callers treat empty results
    # as "no comparison".
    prior_start = prior_end - timedelta(days=length - 1)

    st.session_state[_RESOLVED_END_KEY] = end

    if container.button("Refresh data", help="Clear cached query results and reload."):
        from dashboards.data import clear_data_cache

        clear_data_cache()
        st.rerun()

    return Period(
        start=start,
        end=end,
        prior_start=prior_start,
        prior_end=prior_end,
        label=choice,
        min_date=min_date,
        max_date=max_date,
    )
