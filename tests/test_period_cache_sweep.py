"""
Guards for the shared period + cached data sweep across analytics views.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIEWS = ROOT / "dashboards" / "views"

# Range analytics pages must use the shared period selector (not ad-hoc date_input ranges).
_PERIOD_PAGES = (
    "staffing_rush.py",
    "comps_leakage.py",
    "profitability.py",
    "product_mix.py",
    "cogs_deep_dive.py",
    "payroll.py",
    "operating_expenses.py",
)


def test_period_pages_use_shared_selector():
    for name in _PERIOD_PAGES:
        source = (VIEWS / name).read_text(encoding="utf-8")
        assert "period_selector" in source, f"{name} missing period_selector"
        assert "from dashboards.period import period_selector" in source


def test_period_pages_prefer_cached_data_layer():
    for name in _PERIOD_PAGES:
        source = (VIEWS / name).read_text(encoding="utf-8")
        assert "from dashboards.data import" in source, f"{name} should import dashboards.data"


def test_daily_sales_keeps_day_picker_but_uses_cache():
    source = (VIEWS / "daily_sales.py").read_text(encoding="utf-8")
    assert "from dashboards.data import" in source
    assert "get_all_trading_days" in source
    assert "Trading Day" in source
    # Must not force the range selector onto the single-day deep dive.
    assert "period_selector" not in source


def test_data_layer_exposes_core_cached_wrappers():
    from dashboards import data as d

    for name in (
        "get_sales_date_range",
        "get_daily_sales",
        "get_full_pnl",
        "get_comp_summary_with_cost",
        "get_prime_cost_data",
        "get_payroll_date_range",
        "get_hourly_heatmap_data",
        "clear_data_cache",
    ):
        assert hasattr(d, name), f"dashboards.data missing {name}"


def test_cached_wrappers_do_not_share_a_cache_namespace():
    """
    Regression: wrapping every query in the same inner ``wrapper`` made
    ``st.cache_data`` key only on args, so ``get_reorder_items()`` could return
    the date-range tuple from ``get_sales_date_range()``.
    """
    from dashboards.data import _cached

    def alpha(x):
        return ("alpha", x)

    def beta(x):
        return ("beta", x)

    ca = _cached(alpha)
    cb = _cached(beta)

    assert ca(1) == ("alpha", 1)
    assert cb(1) == ("beta", 1)
    assert ca(1) == ("alpha", 1)


def test_clamp_date_keeps_custom_range_in_bounds():
    from datetime import date

    from dashboards.period import _clamp_date

    assert _clamp_date(date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)) == date(2026, 2, 1)
    assert _clamp_date(date(2026, 6, 1), date(2026, 2, 1), date(2026, 3, 1)) == date(2026, 3, 1)
    assert _clamp_date(date(2026, 2, 15), date(2026, 2, 1), date(2026, 3, 1)) == date(2026, 2, 15)
