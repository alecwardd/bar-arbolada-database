"""
Reorder Alert Engine
=====================
Generates "What to Order" reports grouped by vendor,
with urgency tiers and deadline awareness.

Urgency Tiers:
  RED    = order today or stock out before next delivery
  YELLOW = order by next deadline
  GREEN  = adequate coverage (no action needed)
"""

from datetime import date, timedelta, time, datetime
from decimal import Decimal
import pandas as pd
from sqlalchemy import text

from src.config import engine


ZERO = Decimal("0")

# Day-of-week name -> weekday number (0=Mon, 6=Sun)
DOW_MAP = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


def get_reorder_report(as_of: date = None) -> pd.DataFrame:
    """
    Generate the "What to Order" report.

    Returns a DataFrame with one row per item that needs ordering,
    sorted by urgency (RED first) and grouped by vendor.
    """
    if as_of is None:
        as_of = date.today()

    with engine.connect() as conn:
        df = pd.read_sql(text("""
            SELECT
                i.id AS inv_item_id,
                i.name AS item_name,
                i.category,
                i.subcategory,
                i.unit_of_measure,
                i.par_level,
                i.reorder_point,
                i.reorder_qty,
                i.inventory_tier,
                v.id AS vendor_id,
                v.name AS vendor_name,
                v.order_deadline_day,
                v.order_deadline_time,
                v.lead_time_days,
                v.delivery_days,
                l.closing_qty,
                l.days_of_cover,
                l.theoretical_usage,
                l.reorder_alert
            FROM inv_items i
            LEFT JOIN inv_vendors v ON i.primary_vendor_id = v.id
            LEFT JOIN inv_daily_ledger l
                ON l.inv_item_id = i.id AND l.ledger_date = :as_of
            WHERE i.status = 'active'
              AND i.inventory_tier IN ('A', 'B')
            ORDER BY v.name, i.name
        """), conn, params={"as_of": as_of})

    if df.empty:
        return df

    # Calculate urgency and suggested order qty
    df["on_hand"] = df["closing_qty"].fillna(0).astype(float)
    df["par"] = df["par_level"].fillna(0).astype(float)
    df["reorder_pt"] = df["reorder_point"].fillna(0).astype(float)
    df["cover"] = df["days_of_cover"].astype(float) if "days_of_cover" in df else 0
    df["lead"] = df["lead_time_days"].fillna(2).astype(int)

    df["suggested_order"] = (df["par"] - df["on_hand"]).clip(lower=0)
    df["suggested_order"] = df.apply(
        lambda r: r["reorder_qty"] if r["reorder_qty"] and float(r["reorder_qty"]) > 0
        else r["suggested_order"],
        axis=1,
    )

    # Urgency tiers
    df["urgency"] = df.apply(lambda r: _calc_urgency(r, as_of), axis=1)

    # Filter to items that need ordering (RED or YELLOW) or have alerts
    needs_order = df[
        (df["urgency"].isin(["RED", "YELLOW"]))
        | (df["reorder_alert"] == True)
    ].copy()

    # Sort: RED first, then YELLOW, then by vendor
    urgency_order = {"RED": 0, "YELLOW": 1, "GREEN": 2}
    needs_order["urgency_sort"] = needs_order["urgency"].map(urgency_order)
    needs_order = needs_order.sort_values(["urgency_sort", "vendor_name", "item_name"])

    return needs_order


def _calc_urgency(row, as_of: date) -> str:
    """Determine urgency tier for a single item."""
    on_hand = float(row["on_hand"])
    reorder_pt = float(row["reorder_pt"])
    cover = float(row["cover"]) if pd.notna(row["cover"]) else None
    lead = int(row["lead"])

    # RED: at or below reorder point, or cover <= lead time
    if on_hand <= reorder_pt and reorder_pt > 0:
        return "RED"
    if cover is not None and cover <= lead:
        return "RED"

    # YELLOW: cover <= lead time + 2 days
    if cover is not None and cover <= lead + 2:
        return "YELLOW"

    # Also YELLOW if on_hand < par * 0.5
    par = float(row["par"]) if pd.notna(row["par_level"]) else 0
    if par > 0 and on_hand < par * 0.5:
        return "YELLOW"

    return "GREEN"


def get_vendor_deadlines(as_of: date = None) -> pd.DataFrame:
    """
    Get upcoming order deadlines for all vendors.
    Returns vendor name, next deadline datetime, and next delivery date.
    """
    if as_of is None:
        as_of = date.today()

    with engine.connect() as conn:
        vendors = pd.read_sql(text("""
            SELECT id, name, order_deadline_day, order_deadline_time,
                   lead_time_days, delivery_days
            FROM inv_vendors
            ORDER BY name
        """), conn)

    if vendors.empty:
        return vendors

    results = []
    for _, v in vendors.iterrows():
        deadline_day = v["order_deadline_day"]
        deadline_time = v["order_deadline_time"]
        lead = v["lead_time_days"] or 2

        # Find next deadline
        if deadline_day and deadline_day.lower() in DOW_MAP:
            target_dow = DOW_MAP[deadline_day.lower()]
            current_dow = as_of.weekday()
            days_ahead = (target_dow - current_dow) % 7
            if days_ahead == 0:
                # If today is deadline day, check if past deadline time
                if deadline_time and datetime.now().time() > deadline_time:
                    days_ahead = 7  # next week
            next_deadline = as_of + timedelta(days=days_ahead)
        else:
            next_deadline = None

        # Estimate next delivery
        next_delivery = (as_of + timedelta(days=lead)) if lead else None

        results.append({
            "vendor_name": v["name"],
            "next_deadline": next_deadline,
            "deadline_time": deadline_time,
            "next_delivery": next_delivery,
            "lead_time_days": lead,
        })

    return pd.DataFrame(results)
