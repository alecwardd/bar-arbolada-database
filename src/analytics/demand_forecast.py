"""
Predictive Demand Engine for Bar Arbolada Scheduling Suite.

4-layer prediction model:
  Predicted(day, hour) = Baseline(DOW, hour)
                         x EventMultiplier
                         x SeasonalFactor
                         x TrendFactor

Then converts predicted sales into staffing recommendations using
target SPLH and historical role ratios.
"""

import math
from datetime import date, time, timedelta
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import text

from src.config import engine


# ============================================================================
# INTERNAL HELPERS
# ============================================================================

def _q(sql: str, params: dict = None) -> pd.DataFrame:
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn, params=params or {})


def _get_scheduling_settings() -> dict:
    """Load single-row scheduling_settings as a dict."""
    df = _q("SELECT * FROM scheduling_settings ORDER BY id LIMIT 1")
    if df.empty:
        return {
            "target_splh": 55.0,
            "min_bartenders": 1,
            "min_barbacks": 1,
            "default_shift_length_hours": 7.0,
            "bartender_hour_ratio": 0.65,
            "event_multiplier_thunder": 1.80,
            "event_multiplier_concert": 1.50,
            "event_multiplier_show": 1.30,
            "event_multiplier_convention": 1.15,
            "cut_threshold_per_bartender": 100.0,
        }
    row = df.iloc[0]
    return {k: float(v) if isinstance(v, (int, float, np.integer, np.floating))
            else v for k, v in row.to_dict().items()}


# ============================================================================
# LAYER 1: BASELINE DEMAND MATRIX (DOW x Hour)
# ============================================================================

def get_baseline_matrix(weeks: int = 8,
                        exclude_event_days: bool = True) -> pd.DataFrame:
    """
    Rolling N-week average of hourly sales by (day_of_week, hour_of_day).
    Optionally excludes days with external events to keep baseline clean.

    Returns DataFrame with columns:
        dow (0=Sun..6=Sat, Postgres convention), dow_name, hour_of_day,
        avg_net_sales, avg_checks, avg_guests, num_days
    """
    cutoff = date.today() - timedelta(weeks=weeks)

    event_exclude = ""
    if exclude_event_days:
        event_exclude = """
            AND h.trading_day NOT IN (
                SELECT event_date FROM external_events
            )
        """

    return _q(f"""
        SELECT
            EXTRACT(DOW FROM h.trading_day)::int AS dow,
            TO_CHAR(h.trading_day, 'Dy') AS dow_name,
            h.hour_of_day,
            AVG(h.net_sales) AS avg_net_sales,
            AVG(h.check_count) AS avg_checks,
            AVG(h.guest_count) AS avg_guests,
            COUNT(DISTINCT h.trading_day) AS num_days
        FROM pos_hourly_sales h
        WHERE h.trading_day >= :cutoff
          AND h.net_sales IS NOT NULL
          {event_exclude}
        GROUP BY EXTRACT(DOW FROM h.trading_day),
                 TO_CHAR(h.trading_day, 'Dy'),
                 h.hour_of_day
        ORDER BY dow, h.hour_of_day
    """, {"cutoff": cutoff})


def get_baseline_daily_totals(weeks: int = 8,
                              exclude_event_days: bool = True) -> pd.DataFrame:
    """
    Rolling N-week average of daily net sales by day-of-week.
    Used for daily-level predictions when hourly granularity isn't needed.
    """
    cutoff = date.today() - timedelta(weeks=weeks)

    event_exclude = ""
    if exclude_event_days:
        event_exclude = """
            AND s.trading_day NOT IN (
                SELECT event_date FROM external_events
            )
        """

    return _q(f"""
        SELECT
            EXTRACT(DOW FROM s.trading_day)::int AS dow,
            TO_CHAR(s.trading_day, 'Dy') AS dow_name,
            AVG(s.net_sales) AS avg_net_sales,
            AVG(s.total_checks) AS avg_checks,
            AVG(s.total_guests) AS avg_guests,
            COUNT(*) AS num_days
        FROM pos_daily_sales s
        WHERE s.trading_day >= :cutoff
          AND s.net_sales IS NOT NULL
          AND s.net_sales > 0
          {event_exclude}
        GROUP BY EXTRACT(DOW FROM s.trading_day),
                 TO_CHAR(s.trading_day, 'Dy')
        ORDER BY dow
    """, {"cutoff": cutoff})


