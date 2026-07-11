"""
Frose All Day event product-mix forecasting for Bar Arbolada.

Jones Assembly hosts All Day Frosé each July (next door). This module:
  1. Identifies historical Frose / spike Saturdays from sales + external_events
  2. Builds a sales-weighted product mix from those days
  3. Scales to a target date using demand trend + seasonal factors
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Optional

import pandas as pd
from sqlalchemy import text

from src.analytics.demand_forecast import (
    forecast_day,
    get_seasonal_factor,
    get_trend_factor,
)
from src.config import engine

# Documented Jones Assembly All Day Frosé dates (fallback when not in external_events).
# Bar Arbolada-relevant years are typically 2023+; older dates kept for completeness.
KNOWN_FROSE_DATES: list[date] = [
    date(2023, 7, 15),  # 6th birthday — Oklahoman, Jul 14 2023
    date(2024, 7, 13),  # 7th birthday — Downtown OKC / Oklahoman
    date(2025, 7, 12),  # 8th birthday — mid-July Saturday (inferred)
]


def _q(sql: str, params: dict | None = None) -> pd.DataFrame:
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn, params=params or {})


def get_frose_events_from_db() -> pd.DataFrame:
    """Frose-related rows already stored in external_events."""
    return _q("""
        SELECT event_date, event_name, venue, event_type, expected_impact, notes
        FROM external_events
        WHERE LOWER(event_name) LIKE '%fros%'
           OR LOWER(event_name) LIKE '%frose%'
           OR (LOWER(venue) LIKE '%jones%' AND EXTRACT(MONTH FROM event_date) = 7)
        ORDER BY event_date
    """)


def detect_high_sales_mid_july_saturdays(
    min_year: int = 2023,
    sales_percentile: float = 0.90,
    min_multiplier_vs_sat_avg: float = 1.35,
) -> pd.DataFrame:
    """
    Find mid-July Saturdays that look like Frose-level volume.

    Criteria (either):
      - net_sales >= sales_percentile of all Saturdays since min_year
      - net_sales >= min_multiplier_vs_sat_avg * rolling Saturday average
    """
    return _q("""
        WITH saturdays AS (
            SELECT
                s.trading_day,
                s.net_sales,
                s.total_checks,
                s.total_guests,
                EXTRACT(YEAR FROM s.trading_day)::int AS yr,
                EXTRACT(MONTH FROM s.trading_day)::int AS mo,
                EXTRACT(DAY FROM s.trading_day)::int AS dy
            FROM pos_daily_sales s
            WHERE s.net_sales IS NOT NULL
              AND s.net_sales > 0
              AND EXTRACT(DOW FROM s.trading_day) = 6
              AND EXTRACT(YEAR FROM s.trading_day) >= :min_year
        ),
        sat_baseline AS (
            SELECT AVG(net_sales) AS avg_sat_sales
            FROM saturdays
        ),
        sat_threshold AS (
            SELECT PERCENTILE_CONT(:pct) WITHIN GROUP (ORDER BY net_sales) AS p_sales
            FROM saturdays
        ),
        candidates AS (
            SELECT
                sat.trading_day,
                sat.net_sales,
                sat.total_checks,
                sat.total_guests,
                sb.avg_sat_sales,
                st.p_sales,
                CASE WHEN sb.avg_sat_sales > 0
                     THEN sat.net_sales / sb.avg_sat_sales
                     ELSE 1 END AS vs_sat_avg
            FROM saturdays sat
            CROSS JOIN sat_baseline sb
            CROSS JOIN sat_threshold st
            WHERE sat.mo = 7
              AND sat.dy BETWEEN 5 AND 20
        )
        SELECT
            trading_day,
            net_sales,
            total_checks,
            total_guests,
            ROUND(vs_sat_avg::numeric, 2) AS vs_sat_avg,
            'auto_detected' AS source
        FROM candidates
        WHERE net_sales >= (SELECT p_sales FROM sat_threshold)
           OR vs_sat_avg >= :min_mult
        ORDER BY trading_day
    """, {
        "min_year": min_year,
        "pct": sales_percentile,
        "min_mult": min_multiplier_vs_sat_avg,
    })


def resolve_frose_reference_days(
    extra_dates: list[date] | None = None,
    min_year: int = 2023,
) -> tuple[list[date], pd.DataFrame]:
    """
    Merge external_events, known dates, auto-detected spike days, and extras.

    Returns (sorted unique dates, metadata DataFrame with net_sales per day).
    """
    dates: set[date] = set()

    events = get_frose_events_from_db()
    for d in events.get("event_date", []):
        if pd.notna(d) and d.year >= min_year:
            dates.add(pd.Timestamp(d).date())

    for d in KNOWN_FROSE_DATES:
        if d.year >= min_year:
            dates.add(d)

    if extra_dates:
        dates.update(extra_dates)

    detected = detect_high_sales_mid_july_saturdays(min_year=min_year)
    for d in detected.get("trading_day", []):
        if pd.notna(d):
            dates.add(pd.Timestamp(d).date())

    if not dates:
        return [], pd.DataFrame()

    # Keep only dates that have product-mix data (single-day reports)
    date_list = sorted(dates)
    meta = _q("""
        SELECT
            s.trading_day,
            s.net_sales,
            s.total_checks,
            s.total_guests,
            CASE WHEN pm.covered_items > 0 THEN TRUE ELSE FALSE END AS has_product_mix
        FROM pos_daily_sales s
        LEFT JOIN (
            SELECT report_start_date AS trading_day,
                   COUNT(DISTINCT item_name) AS covered_items
            FROM pos_product_mix
            WHERE entry_type = 'Item'
              AND report_start_date = report_end_date
            GROUP BY report_start_date
        ) pm ON pm.trading_day = s.trading_day
        WHERE s.trading_day = ANY(:dates)
        ORDER BY s.trading_day
    """, {"dates": date_list})

    # Only keep dates that have single-day product-mix coverage
    if meta.empty:
        return [], meta

    with_mix = meta[meta["has_product_mix"] == True]["trading_day"].tolist()  # noqa: E712
    if not with_mix:
        return [], meta

    date_list = sorted(pd.Timestamp(d).date() for d in with_mix)
    return date_list, meta


def get_daily_product_mix(trading_day: date) -> pd.DataFrame:
    """Single-day item-level product mix."""
    return _q("""
        SELECT
            item_name,
            category_name,
            qty_sold,
            net_sales,
            avg_price,
            cost
        FROM pos_product_mix
        WHERE entry_type = 'Item'
          AND report_start_date = :day
          AND report_end_date = :day
          AND COALESCE(qty_sold, 0) > 0
        ORDER BY qty_sold DESC
    """, {"day": trading_day})


def get_active_menu_items() -> pd.DataFrame:
    """Current POS catalog plus recently sold items (handles renames)."""
    return _q("""
        WITH recent_items AS (
            SELECT DISTINCT item_name, category_name
            FROM pos_product_mix
            WHERE entry_type = 'Item'
              AND report_start_date = report_end_date
              AND report_start_date >= CURRENT_DATE - INTERVAL '90 days'
              AND COALESCE(qty_sold, 0) > 0
        ),
        catalog AS (
            SELECT name AS item_name, category_name
            FROM pos_items
            WHERE status IS NULL OR LOWER(status) NOT IN ('deleted', 'inactive')
        )
        SELECT DISTINCT
            COALESCE(r.item_name, c.item_name) AS item_name,
            COALESCE(r.category_name, c.category_name) AS category_name
        FROM catalog c
        FULL OUTER JOIN recent_items r ON r.item_name = c.item_name
        WHERE COALESCE(r.item_name, c.item_name) IS NOT NULL
        ORDER BY category_name, item_name
    """)


def _sales_for_day(d: date) -> float:
    df = _q("""
        SELECT net_sales FROM pos_daily_sales
        WHERE trading_day = :d AND net_sales IS NOT NULL
    """, {"d": d})
    if df.empty:
        return 0.0
    return float(df.iloc[0]["net_sales"] or 0)


def build_frose_weighted_mix(reference_days: list[date]) -> pd.DataFrame:
    """
    Sales-weighted average qty per item across reference Frose days.

    Returns item_name, category_name, weighted_avg_qty, frose_day_count,
    total_historical_qty, share_of_units.
    """
    if not reference_days:
        return pd.DataFrame()

    frames = []
    day_weights = []
    for d in reference_days:
        mix = get_daily_product_mix(d)
        if mix.empty:
            continue
        sales = _sales_for_day(d)
        weight = sales if sales > 0 else 1.0
        mix = mix.copy()
        mix["reference_day"] = d
        mix["day_weight"] = weight
        frames.append(mix)
        day_weights.append({"reference_day": d, "net_sales": sales, "weight": weight})

    if not frames:
        return pd.DataFrame()

    all_mix = pd.concat(frames, ignore_index=True)
    all_mix["qty_sold"] = pd.to_numeric(all_mix["qty_sold"], errors="coerce").fillna(0)
    all_mix["weighted_qty"] = all_mix["qty_sold"] * all_mix["day_weight"]

    grouped = (
        all_mix.groupby(["item_name", "category_name"], as_index=False)
        .agg(
            weighted_qty_sum=("weighted_qty", "sum"),
            weight_sum=("day_weight", "sum"),
            total_historical_qty=("qty_sold", "sum"),
            frose_day_count=("reference_day", "nunique"),
            avg_unit_price=("avg_price", "mean"),
        )
    )
    grouped["weighted_avg_qty"] = grouped["weighted_qty_sum"] / grouped["weight_sum"]
    total_units = grouped["weighted_avg_qty"].sum()
    grouped["share_of_units"] = (
        grouped["weighted_avg_qty"] / total_units if total_units > 0 else 0
    )
    return grouped.sort_values("weighted_avg_qty", ascending=False)


def compute_volume_scale_factor(
    reference_days: list[date],
    target_date: date,
) -> dict:
    """
    Scale historical Frose-day volume to target date.

    Combines:
      - ratio of recent Saturday avg to historical Frose avg sales
      - demand_forecast trend + seasonal factors
    """
    frose_sales = [_sales_for_day(d) for d in reference_days]
    frose_sales = [s for s in frose_sales if s > 0]

    recent_cutoff = target_date - timedelta(weeks=8)
    recent_sats = _q("""
        SELECT AVG(net_sales) AS avg_sales
        FROM pos_daily_sales
        WHERE trading_day >= :cutoff
          AND trading_day < :target
          AND EXTRACT(DOW FROM trading_day) = 6
          AND net_sales > 0
          AND trading_day NOT IN (SELECT event_date FROM external_events)
    """, {"cutoff": recent_cutoff, "target": target_date})

    recent_sat_avg = (
        float(recent_sats.iloc[0]["avg_sales"])
        if not recent_sats.empty and recent_sats.iloc[0]["avg_sales"]
        else None
    )

    hist_frose_avg = sum(frose_sales) / len(frose_sales) if frose_sales else 0

    sat_ratio = 1.0
    if recent_sat_avg and hist_frose_avg > 0:
        sat_ratio = recent_sat_avg / hist_frose_avg

    trend = get_trend_factor()
    seasonal = get_seasonal_factor(target_date)
    forecast = forecast_day(target_date)

    # Blend forecast sales with scaled historical Frose average
    scaled_hist = hist_frose_avg * sat_ratio * trend * seasonal
    forecast_sales = float(forecast.get("predicted_daily_sales") or 0)

    if scaled_hist > 0 and forecast_sales > 0:
        expected_sales = (scaled_hist * 0.6) + (forecast_sales * 0.4)
    elif scaled_hist > 0:
        expected_sales = scaled_hist
    elif forecast_sales > 0:
        expected_sales = forecast_sales
    else:
        expected_sales = 0

    volume_scale = expected_sales / hist_frose_avg if hist_frose_avg > 0 else 1.0

    return {
        "target_date": target_date,
        "reference_days": reference_days,
        "historical_frose_avg_sales": round(hist_frose_avg, 0),
        "historical_frose_sales_by_day": dict(zip(reference_days, frose_sales)),
        "recent_saturday_avg_sales": round(recent_sat_avg or 0, 0),
        "saturday_ratio": round(sat_ratio, 3),
        "trend_factor": round(trend, 3),
        "seasonal_factor": round(seasonal, 3),
        "forecast_day_sales": round(forecast_sales, 0),
        "expected_net_sales": round(expected_sales, 0),
        "volume_scale_factor": round(volume_scale, 3),
    }


def build_frose_product_mix_forecast(
    target_date: date,
    extra_reference_days: list[date] | None = None,
    min_reference_year: int = 2023,
    include_zero_sellers: bool = True,
) -> tuple[pd.DataFrame, dict]:
    """
    Full-menu expected qty forecast for a Frose-scale day.

    Returns (forecast DataFrame, metadata dict).
    """
    ref_days, ref_meta = resolve_frose_reference_days(
        extra_dates=extra_reference_days,
        min_year=min_reference_year,
    )

    meta = compute_volume_scale_factor(ref_days, target_date)
    meta["reference_day_meta"] = ref_meta.to_dict(orient="records") if not ref_meta.empty else []

    if not ref_days:
        meta["error"] = "No Frose reference days with product-mix data found."
        return pd.DataFrame(), meta

    weighted = build_frose_weighted_mix(ref_days)
    if weighted.empty:
        meta["error"] = "Reference days found but no product-mix rows."
        return pd.DataFrame(), meta

    scale = meta["volume_scale_factor"]
    forecast = weighted.copy()
    forecast["expected_qty"] = (forecast["weighted_avg_qty"] * scale).apply(
        lambda x: max(0, math.ceil(x - 1e-9))
    )
    forecast["expected_revenue"] = (
        forecast["expected_qty"] * pd.to_numeric(forecast["avg_unit_price"], errors="coerce").fillna(0)
    ).round(2)

    if include_zero_sellers:
        menu = get_active_menu_items()
        if not menu.empty:
            merged = menu.merge(
                forecast,
                on=["item_name", "category_name"],
                how="left",
            )
            for col in ("weighted_avg_qty", "expected_qty", "expected_revenue",
                        "share_of_units", "frose_day_count", "total_historical_qty"):
                if col in merged.columns:
                    merged[col] = merged[col].fillna(0)
            forecast = merged.sort_values(
                ["expected_qty", "item_name"],
                ascending=[False, True],
            )

    forecast = forecast.sort_values(
        ["expected_qty", "weighted_avg_qty"],
        ascending=[False, False],
    ).reset_index(drop=True)

    meta["total_expected_units"] = int(forecast["expected_qty"].sum())
    meta["total_expected_revenue"] = round(float(forecast["expected_revenue"].sum()), 0)
    meta["item_count"] = len(forecast)
    meta["items_with_expected_sales"] = int((forecast["expected_qty"] > 0).sum())

    return forecast, meta
