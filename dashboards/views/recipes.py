"""
Recipe Management
==================
- Create recipes linking POS menu items to inventory ingredients
- View existing recipes with ingredient lists
- Each recipe maps: 1 POS item -> multiple inv_items with quantities
- Powers theoretical inventory depletion calculations
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
import pandas as pd
from datetime import datetime
from decimal import Decimal

from src.config import get_session
from src.models import Recipe, RecipeLine, InvItem, PosItem
from src.analytics.queries import (
    get_recipes,
    get_recipe_lines,
    get_pos_items_for_recipes,
    get_inv_items,
)

st.title("🍸 Recipe Management")

st.caption(
    "Link POS menu items to their inventory ingredients. When a cocktail is sold, "
    "the system automatically calculates theoretical inventory depletion."
)

# ── Tabs ──────────────────────────────────────────────────────────────────

tab_recipes, tab_add = st.tabs(["📋 Current Recipes", "➕ New Recipe"])


# ════════════════════════════════════════════════════════════════════════════
# TAB 1: CURRENT RECIPES
# ════════════════════════════════════════════════════════════════════════════

with tab_recipes:
    recipes_df = get_recipes()

    if recipes_df.empty:
        st.info(
            "No recipes defined yet. Use the **New Recipe** tab to start mapping "
            "cocktails and menu items to their inventory ingredients."
        )
        st.markdown("""
        **Getting started — map these first:**
        1. Your top 10 cocktails by sales volume
        2. Your top 5 food items by cost
        3. Any item with high variance in physical counts

        Each recipe tells the system: *"When 1 Old Fashioned is sold, deduct 2oz bourbon, "
        "0.25oz simple syrup, and 2 dashes bitters from inventory."*
        """)
    else:
        # Summary
        k1, k2, k3 = st.columns(3)
        with k1:
            st.metric("Total Recipes", len(recipes_df))
        with k2:
            active = len(recipes_df[recipes_df["status"] == "active"])
            st.metric("Active", active)
        with k3:
            total_ingredients = recipes_df["ingredient_count"].sum()
            st.metric("Total Ingredient Links", int(total_ingredients))

        st.markdown("---")

        # Recipe list
        display_recipes = recipes_df[[
            "recipe_name", "pos_item_name", "category_name",
            "ingredient_count", "yield_qty", "status",
        ]].copy()
        display_recipes.columns = [
            "Recipe", "POS Menu Item", "Category",
            "Ingredients", "Yield", "Status",
        ]
        st.dataframe(display_recipes, hide_index=True, use_container_width=True)

        # Recipe detail drill-down
        st.markdown("---")
        st.subheader("Recipe Detail")

        recipe_options = recipes_df["recipe_name"].tolist()
        recipe_ids = recipes_df["id"].tolist()

        selected_recipe = st.selectbox("Select a recipe:", range(len(recipe_options)),
                                        format_func=lambda i: recipe_options[i])

        if selected_recipe is not None:
            recipe_id = int(recipe_ids[selected_recipe])
            lines_df = get_recipe_lines(recipe_id)

            if not lines_df.empty:
                recipe_info = recipes_df.iloc[selected_recipe]
                st.markdown(f"**{recipe_info['recipe_name']}** — "
                            f"POS Item: {recipe_info['pos_item_name'] or 'Not linked'}")

                display_lines = lines_df[[
                    "ingredient_name", "quantity", "unit_of_measure",
                    "waste_factor", "ingredient_category", "notes",
                ]].copy()
                display_lines["quantity"] = display_lines["quantity"].astype(float)
                display_lines["waste_factor"] = display_lines["waste_factor"].astype(float)
                display_lines.columns = [
                    "Ingredient", "Qty", "Unit", "Waste Factor",
                    "Category", "Notes",
                ]
                st.dataframe(display_lines, hide_index=True, use_container_width=True)
            else:
                st.info("This recipe has no ingredients defined yet.")


# ════════════════════════════════════════════════════════════════════════════
# TAB 2: NEW RECIPE
# ════════════════════════════════════════════════════════════════════════════

with tab_add:
    st.subheader("Create New Recipe")

    # Check prerequisites
    inv_items_df = get_inv_items()
    pos_items_df = get_pos_items_for_recipes()

    if inv_items_df.empty:
        st.warning(
            "You need inventory items before creating recipes. "
            "Go to **Inventory Items** to add your stock items first."
        )
    elif pos_items_df.empty:
        st.warning(
            "No POS items found. Import your items from Lightspeed first."
        )
    else:
        # ── Recipe Header ────────────────────────────────────────────────

        st.markdown("#### Recipe Header")

        r1, r2 = st.columns(2)
        with r1:
            recipe_name = st.text_input("Recipe Name *",
                                         placeholder="e.g., Old Fashioned")
        with r2:
            # Build POS item selector with category grouping
            pos_display = pos_items_df.apply(
                lambda r: f"[{r['category_name']}] {r['name']}" if r['category_name']
                else r['name'],
                axis=1,
            ).tolist()
            pos_ids = pos_items_df["id"].tolist()

            selected_pos_idx = st.selectbox(
                "Link to POS Menu Item *",
                range(len(pos_display)),
                format_func=lambda i: pos_display[i],
            )

        r3, r4 = st.columns(2)
        with r3:
            yield_qty = st.number_input("Yield (servings)", min_value=0.5,
                                         value=1.0, step=0.5, format="%.1f",
                                         help="How many servings this recipe makes")
        with r4:
            recipe_notes = st.text_input("Notes", placeholder="Any special prep notes...")

        st.markdown("---")

        # ── Ingredients ──────────────────────────────────────────────────

        st.markdown("#### Ingredients")
        st.caption(
            "Add each ingredient with the quantity used per serving. "
            "Waste factor accounts for spillage (1.0 = no waste, 1.1 = 10% extra)."
        )

        # Build ingredient selector
        inv_display = inv_items_df.apply(
            lambda r: f"[{r['category']}] {r['name']}" if r['category'] else r['name'],
            axis=1,
        ).tolist()
        inv_ids = inv_items_df["id"].tolist()

        ingredient_uom = ["oz", "ml", "dash", "each", "slice", "sprig",
                          "drop", "barspoon", "cup", "tbsp", "tsp",
                          "lb", "g", "piece"]

        # Dynamic ingredient list
        if "recipe_ingredients" not in st.session_state:
            st.session_state.recipe_ingredients = [
                {"inv_idx": 0, "qty": 1.0, "uom": "oz", "waste": 1.0, "notes": ""}
            ]

        ingredients_to_remove = []

        for i, ing in enumerate(st.session_state.recipe_ingredients):
            cols = st.columns([3, 1.2, 1.2, 1, 2, 0.6])

            with cols[0]:
                inv_idx = st.selectbox(
                    "Ingredient" if i == 0 else f"Ingredient {i+1}",
                    range(len(inv_display)),
                    index=min(ing["inv_idx"], len(inv_display) - 1),
                    format_func=lambda x: inv_display[x],
                    key=f"ring_item_{i}",
                    label_visibility="visible" if i == 0 else "collapsed",
                )
            with cols[1]:
                qty = st.number_input(
                    "Qty" if i == 0 else f"Qty {i+1}",
                    value=float(ing["qty"]),
                    min_value=0.0, step=0.25, format="%.2f",
                    key=f"ring_qty_{i}",
                    label_visibility="visible" if i == 0 else "collapsed",
                )
            with cols[2]:
                uom = st.selectbox(
                    "Unit" if i == 0 else f"Unit {i+1}",
                    ingredient_uom,
                    index=ingredient_uom.index(ing["uom"]) if ing["uom"] in ingredient_uom else 0,
                    key=f"ring_uom_{i}",
                    label_visibility="visible" if i == 0 else "collapsed",
                )
            with cols[3]:
                waste = st.number_input(
                    "Waste" if i == 0 else f"Waste {i+1}",
                    value=float(ing["waste"]),
                    min_value=1.0, max_value=2.0, step=0.05, format="%.2f",
                    key=f"ring_waste_{i}",
                    label_visibility="visible" if i == 0 else "collapsed",
                )
            with cols[4]:
                notes = st.text_input(
                    "Notes" if i == 0 else f"Notes {i+1}",
                    value=ing["notes"],
                    key=f"ring_notes_{i}",
                    label_visibility="visible" if i == 0 else "collapsed",
                )
            with cols[5]:
                if i > 0:
                    if st.button("✕", key=f"remove_ring_{i}"):
                        ingredients_to_remove.append(i)
                else:
                    st.markdown("<div style='height:38px'></div>", unsafe_allow_html=True)

            # Update session state
            st.session_state.recipe_ingredients[i] = {
                "inv_idx": inv_idx, "qty": qty,
                "uom": uom, "waste": waste, "notes": notes,
            }

        # Remove ingredients marked for deletion
        for idx in sorted(ingredients_to_remove, reverse=True):
            st.session_state.recipe_ingredients.pop(idx)
            st.rerun()

        b1, b2, _ = st.columns([1, 1, 4])
        with b1:
            if st.button("➕ Add Ingredient"):
                st.session_state.recipe_ingredients.append(
                    {"inv_idx": 0, "qty": 1.0, "uom": "oz", "waste": 1.0, "notes": ""}
                )
                st.rerun()

        # ── Save ─────────────────────────────────────────────────────────

        st.markdown("---")

        # Preview
        valid_ingredients = [
            ing for ing in st.session_state.recipe_ingredients
            if ing["qty"] > 0
        ]
        st.markdown(f"**{len(valid_ingredients)} ingredient(s)** in this recipe")

        if st.button("💾 Save Recipe", type="primary", use_container_width=True):
            errors = []
            if not recipe_name.strip():
                errors.append("Recipe name is required.")
            if not valid_ingredients:
                errors.append("At least one ingredient is required.")

            if errors:
                for e in errors:
                    st.error(e)
            else:
                try:
                    session = get_session()

                    # Check for duplicate recipe name + POS item
                    pos_item_id = pos_ids[selected_pos_idx]
                    existing = session.query(Recipe).filter(
                        Recipe.recipe_name == recipe_name.strip(),
                        Recipe.pos_item_id == pos_item_id,
                        Recipe.status == "active",
                    ).first()

                    if existing:
                        st.error(f"An active recipe '{recipe_name}' already exists for this item.")
                        session.close()
                    else:
                        recipe = Recipe(
                            pos_item_id=pos_item_id,
                            recipe_name=recipe_name.strip(),
                            yield_qty=Decimal(str(yield_qty)),
                            status="active",
                            notes=recipe_notes.strip() or None,
                        )
                        session.add(recipe)
                        session.flush()

                        for ing in valid_ingredients:
                            inv_item_id = int(inv_ids[ing["inv_idx"]])
                            recipe_line = RecipeLine(
                                recipe_id=recipe.id,
                                inv_item_id=inv_item_id,
                                quantity=Decimal(str(ing["qty"])),
                                unit_of_measure=ing["uom"],
                                waste_factor=Decimal(str(ing["waste"])),
                                notes=ing["notes"].strip() or None,
                            )
                            session.add(recipe_line)

                        session.commit()
                        st.success(
                            f"Recipe '{recipe_name}' saved with "
                            f"{len(valid_ingredients)} ingredients!"
                        )
                        st.session_state.recipe_ingredients = [
                            {"inv_idx": 0, "qty": 1.0, "uom": "oz", "waste": 1.0, "notes": ""}
                        ]
                        session.close()
                        st.rerun()

                except Exception as e:
                    st.error(f"Error saving recipe: {e}")


st.markdown("---")
st.caption("Recipe Management | Bar Arbolada Analytics")