# ============================================================================
# LAYER 2: EVENT MULTIPLIER
# ============================================================================

def get_event_multipliers_historical() -> pd.DataFrame:
    """
    Compare event-day sales vs same-DOW non-event-day sales to compute
    actual multipliers from historical data.

    Returns one row per event_type with:
        event_type, avg_event_sales, avg_normal_sales, multiplier, sample_size
    """
    return _q("""
        WITH event_days AS (
            SELECT
                e.event_date,
                e.event_type,
                EXTRACT(DOW FROM e.event_date)::int AS dow,
                s.net_sales
            FROM external_events e
            JOIN pos_daily_sales s ON s.trading_day = e.event_date
            WHERE s.net_sales > 0
        ),
        normal_avgs AS (
            SELECT
                EXTRACT(DOW FROM s.trading_day)::int AS dow,
                AVG(s.net_sales) AS avg_normal_sales
            FROM pos_daily_sales s
            WHERE s.net_sales > 0
              AND s.trading_day NOT IN (SELECT event_date FROM external_events)
            GROUP BY EXTRACT(DOW FROM s.trading_day)
        )
        SELECT
            ed.event_type,
            AVG(ed.net_sales) AS avg_event_sales,
            AVG(na.avg_normal_sales) AS avg_normal_sales,
            CASE WHEN AVG(na.avg_normal_sales) > 0
                 THEN ROUND((AVG(ed.net_sales) / AVG(na.avg_normal_sales))::numeric, 2)
                 ELSE 1.0 END AS multiplier,
            COUNT(*) AS sample_size
        FROM event_days ed
        JOIN normal_avgs na ON ed.dow = na.dow
        GROUP BY ed.event_type
        ORDER BY multiplier DESC
    """)


def get_event_multiplier(target_date: date) -> float:
    """
    Return the demand multiplier for a specific date.
    Uses historical multiplier if enough data exists (5+ events),
    otherwise falls back to configured defaults.
    Returns 1.0 if no event on that date.
    """
    events = _q("""
        SELECT event_type, expected_impact
        FROM external_events
        WHERE event_date = :d
    """, {"d": target_date})

    if events.empty:
        return 1.0

    settings = _get_scheduling_settings()

    historical = get_event_multipliers_historical()
    hist_map = {}
    if not historical.empty:
        for _, row in historical.iterrows():
            if row["sample_size"] >= 5:
                hist_map[row["event_type"]] = float(row["multiplier"])

    type_to_setting_key = {
        "thunder_home": "event_multiplier_thunder",
        "concert": "event_multiplier_concert",
        "show": "event_multiplier_show",
        "convention": "event_multiplier_convention",
    }

    max_mult = 1.0
    for _, evt in events.iterrows():
        et = evt["event_type"]
        if et in hist_map:
            mult = hist_map[et]
        else:
            key = type_to_setting_key.get(et, "event_multiplier_show")
            mult = float(settings.get(key, 1.3))
        max_mult = max(max_mult, mult)

    return max_mult


# ============================================================================
# LAYER 3: SEASONAL FACTOR
# ============================================================================

def get_seasonal_factor(target_date: date) -> float:
    """
    Monthly adjustment factor.
    Ratio of average daily sales in the target month (historical)
    to the overall average daily sales.
    Returns 1.0 if insufficient data.
    """
    target_month = target_date.month

    df = _q("""
        SELECT
            EXTRACT(MONTH FROM trading_day)::int AS month,
            AVG(net_sales) AS avg_daily
        FROM pos_daily_sales
        WHERE net_sales > 0
        GROUP BY EXTRACT(MONTH FROM trading_day)
    """)

    if df.empty or len(df) < 2:
        return 1.0

    overall_avg = df["avg_daily"].astype(float).mean()
    if overall_avg <= 0:
        return 1.0

    month_row = df[df["month"] == target_month]
    if month_row.empty:
        return 1.0

    return float(month_row.iloc[0]["avg_daily"]) / overall_avg


