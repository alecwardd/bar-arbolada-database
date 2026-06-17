"""
Inventory Item Catalog
========================
- Current catalog with stock status, pour economics, and quick qty-on-hand updates
- Add new items with category-aware packaging fields and live pour economics preview
- Edit existing items with purchase history and POS item linking
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
import pandas as pd
from datetime import datetime
from decimal import Decimal

from src.config import get_session
from src.models import InvItem, InvVendor
from src.analytics.queries import (
    get_inv_items,
    get_vendor_names,
    get_vendor_id_by_name,
    get_item_purchase_history,
    get_pos_items_for_linking,
    update_inv_item,
)

st.set_page_config(page_title="Inventory Items | Bar Arbolada", page_icon="📦", layout="wide")
st.title("📦 Inventory Item Catalog")
st.caption(
    "Manage your Tier A & B inventory items. Track stock on hand, pour economics, "
    "and cost per serving against invoice prices."
)

# ── Constants ──────────────────────────────────────────────────────────────────

CATEGORY_OPTIONS = [
    "spirits", "wine", "beer", "food", "non-alcoholic",
    "supplies", "paper_goods", "cleaning",
]

SUBCATEGORY_OPTIONS = {
    "spirits": ["bourbon", "whiskey", "rye", "tequila", "mezcal", "vodka", "gin",
                "rum", "brandy", "scotch", "cordial", "amaro", "vermouth",
                "bitters", "other"],
    "wine":    ["red", "white", "rosé", "sparkling", "natural", "dessert", "other"],
    "beer":    ["draft", "bottle", "can", "cider", "other"],
    "food":    ["protein", "produce", "dairy", "dry_goods", "frozen",
                "condiments", "garnish", "bread", "other"],
    "non-alcoholic": ["juice", "soda", "mixer", "syrup", "water",
                      "coffee", "tea", "other"],
    "supplies":    ["glassware", "barware", "smallwares", "other"],
    "paper_goods": ["napkins", "straws", "to-go", "other"],
    "cleaning":    ["chemicals", "towels", "other"],
}

# Common bottle sizes: (label, ml value, oz equivalent)
BOTTLE_SIZES = [
    ("50 ml (1.7 oz)",   50,   1.7),
    ("200 ml (6.8 oz)",  200,  6.8),
    ("375 ml (12.7 oz)", 375,  12.7),
    ("500 ml (16.9 oz)", 500,  16.9),
    ("700 ml (23.7 oz)", 700,  23.7),
    ("750 ml (25.4 oz)", 750,  25.4),
    ("1 L (33.8 oz)",    1000, 33.8),
    ("1.75 L (59.2 oz)", 1750, 59.2),
    ("Custom",           None, None),
]
BOTTLE_SIZE_LABELS = [b[0] for b in BOTTLE_SIZES]
BOTTLE_SIZE_ML     = {b[0]: b[1] for b in BOTTLE_SIZES}

# Keg sizes for draft beer: (label, ml value)
KEG_SIZES = [
    ("1/6 bbl (5.2 gal / 661 oz)",  19550),
    ("1/4 bbl (7.75 gal / 992 oz)", 29320),
    ("1/2 bbl (15.5 gal / 1984 oz)", 58670),
    ("50 L (13.2 gal / 1690 oz)",   50000),
]
KEG_SIZE_LABELS = [k[0] for k in KEG_SIZES]
KEG_SIZE_ML     = {k[0]: k[1] for k in KEG_SIZES}

# Default pour sizes by category/subcategory
DEFAULT_POUR_OZ = {
    "spirits": 1.5,
    "wine":    5.0,
    "beer":    16.0,  # draft pint
    "food":    None,
    "non-alcoholic": None,
    "supplies": None,
    "paper_goods": None,
    "cleaning": None,
}


def _safe_float(val, default=0.0):
    try:
        return float(val) if val is not None else default
    except (TypeError, ValueError):
        return default


def _derive_pour_stats(bottle_size_ml, standard_pour_oz, unit_cost, menu_price):
    """Return dict of derived pour economics, or None values if inputs are missing."""
    stats = {
        "bottle_size_oz": None,
        "pours_per_unit": None,
        "cost_per_pour":  None,
        "pour_cost_pct":  None,
        "revenue_per_unit": None,
        "profit_per_unit":  None,
    }
    if not bottle_size_ml or not standard_pour_oz:
        return stats
    bottle_oz = bottle_size_ml / 29.5735
    pours = bottle_oz / standard_pour_oz
    stats["bottle_size_oz"] = round(bottle_oz, 1)
    stats["pours_per_unit"] = round(pours, 0)
    if unit_cost:
        cpp = unit_cost / pours
        stats["cost_per_pour"] = round(cpp, 2)
        if menu_price:
            stats["pour_cost_pct"]   = round(cpp / menu_price * 100, 1)
            stats["revenue_per_unit"] = round(menu_price * pours, 2)
            stats["profit_per_unit"]  = round((menu_price - cpp) * pours, 2)
    return stats


def _render_economics_preview(bottle_size_ml, standard_pour_oz, unit_cost, menu_price, container):
    """Render the live pour economics preview card into `container`."""
    stats = _derive_pour_stats(bottle_size_ml, standard_pour_oz, unit_cost, menu_price)
    if stats["pours_per_unit"] is None:
        container.info("Fill in Bottle Size and Standard Pour to see economics preview.")
        return
    lines = []
    lines.append(
        f"**{int(stats['pours_per_unit'])} pours** per unit "
        f"({stats['bottle_size_oz']} oz bottle ÷ {standard_pour_oz} oz pour)"
    )
    if stats["cost_per_pour"] is not None:
        lines.append(f"Cost/Pour: **${stats['cost_per_pour']:.2f}**")
    if stats["pour_cost_pct"] is not None:
        pct = stats["pour_cost_pct"]
        color = "🟢" if pct < 20 else ("🟡" if pct < 30 else "🔴")
        lines.append(f"Pour Cost: **{pct:.1f}%** {color}")
    if stats["revenue_per_unit"] is not None:
        lines.append(
            f"Revenue/Unit: **${stats['revenue_per_unit']:,.2f}** | "
            f"Profit/Unit: **${stats['profit_per_unit']:,.2f}**"
        )
    container.success("  \n".join(lines))


# ── Tabs ────────────────────────────────────────────────────────────────────────

tab_catalog, tab_add, tab_edit = st.tabs([
    "📋 Current Catalog",
    "➕ Add Item",
    "✏️ Edit Item",
])


# ════════════════════════════════════════════════════════════════════════════════
# TAB 1: CURRENT CATALOG
# ════════════════════════════════════════════════════════════════════════════════

with tab_catalog:
    items_df = get_inv_items()

    if items_df.empty:
        st.info(
            "No inventory items yet. Use the **Add Item** tab to build your catalog. "
            "Start with your top 20 highest-cost items (Tier A)."
        )
    else:
        # ── Filters ──────────────────────────────────────────────────────────
        f1, f2, f3 = st.columns(3)
        with f1:
            cat_filter = st.multiselect(
                "Category",
                sorted(items_df["category"].dropna().unique()),
                default=[],
            )
        with f2:
            tier_filter = st.multiselect(
                "Tier",
                sorted(items_df["inventory_tier"].dropna().unique()),
                default=[],
            )
        with f3:
            vendor_filter = st.multiselect(
                "Vendor",
                sorted(items_df["vendor_name"].dropna().unique()),
                default=[],
            )

        filtered = items_df.copy()
        if cat_filter:
            filtered = filtered[filtered["category"].isin(cat_filter)]
        if tier_filter:
            filtered = filtered[filtered["inventory_tier"].isin(tier_filter)]
        if vendor_filter:
            filtered = filtered[filtered["vendor_name"].isin(vendor_filter)]

        # ── KPIs ─────────────────────────────────────────────────────────────
        k1, k2, k3, k4, k5 = st.columns(5)
        with k1:
            st.metric("Total Items", len(filtered))
        with k2:
            st.metric("Tier A", len(filtered[filtered["inventory_tier"] == "A"]))
        with k3:
            st.metric("Tier B", len(filtered[filtered["inventory_tier"] == "B"]))
        with k4:
            has_cost = len(filtered[filtered["unit_cost"].notna() & (filtered["unit_cost"].astype(float) > 0)])
            st.metric("With Cost Data", f"{has_cost}/{len(filtered)}")
        with k5:
            pct_data = filtered["pour_cost_pct"].dropna()
            if len(pct_data) > 0:
                avg_pct = float(pct_data.astype(float).mean())
                st.metric("Avg Pour Cost", f"{avg_pct:.1f}%")
            else:
                st.metric("Avg Pour Cost", "—")

        st.markdown("---")

        # ── Catalog table via st.data_editor (current_qty editable) ──────────
        st.caption(
            "**Stock status:** 🔴 below reorder point | 🟡 below par | 🟢 at/above par  |  "
            "**Pour cost:** 🟢 <20% | 🟡 20-30% | 🔴 >30%  |  "
            "Edit **Qty on Hand** inline and click Save."
        )

        # Build display dataframe
        disp = filtered[[
            "id", "name", "category", "inventory_tier", "vendor_name",
            "current_qty", "par_level", "reorder_point",
            "bottle_size_ml", "standard_pour_oz", "purchase_unit", "pack_size",
            "unit_cost", "cost_per_pour", "menu_price", "pour_cost_pct",
            "pours_per_unit",
        ]].copy()

        # Stock status emoji
        def stock_status(row):
            qty   = _safe_float(row["current_qty"], default=None)
            par   = _safe_float(row["par_level"], default=None)
            reord = _safe_float(row["reorder_point"], default=None)
            if qty is None:
                return "—"
            if reord is not None and qty <= reord:
                return f"🔴 {qty}"
            if par is not None and qty < par:
                return f"🟡 {qty}"
            return f"🟢 {qty}"

        def pour_cost_display(val):
            if val is None or (isinstance(val, float) and pd.isna(val)):
                return "—"
            pct = float(val)
            if pct < 20:
                return f"🟢 {pct:.1f}%"
            if pct < 30:
                return f"🟡 {pct:.1f}%"
            return f"🔴 {pct:.1f}%"

        # Format columns for display
        disp["Stock"] = disp.apply(stock_status, axis=1)
        disp["Pour Cost"] = disp["pour_cost_pct"].apply(pour_cost_display)
        disp["Cost/Pour"] = disp["cost_per_pour"].apply(
            lambda x: f"${float(x):.2f}" if pd.notna(x) and x is not None else "—"
        )
        disp["Unit Cost"] = disp["unit_cost"].apply(
            lambda x: f"${float(x):,.2f}" if pd.notna(x) and x is not None else "—"
        )
        disp["Menu Price"] = disp["menu_price"].apply(
            lambda x: f"${float(x):.2f}" if pd.notna(x) and x is not None else "—"
        )
        disp["Bottle"] = disp.apply(
            lambda r: (
                f"{int(r['bottle_size_ml'])}ml"
                if pd.notna(r["bottle_size_ml"]) and r["bottle_size_ml"] is not None
                else "—"
            ),
            axis=1,
        )
        disp["Pour"] = disp["standard_pour_oz"].apply(
            lambda x: f"{float(x):.1f} oz" if pd.notna(x) and x is not None else "—"
        )
        disp["Pours/Unit"] = disp["pours_per_unit"].apply(
            lambda x: str(int(float(x))) if pd.notna(x) and x is not None else "—"
        )
        disp["Par"] = disp["par_level"].apply(
            lambda x: str(float(x)) if pd.notna(x) and x is not None else "—"
        )

        table_cols = [
            "name", "category", "inventory_tier", "vendor_name",
            "Stock", "Par", "Bottle", "Pour", "Pours/Unit",
            "Unit Cost", "Cost/Pour", "Menu Price", "Pour Cost",
        ]
        table_df = disp[table_cols].copy()
        table_df.columns = [
            "Item", "Category", "Tier", "Vendor",
            "Qty on Hand", "Par", "Bottle", "Pour Size", "Pours/Unit",
            "Unit Cost", "Cost/Pour", "Menu Price", "Pour Cost %",
        ]

        # Editable qty-on-hand section
        st.subheader("Quick Qty Update")
        with st.expander("Update quantities on hand (click to expand)", expanded=False):
            qty_edit_df = filtered[["id", "name", "current_qty"]].copy()
            qty_edit_df["current_qty"] = qty_edit_df["current_qty"].apply(
                lambda x: float(x) if pd.notna(x) and x is not None else 0.0
            )
            qty_edit_df.columns = ["id", "Item", "Qty on Hand"]
            edited = st.data_editor(
                qty_edit_df,
                column_config={
                    "id": st.column_config.NumberColumn("ID", disabled=True),
                    "Item": st.column_config.TextColumn("Item", disabled=True),
                    "Qty on Hand": st.column_config.NumberColumn(
                        "Qty on Hand",
                        min_value=0.0,
                        step=0.5,
                        format="%.1f",
                        help="Partial bottles count (e.g. 0.5 = half bottle)",
                    ),
                },
                hide_index=True,
                use_container_width=True,
            )
            if st.button("💾 Save Quantities", type="primary"):
                session = get_session()
                try:
                    updated = 0
                    for _, row in edited.iterrows():
                        item = session.query(InvItem).filter(InvItem.id == int(row["id"])).first()
                        if item:
                            new_qty = Decimal(str(row["Qty on Hand"]))
                            if item.current_qty != new_qty:
                                item.current_qty = new_qty
                                item.updated_at = datetime.utcnow()
                                updated += 1
                    session.commit()
                    if updated:
                        st.success(f"Updated {updated} item(s).")
                        st.rerun()
                    else:
                        st.info("No changes detected.")
                except Exception as e:
                    st.error(f"Error saving: {e}")
                finally:
                    session.close()

        st.markdown("---")
        st.subheader("Full Catalog")
        st.dataframe(table_df, hide_index=True, use_container_width=True, height=500)


# ════════════════════════════════════════════════════════════════════════════════
# TAB 2: ADD ITEM
# ════════════════════════════════════════════════════════════════════════════════

with tab_add:
    st.subheader("Add Inventory Item")
    st.caption(
        "Start with Tier A items (your top 20 highest-cost products). "
        "These typically include premium spirits, wines, and high-value food items."
    )

    vendor_names = get_vendor_names()

    # ── Section 1: Basic Info ─────────────────────────────────────────────────
    st.markdown("#### Basic Info")
    a1, a2, a3 = st.columns(3)
    with a1:
        add_name = st.text_input("Item Name *", placeholder="e.g., Bourbon 750ml", key="add_name")
    with a2:
        add_category = st.selectbox("Category *", CATEGORY_OPTIONS, key="add_category")
    with a3:
        sub_opts = SUBCATEGORY_OPTIONS.get(add_category, ["other"])
        add_subcategory = st.selectbox("Subcategory", sub_opts, key="add_subcategory")

    # ── Section 2: Packaging & Measurement (category-aware) ──────────────────
    st.markdown("#### Packaging & Measurement")

    is_pourable = add_category in ("spirits", "wine", "cordial", "amaro")
    is_draft    = add_category == "beer" and add_subcategory == "draft"
    is_packaged_beer = add_category == "beer" and add_subcategory != "draft"

    if is_draft:
        pb1, pb2, pb3 = st.columns(3)
        with pb1:
            keg_label = st.selectbox("Keg Size", KEG_SIZE_LABELS, key="add_keg_size")
            add_bottle_ml = KEG_SIZE_ML[keg_label]
        with pb2:
            add_purchase_unit = "keg"
            st.text_input("Purchase Unit", value="keg", disabled=True)
            add_pack_size = 1
        with pb3:
            add_pour_oz = st.number_input(
                "Standard Pour (oz)", min_value=0.0, value=16.0, step=0.5, format="%.1f",
                help="Typical pint = 16 oz; half-pint = 8 oz", key="add_pour_oz_draft"
            )
        add_uom = "keg"

    elif is_packaged_beer:
        pb1, pb2, pb3, pb4 = st.columns(4)
        with pb1:
            beer_size_label = st.selectbox(
                "Container Size",
                ["12 oz can", "12 oz bottle", "16 oz can", "22 oz bottle", "Custom"],
                key="add_beer_size"
            )
            beer_size_map = {"12 oz can": 355, "12 oz bottle": 355, "16 oz can": 473, "22 oz bottle": 651, "Custom": None}
            if beer_size_map[beer_size_label] is not None:
                add_bottle_ml = beer_size_map[beer_size_label]
            else:
                add_bottle_ml = st.number_input("Custom size (ml)", min_value=0, value=355, step=1, key="add_beer_custom_ml")
        with pb2:
            add_purchase_unit = st.selectbox("Purchase Unit", ["case", "pack", "each"], key="add_beer_pu")
        with pb3:
            add_pack_size = st.number_input("Units per Pack/Case", min_value=0, value=24, step=1, key="add_beer_pack")
        with pb4:
            add_pour_oz = None
        add_uom = "each"

    elif add_category in ("spirits", "wine", "non-alcoholic", "cordial", "amaro"):
        pb1, pb2, pb3, pb4, pb5 = st.columns(5)
        with pb1:
            size_label = st.selectbox("Bottle Size", BOTTLE_SIZE_LABELS, index=5, key="add_bottle_size")
            if size_label == "Custom":
                add_bottle_ml = st.number_input("Custom (ml)", min_value=0, value=750, step=50, key="add_custom_ml")
            else:
                add_bottle_ml = BOTTLE_SIZE_ML[size_label]
        with pb2:
            add_purchase_unit = st.selectbox("Purchase Unit", ["bottle", "case"], key="add_spirits_pu")
        with pb3:
            if add_purchase_unit == "case":
                add_pack_size = st.number_input(
                    "Bottles per Case", min_value=0, value=12, step=1, key="add_spirits_pack"
                )
            else:
                add_pack_size = 1
                st.text_input("Bottles per Case", value="1", disabled=True)
        with pb4:
            default_pour = DEFAULT_POUR_OZ.get(add_category, 1.5) or 1.5
            add_pour_oz = st.number_input(
                "Standard Pour (oz)", min_value=0.0, value=default_pour, step=0.25, format="%.2f",
                help="Spirits: 1.5 oz | Wine: 5 oz | Cordials vary", key="add_pour_oz_spirits"
            )
        with pb5:
            add_uom = "bottle"
            st.text_input("Count Unit", value="bottle", disabled=True)

    else:
        # food / supplies / paper_goods / cleaning
        pb1, pb2, pb3, pb4 = st.columns(4)
        with pb1:
            add_uom = st.selectbox(
                "Count Unit", ["each", "lb", "oz", "gallon", "bag", "box", "case"],
                key="add_food_uom"
            )
        with pb2:
            add_purchase_unit = st.selectbox(
                "Purchase Unit", ["case", "bag", "box", "each", "lb"],
                key="add_food_pu"
            )
        with pb3:
            add_pack_size = st.number_input("Units per Purchase", min_value=0, value=1, step=1, key="add_food_pack")
        with pb4:
            add_bottle_ml = None
            add_pour_oz = None
            st.text_input("Serving size", value="N/A", disabled=True)

    # Tier
    add_tier = st.selectbox(
        "Inventory Tier",
        ["A", "B", "C"],
        help="A = top 20 by cost, B = tracked, C = low priority",
        key="add_tier"
    )

    # ── Section 3: Cost & Pricing ─────────────────────────────────────────────
    st.markdown("#### Cost & Pricing")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        add_unit_cost = st.number_input(
            "Unit Cost ($)", min_value=0.0, step=0.01, format="%.2f",
            help="Cost per bottle / each / lb", key="add_unit_cost"
        )
    with c2:
        # Auto-calculate case cost
        auto_case = round(add_unit_cost * add_pack_size, 2) if (add_unit_cost and add_pack_size and add_pack_size > 1) else None
        if auto_case and auto_case > 0:
            add_case_cost = st.number_input(
                "Case Cost ($)", min_value=0.0, step=0.01, format="%.2f",
                value=auto_case, key="add_case_cost",
                help="Auto-calculated from unit cost × pack size. Override if needed."
            )
        else:
            add_case_cost = st.number_input(
                "Case Cost ($)", min_value=0.0, step=0.01, format="%.2f",
                key="add_case_cost"
            )
    with c3:
        add_menu_price = st.number_input(
            "Menu Price ($)", min_value=0.0, step=0.25, format="%.2f",
            help="What you charge per pour/serving", key="add_menu_price"
        )
    with c4:
        add_vendor = st.selectbox(
            "Primary Vendor", ["(none)"] + vendor_names, key="add_vendor"
        )

    # Case/unit cost mismatch warning
    if add_unit_cost > 0 and add_case_cost > 0 and add_pack_size and add_pack_size > 1:
        expected = round(add_unit_cost * add_pack_size, 2)
        if abs(expected - add_case_cost) > 0.05:
            st.warning(
                f"Case cost (${add_case_cost:.2f}) doesn't match "
                f"unit cost × pack size (${expected:.2f}). Double-check before saving."
            )

    # ── Live Economics Preview ────────────────────────────────────────────────
    preview_container = st.container()
    with preview_container:
        _render_economics_preview(
            bottle_size_ml  = add_bottle_ml,
            standard_pour_oz= add_pour_oz if add_pour_oz and add_pour_oz > 0 else None,
            unit_cost       = add_unit_cost if add_unit_cost > 0 else None,
            menu_price      = add_menu_price if add_menu_price > 0 else None,
            container       = preview_container,
        )

    # ── Section 4: Inventory Levels ───────────────────────────────────────────
    st.markdown("#### Inventory Levels")
    l1, l2, l3, l4 = st.columns(4)
    with l1:
        add_current_qty = st.number_input(
            "Qty on Hand",
            min_value=0.0, step=0.5, format="%.1f",
            help="Current physical count. Supports partials (0.5 = half bottle).",
            key="add_current_qty"
        )
    with l2:
        add_par = st.number_input(
            "Par Level", min_value=0.0, step=0.5, format="%.1f",
            help="Ideal qty to have on hand", key="add_par"
        )
    with l3:
        add_reorder = st.number_input(
            "Reorder Point", min_value=0.0, step=0.5, format="%.1f",
            help="Alert when stock drops below this level", key="add_reorder"
        )
    with l4:
        add_reorder_qty = st.number_input(
            "Reorder Qty", min_value=0.0, step=0.5, format="%.1f",
            help="Standard order quantity", key="add_reorder_qty"
        )

    add_notes = st.text_area("Notes", height=60, placeholder="Any notes about this item...", key="add_notes")

    if st.button("💾 Add Item", type="primary", use_container_width=True, key="add_submit"):
        if not add_name.strip():
            st.error("Item name is required.")
        else:
            try:
                session = get_session()
                existing = session.query(InvItem).filter(
                    InvItem.name == add_name.strip(),
                    InvItem.status == "active",
                ).first()

                if existing:
                    st.error(f"'{add_name}' already exists in the catalog.")
                    session.close()
                else:
                    vendor_id = None
                    if add_vendor != "(none)":
                        vendor_id = get_vendor_id_by_name(add_vendor)

                    new_item = InvItem(
                        name          = add_name.strip(),
                        category      = add_category,
                        subcategory   = add_subcategory,
                        unit_of_measure = add_uom,
                        purchase_unit = add_purchase_unit if "add_purchase_unit" in dir() else None,
                        pack_size     = int(add_pack_size) if add_pack_size and add_pack_size > 0 else None,
                        bottle_size_ml= int(add_bottle_ml) if add_bottle_ml and add_bottle_ml > 0 else None,
                        standard_pour_oz = Decimal(str(add_pour_oz)) if add_pour_oz and add_pour_oz > 0 else None,
                        inventory_tier= add_tier,
                        unit_cost     = Decimal(str(add_unit_cost)) if add_unit_cost > 0 else None,
                        case_cost     = Decimal(str(add_case_cost)) if add_case_cost > 0 else None,
                        menu_price    = Decimal(str(add_menu_price)) if add_menu_price > 0 else None,
                        primary_vendor_id = vendor_id,
                        current_qty   = Decimal(str(add_current_qty)) if add_current_qty > 0 else None,
                        par_level     = Decimal(str(add_par)) if add_par > 0 else None,
                        reorder_point = Decimal(str(add_reorder)) if add_reorder > 0 else None,
                        reorder_qty   = Decimal(str(add_reorder_qty)) if add_reorder_qty > 0 else None,
                        notes         = add_notes.strip() or None,
                    )
                    session.add(new_item)
                    session.commit()
                    st.success(f"'{add_name}' added as Tier {add_tier} item!")
                    session.close()
                    st.rerun()

            except Exception as e:
                st.error(f"Error adding item: {e}")


# ════════════════════════════════════════════════════════════════════════════════
# TAB 3: EDIT ITEM
# ════════════════════════════════════════════════════════════════════════════════

with tab_edit:
    st.subheader("Edit Inventory Item")
    items_df_edit = get_inv_items()

    if items_df_edit.empty:
        st.info("No items yet. Add items using the **Add Item** tab.")
    else:
        # ── Item selector ─────────────────────────────────────────────────────
        item_name_list = items_df_edit["name"].tolist()
        selected_name = st.selectbox("Select item to edit", item_name_list, key="edit_selector")
        row = items_df_edit[items_df_edit["name"] == selected_name].iloc[0]
        item_id = int(row["id"])

        st.markdown("---")

        # ── Form: two-column layout for compact editing ───────────────────────
        with st.form("edit_inv_item_form"):
            st.markdown("#### Basic Info")
            e1, e2, e3 = st.columns(3)
            with e1:
                e_name = st.text_input("Item Name *", value=str(row["name"]), key="e_name")
            with e2:
                cat_idx = CATEGORY_OPTIONS.index(row["category"]) if row["category"] in CATEGORY_OPTIONS else 0
                e_category = st.selectbox("Category *", CATEGORY_OPTIONS, index=cat_idx, key="e_category")
            with e3:
                sub_opts_e = SUBCATEGORY_OPTIONS.get(e_category, ["other"])
                sub_idx = sub_opts_e.index(row["subcategory"]) if row["subcategory"] in sub_opts_e else 0
                e_subcategory = st.selectbox("Subcategory", sub_opts_e, index=sub_idx, key="e_subcategory")

            st.markdown("#### Packaging & Measurement")
            p1, p2, p3, p4, p5 = st.columns(5)
            with p1:
                e_bottle_ml = st.number_input(
                    "Bottle Size (ml)",
                    min_value=0, value=int(row["bottle_size_ml"]) if pd.notna(row["bottle_size_ml"]) else 0,
                    step=50, help="0 = not applicable (food, supplies)",
                    key="e_bottle_ml"
                )
            with p2:
                e_purchase_unit = st.selectbox(
                    "Purchase Unit",
                    ["bottle", "case", "keg", "bag", "box", "each", "lb"],
                    index=["bottle", "case", "keg", "bag", "box", "each", "lb"].index(row["purchase_unit"])
                    if pd.notna(row["purchase_unit"]) and row["purchase_unit"] in ["bottle", "case", "keg", "bag", "box", "each", "lb"]
                    else 0,
                    key="e_purchase_unit"
                )
            with p3:
                e_pack_size = st.number_input(
                    "Pack Size",
                    min_value=0,
                    value=int(row["pack_size"]) if pd.notna(row["pack_size"]) else 1,
                    step=1,
                    key="e_pack_size"
                )
            with p4:
                e_uom = st.selectbox(
                    "Count Unit",
                    ["bottle", "case", "each", "lb", "oz", "gallon", "keg", "bag", "box", "can", "liter"],
                    index=["bottle", "case", "each", "lb", "oz", "gallon", "keg", "bag", "box", "can", "liter"].index(row["unit_of_measure"])
                    if pd.notna(row["unit_of_measure"]) and row["unit_of_measure"] in ["bottle", "case", "each", "lb", "oz", "gallon", "keg", "bag", "box", "can", "liter"]
                    else 0,
                    key="e_uom"
                )
            with p5:
                tier_opts = ["A", "B", "C"]
                e_tier = st.selectbox(
                    "Tier",
                    tier_opts,
                    index=tier_opts.index(row["inventory_tier"]) if row["inventory_tier"] in tier_opts else 2,
                    key="e_tier"
                )

            st.markdown("#### Cost & Pricing")
            cp1, cp2, cp3, cp4, cp5 = st.columns(5)
            with cp1:
                e_unit_cost = st.number_input(
                    "Unit Cost ($)",
                    min_value=0.0, step=0.01, format="%.2f",
                    value=_safe_float(row["unit_cost"]),
                    key="e_unit_cost"
                )
            with cp2:
                e_case_cost = st.number_input(
                    "Case Cost ($)",
                    min_value=0.0, step=0.01, format="%.2f",
                    value=_safe_float(row["case_cost"]),
                    key="e_case_cost"
                )
            with cp3:
                e_pour_oz = st.number_input(
                    "Standard Pour (oz)",
                    min_value=0.0, step=0.25, format="%.2f",
                    value=_safe_float(row["standard_pour_oz"]),
                    help="1.5 spirits | 5.0 wine | 16.0 draft",
                    key="e_pour_oz"
                )
            with cp4:
                e_menu_price = st.number_input(
                    "Menu Price ($)",
                    min_value=0.0, step=0.25, format="%.2f",
                    value=_safe_float(row["menu_price"]),
                    key="e_menu_price"
                )
            with cp5:
                vendor_opts_e = ["(none)"] + get_vendor_names()
                current_vendor = str(row["vendor_name"]) if pd.notna(row["vendor_name"]) else "(none)"
                v_idx = vendor_opts_e.index(current_vendor) if current_vendor in vendor_opts_e else 0
                e_vendor = st.selectbox("Primary Vendor", vendor_opts_e, index=v_idx, key="e_vendor")

            st.markdown("#### Inventory Levels")
            il1, il2, il3, il4 = st.columns(4)
            with il1:
                e_current_qty = st.number_input(
                    "Qty on Hand",
                    min_value=0.0, step=0.5, format="%.1f",
                    value=_safe_float(row["current_qty"]),
                    help="Supports partial bottles (0.5, 1.5, etc.)",
                    key="e_current_qty"
                )
            with il2:
                e_par = st.number_input(
                    "Par Level",
                    min_value=0.0, step=0.5, format="%.1f",
                    value=_safe_float(row["par_level"]),
                    key="e_par"
                )
            with il3:
                e_reorder = st.number_input(
                    "Reorder Point",
                    min_value=0.0, step=0.5, format="%.1f",
                    value=_safe_float(row["reorder_point"]),
                    key="e_reorder"
                )
            with il4:
                e_reorder_qty = st.number_input(
                    "Reorder Qty",
                    min_value=0.0, step=0.5, format="%.1f",
                    value=_safe_float(row["reorder_qty"]),
                    key="e_reorder_qty"
                )

            e_notes = st.text_area(
                "Notes", height=60,
                value=str(row["notes"]) if pd.notna(row["notes"]) else "",
                key="e_notes"
            )

            # ── POS Item Link ─────────────────────────────────────────────────
            st.markdown("#### POS Item Link")
            st.caption(
                "Link this inventory item to a POS menu item. "
                "This connection will eventually drive recipe costing so inventory costs "
                "feed automatically into the Profitability page."
            )
            pos_df = get_pos_items_for_linking()
            pos_labels  = ["(none)"] + [
                f"{r['name']} ({r['category_name']}) — ${_safe_float(r['price']):.2f}"
                for _, r in pos_df.iterrows()
            ]
            pos_ids = [None] + pos_df["id"].tolist()

            current_pos_id = str(row["pos_item_id"]) if pd.notna(row["pos_item_id"]) else None
            current_pos_idx = 0
            if current_pos_id and current_pos_id in pos_ids:
                current_pos_idx = pos_ids.index(current_pos_id)

            e_pos_label = st.selectbox(
                "Linked POS Item",
                pos_labels,
                index=current_pos_idx,
                key="e_pos_item"
            )
            e_pos_id = pos_ids[pos_labels.index(e_pos_label)]

            col_save, col_deactivate = st.columns([3, 1])
            with col_save:
                save_submitted = st.form_submit_button(
                    "💾 Save Changes", type="primary", use_container_width=True
                )
            with col_deactivate:
                deactivate_submitted = st.form_submit_button(
                    "🗑 Deactivate", use_container_width=True
                )

        # ── Handle form submissions ───────────────────────────────────────────
        if save_submitted:
            if not e_name.strip():
                st.error("Item name is required.")
            else:
                try:
                    vendor_id_e = None
                    if e_vendor != "(none)":
                        vendor_id_e = get_vendor_id_by_name(e_vendor)

                    update_inv_item(item_id, {
                        "name":           e_name.strip(),
                        "category":       e_category,
                        "subcategory":    e_subcategory,
                        "unit_of_measure": e_uom,
                        "purchase_unit":  e_purchase_unit,
                        "pack_size":      int(e_pack_size) if e_pack_size > 0 else None,
                        "bottle_size_ml": int(e_bottle_ml) if e_bottle_ml > 0 else None,
                        "standard_pour_oz": Decimal(str(e_pour_oz)) if e_pour_oz > 0 else None,
                        "inventory_tier": e_tier,
                        "unit_cost":      Decimal(str(e_unit_cost)) if e_unit_cost > 0 else None,
                        "case_cost":      Decimal(str(e_case_cost)) if e_case_cost > 0 else None,
                        "menu_price":     Decimal(str(e_menu_price)) if e_menu_price > 0 else None,
                        "primary_vendor_id": vendor_id_e,
                        "current_qty":    Decimal(str(e_current_qty)) if e_current_qty >= 0 else None,
                        "par_level":      Decimal(str(e_par)) if e_par > 0 else None,
                        "reorder_point":  Decimal(str(e_reorder)) if e_reorder > 0 else None,
                        "reorder_qty":    Decimal(str(e_reorder_qty)) if e_reorder_qty > 0 else None,
                        "pos_item_id":    e_pos_id,
                        "notes":          e_notes.strip() or None,
                    })
                    st.success(f"'{e_name}' updated successfully.")
                    st.rerun()
                except Exception as ex:
                    st.error(f"Error saving: {ex}")

        if deactivate_submitted:
            try:
                update_inv_item(item_id, {"status": "inactive"})
                st.warning(f"'{selected_name}' has been deactivated. It will no longer appear in the catalog.")
                st.rerun()
            except Exception as ex:
                st.error(f"Error deactivating: {ex}")

        # ── Pour economics preview (outside form so it updates live) ──────────
        st.markdown("---")
        st.subheader("Pour Economics Preview")
        preview_edit_container = st.container()
        # Read last saved values from the DB row for preview (form values not accessible outside form)
        _render_economics_preview(
            bottle_size_ml   = int(row["bottle_size_ml"]) if pd.notna(row["bottle_size_ml"]) else None,
            standard_pour_oz = _safe_float(row["standard_pour_oz"]) or None,
            unit_cost        = _safe_float(row["unit_cost"]) or None,
            menu_price       = _safe_float(row["menu_price"]) or None,
            container        = preview_edit_container,
        )

        # ── Purchase History ──────────────────────────────────────────────────
        st.markdown("---")
        st.subheader("Purchase History")
        st.caption("Recent invoice lines matched to this item (most recent first, max 20).")
        hist_df = get_item_purchase_history(item_id)

        if hist_df.empty:
            st.info(
                "No invoice lines matched to this item yet. "
                "Match invoice lines on the **Invoices** page to see cost history here."
            )
        else:
            hist_display = hist_df.copy()
            hist_display["unit_price"] = hist_display["unit_price"].apply(
                lambda x: f"${float(x):,.2f}" if pd.notna(x) else "—"
            )
            hist_display["extended_price"] = hist_display["extended_price"].apply(
                lambda x: f"${float(x):,.2f}" if pd.notna(x) else "—"
            )
            hist_display.columns = [
                "Date", "Invoice #", "Vendor", "Qty", "Unit",
                "Unit Price", "Extended", "Description"
            ]
            st.dataframe(hist_display, hide_index=True, use_container_width=True)


st.markdown("---")
st.caption("Inventory Item Catalog | Bar Arbolada Analytics")