# ============================================================================
# LAYER 4: TREND FACTOR
# ============================================================================

def get_trend_factor() -> float:
    """
    Recent 4-week moving average vs 12-week moving average.
    If the bar is trending up, factor > 1.0; trending down, < 1.0.
    """
    today = date.today()
    four_weeks_ago = today - timedelta(weeks=4)
    twelve_weeks_ago = today - timedelta(weeks=12)

    df = _q("""
        SELECT
            CASE WHEN trading_day >= :four_wk THEN 'recent' ELSE 'older' END AS period,
            AVG(net_sales) AS avg_sales
        FROM pos_daily_sales
        WHERE trading_day >= :twelve_wk
          AND net_sales > 0
        GROUP BY CASE WHEN trading_day >= :four_wk THEN 'recent' ELSE 'older' END
    """, {"four_wk": four_weeks_ago, "twelve_wk": twelve_weeks_ago})

    if df.empty or len(df) < 2:
        return 1.0

    recent = df.loc[df["period"] == "recent", "avg_sales"]
    older = df.loc[df["period"] == "older", "avg_sales"]

    if recent.empty or older.empty:
        return 1.0

    r = float(recent.iloc[0])
    o = float(older.iloc[0])

    if o <= 0:
        return 1.0

    factor = r / o
    return max(0.7, min(factor, 1.4))


# ============================================================================
# COMBINED FORECAST
# ============================================================================

def forecast_day(target_date: date, weeks: int = 8) -> dict:
    """
    Produce a full-day forecast for target_date.

    Returns dict:
        date, dow_name,
        predicted_daily_sales, predicted_checks,
        event_multiplier, seasonal_factor, trend_factor,
        events: [list of event names],
        hourly: [{hour, predicted_sales, predicted_checks}, ...]
    """
    from calendar import day_abbr

    dow_pg = target_date.isoweekday() % 7  # Postgres DOW: Sun=0, Mon=1, ..., Sat=6

    baseline = get_baseline_matrix(weeks=weeks)
    event_mult = get_event_multiplier(target_date)
    seasonal = get_seasonal_factor(target_date)
    trend = get_trend_factor()

    dow_baseline = baseline[baseline["dow"] == dow_pg].copy()

    biz_hours = list(range(11, 24)) + [0, 1, 2]
    hourly = []
    total_sales = 0.0
    total_checks = 0.0

    for hour in biz_hours:
        row = dow_baseline[dow_baseline["hour_of_day"] == hour]
        if row.empty:
            base_sales = 0.0
            base_checks = 0.0
        else:
            base_sales = float(row.iloc[0]["avg_net_sales"])
            base_checks = float(row.iloc[0]["avg_checks"])

        pred_sales = base_sales * event_mult * seasonal * trend
        pred_checks = base_checks * event_mult * seasonal * trend

        hourly.append({
            "hour": hour,
            "predicted_sales": round(pred_sales, 0),
            "predicted_checks": round(pred_checks, 1),
            "baseline_sales": round(base_sales, 0),
        })
        total_sales += pred_sales
        total_checks += pred_checks

    events_df = _q("""
        SELECT event_name, event_type, venue, expected_impact, event_time
        FROM external_events WHERE event_date = :d
    """, {"d": target_date})

    events_list = []
    if not events_df.empty:
        for _, e in events_df.iterrows():
            events_list.append({
                "name": e["event_name"],
                "type": e["event_type"],
                "venue": e["venue"],
                "impact": e["expected_impact"],
                "time": str(e["event_time"]) if e["event_time"] else None,
            })

    dow_names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    dow_name = dow_names[dow_pg]

    return {
        "date": target_date,
        "dow_name": dow_name,
        "predicted_daily_sales": round(total_sales, 0),
        "predicted_checks": round(total_checks, 0),
        "event_multiplier": round(event_mult, 2),
        "seasonal_factor": round(seasonal, 3),
        "trend_factor": round(trend, 3),
        "events": events_list,
        "hourly": hourly,
    }


def forecast_range(start: date, end: date, weeks: int = 8) -> list[dict]:
    """Forecast multiple days. Returns list of forecast_day results."""
    results = []
    current = start
    while current <= end:
        results.append(forecast_day(current, weeks=weeks))
        current += timedelta(days=1)
    return results


# ============================================================================
# STAFFING RECOMMENDATIONS
# ============================================================================

def recommend_staffing(target_date: date, weeks: int = 8,
                       target_splh: float = None) -> dict:
    """
    Convert demand forecast into staffing recommendations.

    Returns:
        date, predicted_sales,
        required_labor_hours, recommended_bartenders, recommended_barbacks,
        projected_labor_cost, projected_labor_pct,
        shift_cuts: [{hour, action, reason}, ...],
        hourly_staffing: [{hour, bartenders, barbacks, predicted_sales}, ...]
    """
    settings = _get_scheduling_settings()
    if target_splh is None:
        target_splh = float(settings.get("target_splh", 55))

    forecast = forecast_day(target_date, weeks=weeks)
    predicted_sales = forecast["predicted_daily_sales"]

    min_bt = int(settings.get("min_bartenders", 1))
    min_bb = int(settings.get("min_barbacks", 1))
    shift_len = float(settings.get("default_shift_length_hours", 7))
    bt_ratio = float(settings.get("bartender_hour_ratio", 0.65))
    cut_threshold = float(settings.get("cut_threshold_per_bartender", 100))

    if predicted_sales <= 0 or target_splh <= 0:
        return {
            "date": target_date,
            "predicted_sales": 0,
            "required_labor_hours": 0,
            "recommended_bartenders": min_bt,
            "recommended_barbacks": min_bb,
            "projected_labor_cost": 0,
            "projected_labor_pct": 0,
            "shift_cuts": [],
            "hourly_staffing": [],
        }

    required_hours = predicted_sales / target_splh
    bt_hours = required_hours * bt_ratio
    bb_hours = required_hours * (1 - bt_ratio)

    rec_bt = max(min_bt, math.ceil(bt_hours / shift_len))
    rec_bb = max(min_bb, math.ceil(bb_hours / shift_len))

    avg_hourly_wage = _get_avg_hourly_wage()
    projected_cost = required_hours * avg_hourly_wage
    projected_pct = (projected_cost / predicted_sales * 100) if predicted_sales > 0 else 0

    hourly_staffing = []
    shift_cuts = []

    peak_bt = rec_bt
    current_bt = rec_bt

    for h in forecast["hourly"]:
        hour = h["hour"]
        pred_h = h["predicted_sales"]

        needed_bt = max(min_bt, math.ceil(pred_h / cut_threshold)) if pred_h > 0 else min_bt
        needed_bt = min(needed_bt, peak_bt)

        bb_for_hour = max(min_bb, math.ceil(needed_bt * (1 - bt_ratio) / bt_ratio)) if needed_bt > 0 else min_bb

        if needed_bt < current_bt:
            cut_count = current_bt - needed_bt
            shift_cuts.append({
                "hour": hour,
                "action": f"Cut {cut_count} bartender{'s' if cut_count > 1 else ''}",
                "reason": f"Predicted sales ${pred_h:.0f}/hr "
                          f"(${pred_h / max(needed_bt, 1):.0f}/bartender)",
            })
            current_bt = needed_bt

        hourly_staffing.append({
            "hour": hour,
            "bartenders": needed_bt,
            "barbacks": bb_for_hour,
            "predicted_sales": pred_h,
        })

    return {
        "date": target_date,
        "predicted_sales": predicted_sales,
        "required_labor_hours": round(required_hours, 1),
        "recommended_bartenders": rec_bt,
        "recommended_barbacks": rec_bb,
        "projected_labor_cost": round(projected_cost, 0),
        "projected_labor_pct": round(projected_pct, 1),
        "shift_cuts": shift_cuts,
        "hourly_staffing": hourly_staffing,
    }


def get_shift_cut_recommendations(weeks: int = 8) -> pd.DataFrame:
    """
    Per-DOW recommended cut times based on when hourly sales drop below
    the cut threshold per bartender.

    Returns DataFrame:
        dow_name, hour, avg_sales, recommended_bartenders, action
    """
    settings = _get_scheduling_settings()
    cut_threshold = float(settings.get("cut_threshold_per_bartender", 100))
    min_bt = int(settings.get("min_bartenders", 1))

    baseline = get_baseline_matrix(weeks=weeks)
    if baseline.empty:
        return pd.DataFrame()

    biz_hours = list(range(11, 24)) + [0, 1, 2]
    rows = []

    for dow in range(7):
        dow_data = baseline[baseline["dow"] == dow]
        dow_name = dow_data["dow_name"].iloc[0] if not dow_data.empty else ""

        peak_bt = 1
        for hour in biz_hours:
            hr_data = dow_data[dow_data["hour_of_day"] == hour]
            avg_sales = float(hr_data.iloc[0]["avg_net_sales"]) if not hr_data.empty else 0

            needed = max(min_bt, math.ceil(avg_sales / cut_threshold)) if avg_sales > 0 else min_bt
            peak_bt = max(peak_bt, needed)

        prev_bt = peak_bt
        for hour in biz_hours:
            hr_data = dow_data[dow_data["hour_of_day"] == hour]
            avg_sales = float(hr_data.iloc[0]["avg_net_sales"]) if not hr_data.empty else 0

            needed = max(min_bt, math.ceil(avg_sales / cut_threshold)) if avg_sales > 0 else min_bt
            needed = min(needed, peak_bt)

            action = ""
            if needed < prev_bt:
                cut_n = prev_bt - needed
                action = f"Cut {cut_n}"

            rows.append({
                "dow_name": dow_name,
                "dow": dow,
                "hour": hour,
                "avg_sales": round(avg_sales, 0),
                "recommended_bartenders": needed,
                "action": action,
            })
            prev_bt = needed

    return pd.DataFrame(rows)


def _get_avg_hourly_wage() -> float:
    """Average hourly wage from recent labor data (last 90 days)."""
    cutoff = date.today() - timedelta(days=90)
    df = _q("""
        SELECT AVG(pay_per_hour) AS avg_wage
        FROM pos_labor pl
        JOIN import_logs il ON il.id = pl.import_log_id
        WHERE il.import_type = 'labor' AND il.status = 'success'
          AND pl.trading_day >= :cutoff
          AND pl.pay_per_hour > 0
    """, {"cutoff": cutoff})

    if df.empty or df.iloc[0]["avg_wage"] is None:
        return 12.0  # Oklahoma tipped minimum wage fallback
    return float(df.iloc[0]["avg_wage"])


# ============================================================================
# WEEKLY SUMMARY FOR SCHEDULE BUILDER
# ============================================================================

def forecast_week_summary(start: date) -> pd.DataFrame:
    """
    7-day forecast starting from `start`, with staffing recommendations.
    Returns DataFrame with one row per day:
        date, dow_name, predicted_sales, event_names,
        rec_bartenders, rec_barbacks, projected_labor_cost, projected_labor_pct
    """
    rows = []
    for i in range(7):
        d = start + timedelta(days=i)
        rec = recommend_staffing(d)

        events = forecast_day(d)["events"]
        event_names = ", ".join(e["name"] for e in events) if events else ""

        rows.append({
            "date": d,
            "dow_name": rec.get("date", d),
            "predicted_sales": rec["predicted_sales"],
            "event_names": event_names,
            "rec_bartenders": rec["recommended_bartenders"],
            "rec_barbacks": rec["recommended_barbacks"],
            "projected_labor_cost": rec["projected_labor_cost"],
            "projected_labor_pct": rec["projected_labor_pct"],
        })

    df = pd.DataFrame(rows)
    dow_names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    df["dow_name"] = df["date"].apply(lambda d: dow_names[d.isoweekday() % 7])
    return df
