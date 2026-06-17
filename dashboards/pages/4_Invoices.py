"""
Invoice Entry & Management
============================
- Upload and auto-parse invoice PDFs
- Add new vendors
- Enter invoices with line items
- View and manage existing invoices
- Invoice spending summary by vendor
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
import pandas as pd
from datetime import date, datetime
from decimal import Decimal
import tempfile, shutil

from src.config import get_session
from src.models import InvVendor, InvInvoice, InvInvoiceLine, InvItem
from src.analytics.queries import (
    get_vendors,
    get_vendor_names,
    get_vendor_id_by_name,
    get_inv_item_names,
    get_invoices,
    get_invoice_lines,
    get_invoice_totals,
)

st.set_page_config(page_title="Invoices | Bar Arbolada", page_icon="📄", layout="wide")
st.title("📄 Invoice Entry & Management")

# ── Tabs ─────────────────────────────────────────────────────────────────────

tab_upload, tab_entry, tab_history, tab_vendors = st.tabs([
    "📤 Upload PDF",
    "📝 New Invoice",
    "📋 Invoice History",
    "🏢 Manage Vendors",
])


# ════════════════════════════════════════════════════════════════════════════
# TAB 0: UPLOAD PDF
# ════════════════════════════════════════════════════════════════════════════

with tab_upload:
    st.subheader("Upload Invoice PDF")
    st.caption(
        "Upload a vendor invoice PDF and the system will auto-extract line items. "
        "Works best with text-based PDFs (digitally generated). "
        "Scanned/photographed PDFs require OCR — use Adobe Scan or Microsoft Lens first."
    )

    uploaded_file = st.file_uploader(
        "Drop an invoice PDF here",
        type=["pdf"],
        key="pdf_upload",
    )

    if uploaded_file is not None:
        try:
            from src.importers.invoices import parse_invoice_pdf

            # Save to temp file
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(uploaded_file.read())
                tmp_path = tmp.name

            # Parse
            with st.spinner("Parsing invoice..."):
                result = parse_invoice_pdf(tmp_path)

            # Show errors
            if result.errors:
                for err in result.errors:
                    st.error(err)
                st.stop()

            # Show warnings
            for warn in result.warnings:
                st.warning(warn)

            # Show confidence
            confidence_colors = {"high": "🟢", "medium": "🟡", "low": "🔴"}
            st.markdown(
                f"**Parse Confidence:** {confidence_colors.get(result.confidence, '⚪')} "
                f"{result.confidence.upper()} | "
                f"**Method:** {result.parse_method} | "
                f"**Vendor:** {result.vendor_name or 'Unknown'}"
            )

            st.markdown("---")

            # ── Editable Header ──────────────────────────────────────────

            st.markdown("#### Review & Edit Invoice Header")

            vendor_names = get_vendor_names()
            h1, h2, h3, h4 = st.columns(4)

            with h1:
                # Try to match vendor
                default_vendor_idx = 0
                if result.vendor_name and vendor_names:
                    for i, vn in enumerate(vendor_names):
                        if result.vendor_name.lower() in vn.lower() or vn.lower() in result.vendor_name.lower():
                            default_vendor_idx = i
                            break

                if vendor_names:
                    pdf_vendor = st.selectbox("Vendor", vendor_names,
                                              index=default_vendor_idx,
                                              key="pdf_vendor")
                else:
                    pdf_vendor = st.text_input("Vendor", value=result.vendor_name,
                                               key="pdf_vendor_text")
                    st.warning("Add vendors in the Manage Vendors tab first.")

            with h2:
                pdf_inv_num = st.text_input("Invoice #",
                                             value=result.invoice_number,
                                             key="pdf_inv_num")
            with h3:
                _pdf_inv_d = result.invoice_date or date.today()
                if _pdf_inv_d < date(2018, 1, 1) or _pdf_inv_d > date(2030, 12, 31):
                    _pdf_inv_d = date.today()
                pdf_inv_date = st.date_input(
                    "Invoice Date",
                    value=_pdf_inv_d,
                    min_value=date(2018, 1, 1),
                    max_value=date(2030, 12, 31),
                    key="pdf_inv_date",
                )
            with h4:
                _pdf_recv_d = result.delivery_date or date.today()
                if _pdf_recv_d < date(2018, 1, 1) or _pdf_recv_d > date(2030, 12, 31):
                    _pdf_recv_d = date.today()
                pdf_recv_date = st.date_input(
                    "Received Date",
                    value=_pdf_recv_d,
                    min_value=date(2018, 1, 1),
                    max_value=date(2030, 12, 31),
                    key="pdf_recv_date",
                )

            st.markdown("---")

            # ── Editable Line Items ──────────────────────────────────────

            st.markdown("#### Review & Edit Line Items")
            st.caption("Verify each line. Edit descriptions, quantities, and prices as needed.")

            if result.lines:
                # Build editable dataframe
                lines_data = []
                for line in result.lines:
                    lines_data.append({
                        "Description": line.description,
                        "Qty": line.quantity,
                        "Unit": line.unit_of_measure,
                        "Unit Price": line.unit_price,
                        "Ext Price": line.extended_price,
                        "Item Code": line.item_code,
                        "Size": line.bottle_size,
                    })

                lines_edit_df = pd.DataFrame(lines_data)

                edited_df = st.data_editor(
                    lines_edit_df,
                    num_rows="dynamic",
                    use_container_width=True,
                    key="pdf_lines_editor",
                    column_config={
                        "Unit Price": st.column_config.NumberColumn(format="$%.2f"),
                        "Ext Price": st.column_config.NumberColumn(format="$%.2f"),
                        "Qty": st.column_config.NumberColumn(format="%.1f"),
                    },
                )

                # Totals
                computed_total = edited_df["Ext Price"].sum()
                t1, t2 = st.columns(2)
                with t1:
                    st.metric("Computed Total", f"${computed_total:,.2f}")
                with t2:
                    if result.total_amount > 0:
                        st.metric("Invoice Total (from PDF)",
                                  f"${result.total_amount:,.2f}")

                st.markdown("---")

                # ── Save Button ──────────────────────────────────────────

                pdf_notes = st.text_area("Notes", key="pdf_notes",
                                          placeholder="Any notes about this invoice...",
                                          height=60)

                if st.button("💾 Save Parsed Invoice", type="primary",
                             use_container_width=True, key="save_pdf_invoice"):
                    errors = []
                    if not pdf_inv_num.strip():
                        errors.append("Invoice # is required.")
                    if edited_df.empty or len(edited_df) == 0:
                        errors.append("At least one line item is required.")
                    if not vendor_names:
                        errors.append("Add a vendor first.")

                    if errors:
                        for e in errors:
                            st.error(e)
                    else:
                        try:
                            session = get_session()
                            vendor_id = get_vendor_id_by_name(pdf_vendor)

                            # Check for duplicate
                            existing = session.query(InvInvoice).filter_by(
                                vendor_id=vendor_id,
                                invoice_number=pdf_inv_num.strip(),
                            ).first()

                            if existing:
                                st.error(f"Invoice #{pdf_inv_num} already exists for {pdf_vendor}.")
                                session.close()
                            else:
                                # Save to raw-invoices folder
                                raw_dir = Path(__file__).parent.parent.parent / "raw-invoices-unedited"
                                raw_dir.mkdir(exist_ok=True)
                                dest_path = raw_dir / uploaded_file.name
                                if not dest_path.exists():
                                    shutil.copy2(tmp_path, dest_path)

                                invoice = InvInvoice(
                                    vendor_id=vendor_id,
                                    invoice_number=pdf_inv_num.strip(),
                                    invoice_date=pdf_inv_date,
                                    received_date=pdf_recv_date,
                                    total_amount=Decimal(str(round(computed_total, 2))),
                                    status="pending",
                                    source_file=str(dest_path),
                                    notes=pdf_notes.strip() or None,
                                )
                                session.add(invoice)
                                session.flush()

                                for idx, row in edited_df.iterrows():
                                    if not str(row.get("Description", "")).strip():
                                        continue
                                    inv_line = InvInvoiceLine(
                                        invoice_id=invoice.id,
                                        description=str(row["Description"]).strip(),
                                        quantity=Decimal(str(row.get("Qty", 1))),
                                        unit_of_measure=str(row.get("Unit", "bottle")),
                                        unit_price=Decimal(str(row.get("Unit Price", 0))),
                                        extended_price=Decimal(str(row.get("Ext Price", 0))),
                                        line_number=idx + 1,
                                        matched=False,
                                        line_type="item",
                                    )
                                    session.add(inv_line)

                                session.commit()
                                st.success(
                                    f"Invoice #{pdf_inv_num} saved for {pdf_vendor} "
                                    f"({len(edited_df)} items, ${computed_total:,.2f})"
                                )
                                session.close()

                        except Exception as e:
                            st.error(f"Error saving invoice: {e}")

            else:
                st.info(
                    "No line items could be auto-extracted. "
                    "This PDF may be image-based. Try:\n"
                    "1. Scan with Adobe Scan or Microsoft Lens (creates OCR'd PDF)\n"
                    "2. Use the **New Invoice** tab for manual entry"
                )

        except ImportError:
            st.error(
                "pdfplumber is required for PDF parsing. "
                "Run: `pip install pdfplumber`"
            )
        except Exception as e:
            st.error(f"Error processing PDF: {e}")


# ════════════════════════════════════════════════════════════════════════════
# TAB 1: NEW INVOICE ENTRY
# ════════════════════════════════════════════════════════════════════════════

with tab_entry:
    st.subheader("Enter a New Invoice")

    vendor_names = get_vendor_names()

    if not vendor_names:
        st.warning("No vendors in the system yet. Add a vendor in the **Manage Vendors** tab first.")
    else:
        # ── Invoice Header ───────────────────────────────────────────────

        st.markdown("#### Invoice Header")
        h1, h2, h3, h4 = st.columns(4)

        with h1:
            vendor_name = st.selectbox("Vendor", vendor_names, key="inv_vendor")
        with h2:
            invoice_number = st.text_input("Invoice #", key="inv_number",
                                           placeholder="e.g., INV-2026-0123")
        with h3:
            invoice_date = st.date_input("Invoice Date", value=date.today(),
                                         min_value=date(2018, 1, 1),
                                         max_value=date(2030, 12, 31),
                                         key="inv_date")
        with h4:
            received_date = st.date_input("Received Date", value=date.today(),
                                          min_value=date(2018, 1, 1),
                                          max_value=date(2030, 12, 31),
                                          key="inv_received")

        invoice_notes = st.text_area("Notes (optional)", key="inv_notes", height=60,
                                     placeholder="Any notes about this invoice...")

        st.markdown("---")

        # ── Line Items ───────────────────────────────────────────────────

        st.markdown("#### Line Items")
        st.caption("Add each item from the invoice. Extended price auto-calculates from Qty x Unit Price.")

        # Use session state for dynamic line items
        if "invoice_lines" not in st.session_state:
            st.session_state.invoice_lines = [{"description": "", "qty": 1.0,
                                                "uom": "bottle", "unit_price": 0.0}]

        uom_options = ["bottle", "case", "each", "lb", "oz", "gallon", "keg", "bag", "box"]

        lines_to_remove = []

        for i, line in enumerate(st.session_state.invoice_lines):
            cols = st.columns([4, 1.5, 1.5, 1.5, 1.5, 0.8])

            with cols[0]:
                desc = st.text_input(
                    "Description", value=line["description"],
                    key=f"line_desc_{i}",
                    placeholder="e.g., Bourbon 750ml",
                    label_visibility="collapsed" if i > 0 else "visible",
                )
            with cols[1]:
                qty = st.number_input(
                    "Qty", value=float(line["qty"]), min_value=0.0,
                    step=1.0, format="%.2f",
                    key=f"line_qty_{i}",
                    label_visibility="collapsed" if i > 0 else "visible",
                )
            with cols[2]:
                uom = st.selectbox(
                    "Unit", uom_options,
                    index=uom_options.index(line["uom"]) if line["uom"] in uom_options else 0,
                    key=f"line_uom_{i}",
                    label_visibility="collapsed" if i > 0 else "visible",
                )
            with cols[3]:
                unit_price = st.number_input(
                    "Unit Price", value=float(line["unit_price"]),
                    min_value=0.0, step=0.01, format="%.2f",
                    key=f"line_price_{i}",
                    label_visibility="collapsed" if i > 0 else "visible",
                )
            with cols[4]:
                ext_price = qty * unit_price
                st.text_input(
                    "Ext Price", value=f"${ext_price:,.2f}",
                    key=f"line_ext_{i}", disabled=True,
                    label_visibility="collapsed" if i > 0 else "visible",
                )
            with cols[5]:
                if i > 0:
                    if st.button("✕", key=f"remove_{i}", help="Remove this line"):
                        lines_to_remove.append(i)
                else:
                    st.markdown("<div style='height:38px'></div>", unsafe_allow_html=True)

            # Update session state
            st.session_state.invoice_lines[i] = {
                "description": desc, "qty": qty,
                "uom": uom, "unit_price": unit_price,
            }

        # Remove lines marked for deletion (in reverse to preserve indices)
        for idx in sorted(lines_to_remove, reverse=True):
            st.session_state.invoice_lines.pop(idx)
            st.rerun()

        # Add line button
        if st.button("➕ Add Line Item"):
            st.session_state.invoice_lines.append(
                {"description": "", "qty": 1.0, "uom": "bottle", "unit_price": 0.0}
            )
            st.rerun()

        # ── Credits ─────────────────────────────────────────────────────

        st.markdown("---")
        st.markdown("#### Credits")
        st.caption("Returned kegs, packaging returns, etc. Enter amounts as positive numbers — they'll be subtracted from the total.")

        if "invoice_credits" not in st.session_state:
            st.session_state.invoice_credits = []

        credits_to_remove = []

        for i, credit in enumerate(st.session_state.invoice_credits):
            cr_cols = st.columns([5, 2, 0.8])
            with cr_cols[0]:
                cr_desc = st.text_input(
                    "Description", value=credit["description"],
                    key=f"credit_desc_{i}",
                    placeholder="e.g., Keg return deposit",
                    label_visibility="collapsed" if i > 0 else "visible",
                )
            with cr_cols[1]:
                cr_amount = st.number_input(
                    "Amount", value=float(credit["amount"]),
                    min_value=0.0, step=0.01, format="%.2f",
                    key=f"credit_amt_{i}",
                    label_visibility="collapsed" if i > 0 else "visible",
                )
            with cr_cols[2]:
                if st.button("✕", key=f"remove_credit_{i}", help="Remove this credit"):
                    credits_to_remove.append(i)

            st.session_state.invoice_credits[i] = {
                "description": cr_desc, "amount": cr_amount,
            }

        for idx in sorted(credits_to_remove, reverse=True):
            st.session_state.invoice_credits.pop(idx)
            st.rerun()

        if st.button("➕ Add Credit"):
            st.session_state.invoice_credits.append(
                {"description": "", "amount": 0.0}
            )
            st.rerun()

        # ── Fees ────────────────────────────────────────────────────────

        st.markdown("---")
        st.markdown("#### Fees")
        st.caption("Delivery fees, surcharges, etc. These add to the total but aren't inventory items.")

        if "invoice_fees" not in st.session_state:
            st.session_state.invoice_fees = []

        fees_to_remove = []

        for i, fee in enumerate(st.session_state.invoice_fees):
            fe_cols = st.columns([5, 2, 0.8])
            with fe_cols[0]:
                fe_desc = st.text_input(
                    "Description", value=fee["description"],
                    key=f"fee_desc_{i}",
                    placeholder="e.g., Delivery fee",
                    label_visibility="collapsed" if i > 0 else "visible",
                )
            with fe_cols[1]:
                fe_amount = st.number_input(
                    "Amount", value=float(fee["amount"]),
                    min_value=0.0, step=0.01, format="%.2f",
                    key=f"fee_amt_{i}",
                    label_visibility="collapsed" if i > 0 else "visible",
                )
            with fe_cols[2]:
                if st.button("✕", key=f"remove_fee_{i}", help="Remove this fee"):
                    fees_to_remove.append(i)

            st.session_state.invoice_fees[i] = {
                "description": fe_desc, "amount": fe_amount,
            }

        for idx in sorted(fees_to_remove, reverse=True):
            st.session_state.invoice_fees.pop(idx)
            st.rerun()

        if st.button("➕ Add Fee"):
            st.session_state.invoice_fees.append(
                {"description": "", "amount": 0.0}
            )
            st.rerun()

        # ── Totals ───────────────────────────────────────────────────────

        st.markdown("---")
        items_total = sum(l["qty"] * l["unit_price"] for l in st.session_state.invoice_lines)
        credits_total = sum(c["amount"] for c in st.session_state.invoice_credits)
        fees_total = sum(f["amount"] for f in st.session_state.invoice_fees)
        total = items_total - credits_total + fees_total
        line_count = len([l for l in st.session_state.invoice_lines if l["description"].strip()])

        t1, t2, t3, t4, t5 = st.columns(5)
        with t1:
            st.metric("Items", f"${items_total:,.2f}")
        with t2:
            st.metric("Credits", f"-${credits_total:,.2f}")
        with t3:
            st.metric("Fees", f"+${fees_total:,.2f}")
        with t4:
            st.metric("Invoice Total", f"${total:,.2f}")
        with t5:
            st.metric("Vendor", vendor_name)

        # ── Save Button ──────────────────────────────────────────────────

        st.markdown("---")
        if st.button("💾 Save Invoice", type="primary", use_container_width=True):
            # Validation
            errors = []
            if not invoice_number.strip():
                errors.append("Invoice # is required.")
            if line_count == 0:
                errors.append("At least one line item with a description is required.")

            if errors:
                for e in errors:
                    st.error(e)
            else:
                try:
                    session = get_session()
                    vendor_id = get_vendor_id_by_name(vendor_name)

                    # Check for duplicate invoice
                    existing = session.query(InvInvoice).filter_by(
                        vendor_id=vendor_id,
                        invoice_number=invoice_number.strip(),
                    ).first()

                    if existing:
                        st.error(f"Invoice #{invoice_number} already exists for {vendor_name}.")
                        session.close()
                    else:
                        invoice = InvInvoice(
                            vendor_id=vendor_id,
                            invoice_number=invoice_number.strip(),
                            invoice_date=invoice_date,
                            received_date=received_date,
                            total_amount=Decimal(str(round(total, 2))),
                            status="pending",
                            notes=invoice_notes.strip() if invoice_notes else None,
                        )
                        session.add(invoice)
                        session.flush()

                        line_num = 1

                        # Save item lines
                        for line in st.session_state.invoice_lines:
                            if not line["description"].strip():
                                continue
                            ext = round(line["qty"] * line["unit_price"], 2)
                            inv_line = InvInvoiceLine(
                                invoice_id=invoice.id,
                                description=line["description"].strip(),
                                quantity=Decimal(str(line["qty"])),
                                unit_of_measure=line["uom"],
                                unit_price=Decimal(str(line["unit_price"])),
                                extended_price=Decimal(str(ext)),
                                line_number=line_num,
                                matched=False,
                                line_type="item",
                            )
                            session.add(inv_line)
                            line_num += 1

                        # Save credit lines
                        for credit in st.session_state.invoice_credits:
                            if not credit["description"].strip():
                                continue
                            inv_line = InvInvoiceLine(
                                invoice_id=invoice.id,
                                description=credit["description"].strip(),
                                extended_price=Decimal(str(-abs(round(credit["amount"], 2)))),
                                line_number=line_num,
                                matched=False,
                                line_type="credit",
                            )
                            session.add(inv_line)
                            line_num += 1

                        # Save fee lines
                        for fee in st.session_state.invoice_fees:
                            if not fee["description"].strip():
                                continue
                            inv_line = InvInvoiceLine(
                                invoice_id=invoice.id,
                                description=fee["description"].strip(),
                                extended_price=Decimal(str(abs(round(fee["amount"], 2)))),
                                line_number=line_num,
                                matched=False,
                                line_type="fee",
                            )
                            session.add(inv_line)
                            line_num += 1

                        session.commit()
                        st.success(
                            f"Invoice #{invoice_number} saved for {vendor_name} "
                            f"({line_count} items, ${total:,.2f})"
                        )
                        # Reset form
                        st.session_state.invoice_lines = [
                            {"description": "", "qty": 1.0, "uom": "bottle", "unit_price": 0.0}
                        ]
                        st.session_state.invoice_credits = []
                        st.session_state.invoice_fees = []
                        session.close()

                except Exception as e:
                    st.error(f"Error saving invoice: {e}")


# ════════════════════════════════════════════════════════════════════════════
# TAB 2: INVOICE HISTORY
# ════════════════════════════════════════════════════════════════════════════

with tab_history:
    st.subheader("Invoice History")

    # ── Session-state helpers for invoice edit / delete ────────────────
    if "inv_edit_id" not in st.session_state:
        st.session_state.inv_edit_id = None
    if "inv_delete_id" not in st.session_state:
        st.session_state.inv_delete_id = None
    if "inv_edit_lines" not in st.session_state:
        st.session_state.inv_edit_lines = []
    if "inv_edit_lines_to_delete" not in st.session_state:
        st.session_state.inv_edit_lines_to_delete = []

    invoices_df = get_invoices()

    if not invoices_df.empty:
        # Summary by vendor
        totals_df = get_invoice_totals()
        if not totals_df.empty:
            st.markdown("#### Spend by Vendor")
            totals_df["total_spend"] = totals_df["total_spend"].astype(float)
            display_totals = totals_df.copy()
            display_totals["total_spend"] = display_totals["total_spend"].apply(lambda x: f"${x:,.2f}")
            display_totals.columns = ["Vendor", "Invoices", "Total Spend", "First Invoice", "Last Invoice"]
            st.dataframe(display_totals, hide_index=True, use_container_width=True)
            st.markdown("---")

        # All invoices table
        st.markdown("#### All Invoices")
        invoices_df["total_amount"] = invoices_df["total_amount"].astype(float)

        display_inv = invoices_df[["invoice_date", "vendor_name", "invoice_number",
                                    "total_amount", "line_count", "status"]].copy()
        display_inv["total_amount"] = display_inv["total_amount"].apply(lambda x: f"${x:,.2f}")
        display_inv.columns = ["Date", "Vendor", "Invoice #", "Total", "Lines", "Status"]
        st.dataframe(display_inv, hide_index=True, use_container_width=True)

        # ── Invoice detail / edit drill-down ──────────────────────────
        st.markdown("---")
        st.markdown("#### Invoice Detail")
        inv_options = invoices_df.apply(
            lambda r: f"{r['invoice_date']} | {r['vendor_name']} | #{r['invoice_number']}",
            axis=1,
        ).tolist()
        inv_ids = invoices_df["id"].tolist()

        selected_idx = st.selectbox("Select an invoice to view details:",
                                     range(len(inv_options)),
                                     format_func=lambda i: inv_options[i])

        if selected_idx is not None:
            sel_inv_id = int(inv_ids[selected_idx])
            sel_row = invoices_df.iloc[selected_idx]
            is_editing_inv = st.session_state.inv_edit_id == sel_inv_id
            is_deleting_inv = st.session_state.inv_delete_id == sel_inv_id

            # ── Action buttons ────────────────────────────────────────
            act1, act2, act3 = st.columns([1, 1, 4])
            with act1:
                if st.button("✏️ Edit Invoice",
                             key="btn_edit_inv",
                             use_container_width=True):
                    if is_editing_inv:
                        st.session_state.inv_edit_id = None
                        st.session_state.inv_edit_lines = []
                        st.session_state.inv_edit_lines_to_delete = []
                    else:
                        st.session_state.inv_edit_id = sel_inv_id
                        st.session_state.inv_delete_id = None
                        # Load current lines into session state
                        cur_lines = get_invoice_lines(sel_inv_id)
                        if not cur_lines.empty:
                            st.session_state.inv_edit_lines = [
                                {
                                    "line_id": int(r["id"]),
                                    "line_type": r.get("line_type") or "item",
                                    "description": r["description"] or "",
                                    "qty": float(r["quantity"] or 0),
                                    "uom": r["unit_of_measure"] or "bottle",
                                    "unit_price": float(r["unit_price"] or 0),
                                    "amount": abs(float(r["extended_price"] or 0)),
                                }
                                for _, r in cur_lines.iterrows()
                            ]
                        else:
                            st.session_state.inv_edit_lines = []
                        st.session_state.inv_edit_lines_to_delete = []
                    st.rerun()
            with act2:
                if st.button("🗑️ Delete Invoice",
                             key="btn_del_inv",
                             use_container_width=True):
                    if is_deleting_inv:
                        st.session_state.inv_delete_id = None
                    else:
                        st.session_state.inv_delete_id = sel_inv_id
                        st.session_state.inv_edit_id = None
                        st.session_state.inv_edit_lines = []
                    st.rerun()

            # ── Delete confirmation ───────────────────────────────────
            if is_deleting_inv:
                st.warning(
                    f"Are you sure you want to delete invoice "
                    f"**#{sel_row['invoice_number']}** from "
                    f"**{sel_row['vendor_name']}**? "
                    f"This will also delete all {int(sel_row['line_count'])} "
                    f"line items and cannot be undone."
                )
                dc1, dc2, dc3 = st.columns([1, 1, 3])
                with dc1:
                    if st.button("Yes, delete", key="confirm_del_inv",
                                 type="primary", use_container_width=True):
                        try:
                            session = get_session()
                            inv_obj = session.query(InvInvoice).get(
                                sel_inv_id)
                            if inv_obj:
                                # Delete lines first
                                session.query(InvInvoiceLine).filter_by(
                                    invoice_id=sel_inv_id
                                ).delete()
                                session.delete(inv_obj)
                                session.commit()
                                st.success(
                                    f"Deleted invoice "
                                    f"#{sel_row['invoice_number']}.")
                            session.close()
                            st.session_state.inv_delete_id = None
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error deleting invoice: {e}")
                with dc2:
                    if st.button("Cancel", key="cancel_del_inv",
                                 use_container_width=True):
                        st.session_state.inv_delete_id = None
                        st.rerun()

            # ── Edit form ─────────────────────────────────────────────
            elif is_editing_inv:
                st.markdown("---")
                st.markdown("##### Edit Invoice Header")
                vendor_names = get_vendor_names()

                with st.form("edit_invoice_form"):
                    eh1, eh2 = st.columns(2)
                    with eh1:
                        cur_vendor = sel_row.get("vendor_name") or ""
                        e_vendor = st.selectbox(
                            "Vendor", vendor_names,
                            index=vendor_names.index(cur_vendor)
                            if cur_vendor in vendor_names else 0)
                        e_inv_num = st.text_input(
                            "Invoice #",
                            value=sel_row.get("invoice_number") or "")
                    with eh2:
                        _date_min = date(2018, 1, 1)
                        _date_max = date(2030, 12, 31)

                        raw_inv_date = sel_row.get("invoice_date")
                        if isinstance(raw_inv_date, str):
                            raw_inv_date = datetime.strptime(
                                raw_inv_date, "%Y-%m-%d").date()
                        # Clamp to valid range so the widget doesn't error
                        if raw_inv_date and raw_inv_date < _date_min:
                            raw_inv_date = date.today()
                        if raw_inv_date and raw_inv_date > _date_max:
                            raw_inv_date = date.today()
                        e_inv_date = st.date_input(
                            "Invoice Date",
                            value=raw_inv_date or date.today(),
                            min_value=_date_min,
                            max_value=_date_max)

                        raw_recv_date = sel_row.get("received_date")
                        if isinstance(raw_recv_date, str) and raw_recv_date:
                            raw_recv_date = datetime.strptime(
                                raw_recv_date, "%Y-%m-%d").date()
                        elif not raw_recv_date or (isinstance(raw_recv_date, float) and pd.isna(raw_recv_date)):
                            raw_recv_date = date.today()
                        if raw_recv_date and raw_recv_date < _date_min:
                            raw_recv_date = date.today()
                        if raw_recv_date and raw_recv_date > _date_max:
                            raw_recv_date = date.today()
                        e_recv_date = st.date_input(
                            "Received Date",
                            value=raw_recv_date,
                            min_value=_date_min,
                            max_value=_date_max)

                    e_status = st.selectbox(
                        "Status", ["pending", "verified", "posted"],
                        index=["pending", "verified", "posted"].index(
                            sel_row.get("status") or "pending")
                        if (sel_row.get("status") or "pending")
                        in ["pending", "verified", "posted"] else 0)
                    e_notes = st.text_area(
                        "Notes",
                        value=sel_row.get("notes") or "",
                        height=60)

                    # ── Editable line items ───────────────────────────
                    st.markdown("##### Edit Line Items")

                    uom_options = ["bottle", "case", "each", "keg",
                                   "lb", "oz", "gallon", "liter", "pack",
                                   "bag", "box", "can", "unit"]
                    type_options = ["item", "credit", "fee"]

                    edit_lines = st.session_state.inv_edit_lines
                    lines_to_remove = []

                    # Separate by type for display
                    item_indices = [i for i, l in enumerate(edit_lines)
                                    if l.get("line_type", "item") == "item"]
                    credit_indices = [i for i, l in enumerate(edit_lines)
                                      if l.get("line_type") == "credit"]
                    fee_indices = [i for i, l in enumerate(edit_lines)
                                   if l.get("line_type") == "fee"]

                    # ── Item lines ──
                    st.caption("Inventory items (Qty x Unit Price)")
                    first_item = True
                    for i in item_indices:
                        line = edit_lines[i]
                        lc1, lc2, lc3, lc4, lc5, lc6 = st.columns(
                            [3, 1, 1, 1, 1, 0.5])
                        with lc1:
                            edit_lines[i]["description"] = st.text_input(
                                "Description", value=line["description"],
                                key=f"el_desc_{i}",
                                label_visibility="collapsed"
                                if not first_item else "visible")
                        with lc2:
                            edit_lines[i]["qty"] = st.number_input(
                                "Qty", value=line["qty"],
                                min_value=0.0, step=1.0,
                                key=f"el_qty_{i}",
                                label_visibility="collapsed"
                                if not first_item else "visible")
                        with lc3:
                            cur_uom = line.get("uom") or "bottle"
                            uom_idx = (uom_options.index(cur_uom)
                                       if cur_uom in uom_options else 0)
                            edit_lines[i]["uom"] = st.selectbox(
                                "Unit", uom_options, index=uom_idx,
                                key=f"el_uom_{i}",
                                label_visibility="collapsed"
                                if not first_item else "visible")
                        with lc4:
                            edit_lines[i]["unit_price"] = st.number_input(
                                "Unit Price",
                                value=line["unit_price"],
                                min_value=0.0, step=0.01,
                                format="%.2f",
                                key=f"el_up_{i}",
                                label_visibility="collapsed"
                                if not first_item else "visible")
                        with lc5:
                            ext = round(
                                edit_lines[i]["qty"]
                                * edit_lines[i]["unit_price"], 2)
                            st.text_input(
                                "Ext Price",
                                value=f"${ext:,.2f}",
                                disabled=True,
                                key=f"el_ext_{i}",
                                label_visibility="collapsed"
                                if not first_item else "visible")
                        with lc6:
                            if st.form_submit_button(
                                    "🗑️", key=f"el_rm_{i}"):
                                lines_to_remove.append(i)
                        first_item = False

                    # ── Credit lines ──
                    st.markdown("---")
                    st.markdown("**Credits** (returned kegs, packaging, etc.)")
                    first_credit = True
                    for i in credit_indices:
                        line = edit_lines[i]
                        cc1, cc2, cc3 = st.columns([5, 2, 0.5])
                        with cc1:
                            edit_lines[i]["description"] = st.text_input(
                                "Description", value=line["description"],
                                key=f"el_desc_{i}",
                                label_visibility="collapsed"
                                if not first_credit else "visible")
                        with cc2:
                            edit_lines[i]["amount"] = st.number_input(
                                "Amount", value=float(line.get("amount", 0)),
                                min_value=0.0, step=0.01, format="%.2f",
                                key=f"el_amt_{i}",
                                label_visibility="collapsed"
                                if not first_credit else "visible")
                        with cc3:
                            if st.form_submit_button(
                                    "🗑️", key=f"el_rm_{i}"):
                                lines_to_remove.append(i)
                        first_credit = False

                    # ── Fee lines ──
                    st.markdown("---")
                    st.markdown("**Fees** (delivery, surcharges, etc.)")
                    first_fee = True
                    for i in fee_indices:
                        line = edit_lines[i]
                        fc1, fc2, fc3 = st.columns([5, 2, 0.5])
                        with fc1:
                            edit_lines[i]["description"] = st.text_input(
                                "Description", value=line["description"],
                                key=f"el_desc_{i}",
                                label_visibility="collapsed"
                                if not first_fee else "visible")
                        with fc2:
                            edit_lines[i]["amount"] = st.number_input(
                                "Amount", value=float(line.get("amount", 0)),
                                min_value=0.0, step=0.01, format="%.2f",
                                key=f"el_amt_{i}",
                                label_visibility="collapsed"
                                if not first_fee else "visible")
                        with fc3:
                            if st.form_submit_button(
                                    "🗑️", key=f"el_rm_{i}"):
                                lines_to_remove.append(i)
                        first_fee = False

                    # Process removals
                    for idx in sorted(lines_to_remove, reverse=True):
                        removed = st.session_state.inv_edit_lines.pop(idx)
                        if removed.get("line_id"):
                            st.session_state.inv_edit_lines_to_delete.append(
                                removed["line_id"])
                        st.rerun()

                    # Totals
                    items_subtotal = sum(
                        l["qty"] * l["unit_price"]
                        for l in edit_lines
                        if l.get("line_type", "item") == "item"
                        and l["description"].strip())
                    credits_subtotal = sum(
                        l.get("amount", 0)
                        for l in edit_lines
                        if l.get("line_type") == "credit"
                        and l["description"].strip())
                    fees_subtotal = sum(
                        l.get("amount", 0)
                        for l in edit_lines
                        if l.get("line_type") == "fee"
                        and l["description"].strip())
                    edit_total = items_subtotal - credits_subtotal + fees_subtotal

                    st.markdown("---")
                    et1, et2, et3, et4 = st.columns(4)
                    with et1:
                        st.markdown(f"**Items:** ${items_subtotal:,.2f}")
                    with et2:
                        st.markdown(f"**Credits:** -${credits_subtotal:,.2f}")
                    with et3:
                        st.markdown(f"**Fees:** +${fees_subtotal:,.2f}")
                    with et4:
                        st.markdown(f"**Total: ${edit_total:,.2f}**")

                    # ── Form buttons ──────────────────────────────────
                    sf1, sf2, sf3, sf4, sf5 = st.columns(5)
                    with sf1:
                        save_inv = st.form_submit_button(
                            "💾 Save Changes", type="primary",
                            use_container_width=True)
                    with sf2:
                        add_line = st.form_submit_button(
                            "➕ Add Item", use_container_width=True)
                    with sf3:
                        add_credit = st.form_submit_button(
                            "➕ Add Credit", use_container_width=True)
                    with sf4:
                        add_fee = st.form_submit_button(
                            "➕ Add Fee", use_container_width=True)
                    with sf5:
                        cancel_inv = st.form_submit_button(
                            "Cancel", use_container_width=True)

                    if add_line:
                        st.session_state.inv_edit_lines.append({
                            "line_id": None,
                            "line_type": "item",
                            "description": "",
                            "qty": 1.0,
                            "uom": "bottle",
                            "unit_price": 0.0,
                            "amount": 0.0,
                        })
                        st.rerun()

                    if add_credit:
                        st.session_state.inv_edit_lines.append({
                            "line_id": None,
                            "line_type": "credit",
                            "description": "",
                            "qty": 0.0,
                            "uom": "bottle",
                            "unit_price": 0.0,
                            "amount": 0.0,
                        })
                        st.rerun()

                    if add_fee:
                        st.session_state.inv_edit_lines.append({
                            "line_id": None,
                            "line_type": "fee",
                            "description": "",
                            "qty": 0.0,
                            "uom": "bottle",
                            "unit_price": 0.0,
                            "amount": 0.0,
                        })
                        st.rerun()

                    if cancel_inv:
                        st.session_state.inv_edit_id = None
                        st.session_state.inv_edit_lines = []
                        st.session_state.inv_edit_lines_to_delete = []
                        st.rerun()

                    if save_inv:
                        # Validation
                        errors = []
                        if not e_inv_num.strip():
                            errors.append("Invoice # is required.")
                        valid_items = [
                            l for l in edit_lines
                            if l.get("line_type", "item") == "item"
                            and l["description"].strip()]
                        if not valid_items:
                            errors.append(
                                "At least one line item is required.")

                        if errors:
                            for err in errors:
                                st.error(err)
                        else:
                            try:
                                session = get_session()
                                inv_obj = session.query(
                                    InvInvoice).get(sel_inv_id)
                                if inv_obj:
                                    new_vendor_id = get_vendor_id_by_name(
                                        e_vendor)
                                    inv_obj.vendor_id = new_vendor_id
                                    inv_obj.invoice_number = (
                                        e_inv_num.strip())
                                    inv_obj.invoice_date = e_inv_date
                                    inv_obj.received_date = e_recv_date
                                    inv_obj.status = e_status
                                    inv_obj.notes = (
                                        e_notes.strip() or None)
                                    inv_obj.total_amount = Decimal(
                                        str(round(edit_total, 2)))

                                    # Delete removed lines
                                    for lid in (st.session_state
                                                .inv_edit_lines_to_delete):
                                        session.query(
                                            InvInvoiceLine
                                        ).filter_by(id=lid).delete()

                                    # Update / insert lines
                                    line_num = 1
                                    for line in edit_lines:
                                        if not line[
                                                "description"].strip():
                                            continue
                                        lt = line.get(
                                            "line_type", "item")

                                        # Compute extended price
                                        if lt == "item":
                                            ext = round(
                                                line["qty"]
                                                * line["unit_price"], 2)
                                        elif lt == "credit":
                                            ext = -abs(round(
                                                line.get("amount", 0), 2))
                                        else:  # fee
                                            ext = abs(round(
                                                line.get("amount", 0), 2))

                                        if line.get("line_id"):
                                            db_line = session.query(
                                                InvInvoiceLine
                                            ).get(line["line_id"])
                                            if db_line:
                                                db_line.description = (
                                                    line["description"]
                                                    .strip())
                                                db_line.line_type = lt
                                                if lt == "item":
                                                    db_line.quantity = (
                                                        Decimal(str(
                                                            line["qty"])))
                                                    db_line.unit_of_measure = (
                                                        line["uom"])
                                                    db_line.unit_price = (
                                                        Decimal(str(
                                                            line[
                                                                "unit_price"
                                                            ])))
                                                else:
                                                    db_line.quantity = None
                                                    db_line.unit_of_measure = None
                                                    db_line.unit_price = None
                                                db_line.extended_price = (
                                                    Decimal(str(ext)))
                                                db_line.line_number = (
                                                    line_num)
                                        else:
                                            new_line = InvInvoiceLine(
                                                invoice_id=sel_inv_id,
                                                description=(
                                                    line["description"]
                                                    .strip()),
                                                line_type=lt,
                                                quantity=(
                                                    Decimal(str(
                                                        line["qty"]))
                                                    if lt == "item"
                                                    else None),
                                                unit_of_measure=(
                                                    line["uom"]
                                                    if lt == "item"
                                                    else None),
                                                unit_price=(
                                                    Decimal(str(
                                                        line["unit_price"]))
                                                    if lt == "item"
                                                    else None),
                                                extended_price=Decimal(
                                                    str(ext)),
                                                line_number=line_num,
                                                matched=False,
                                            )
                                            session.add(new_line)
                                        line_num += 1

                                    session.commit()
                                    st.success(
                                        f"Invoice #{e_inv_num.strip()} "
                                        f"updated successfully!")
                                    session.close()

                                st.session_state.inv_edit_id = None
                                st.session_state.inv_edit_lines = []
                                st.session_state.inv_edit_lines_to_delete = []
                                st.rerun()

                            except Exception as e:
                                st.error(
                                    f"Error updating invoice: {e}")

            # ── Read-only line items (when not editing) ───────────────
            else:
                lines_df = get_invoice_lines(sel_inv_id)
                if not lines_df.empty:
                    # Ensure line_type column exists (backward compat)
                    if "line_type" not in lines_df.columns:
                        lines_df["line_type"] = "item"
                    lines_df["line_type"] = lines_df["line_type"].fillna("item")

                    lines_df["unit_price"] = pd.to_numeric(
                        lines_df["unit_price"], errors="coerce").fillna(0)
                    lines_df["extended_price"] = pd.to_numeric(
                        lines_df["extended_price"], errors="coerce").fillna(0)
                    lines_df["quantity"] = pd.to_numeric(
                        lines_df["quantity"], errors="coerce").fillna(0)

                    display_lines = lines_df[["line_number", "line_type",
                                               "description", "quantity",
                                               "unit_of_measure",
                                               "unit_price",
                                               "extended_price"]].copy()
                    display_lines["unit_price"] = display_lines.apply(
                        lambda r: f"${r['unit_price']:,.2f}"
                        if r["line_type"] == "item" else "", axis=1)
                    display_lines["quantity"] = display_lines.apply(
                        lambda r: r["quantity"]
                        if r["line_type"] == "item" else None, axis=1)
                    display_lines["unit_of_measure"] = display_lines.apply(
                        lambda r: r["unit_of_measure"]
                        if r["line_type"] == "item" else "", axis=1)
                    display_lines["extended_price"] = display_lines[
                        "extended_price"].apply(lambda x: f"${x:,.2f}")
                    display_lines["line_type"] = display_lines[
                        "line_type"].str.capitalize()
                    display_lines.columns = ["#", "Type", "Description",
                                             "Qty", "Unit", "Unit Price",
                                             "Ext Price"]
                    st.dataframe(display_lines, hide_index=True,
                                 use_container_width=True)

                    # Breakdown totals
                    items_sum = lines_df.loc[
                        lines_df["line_type"] == "item",
                        "extended_price"].sum()
                    credits_sum = abs(lines_df.loc[
                        lines_df["line_type"] == "credit",
                        "extended_price"].sum())
                    fees_sum = lines_df.loc[
                        lines_df["line_type"] == "fee",
                        "extended_price"].sum()
                    if credits_sum > 0 or fees_sum > 0:
                        br1, br2, br3, br4 = st.columns(4)
                        with br1:
                            st.metric("Items", f"${items_sum:,.2f}")
                        with br2:
                            st.metric("Credits", f"-${credits_sum:,.2f}")
                        with br3:
                            st.metric("Fees", f"+${fees_sum:,.2f}")
                        with br4:
                            st.metric("Total",
                                      f"${items_sum - credits_sum + fees_sum:,.2f}")
                else:
                    st.info("No line items for this invoice.")
    else:
        st.info("No invoices entered yet. Use the **New Invoice** tab to add one.")


# ════════════════════════════════════════════════════════════════════════════
# TAB 3: MANAGE VENDORS
# ════════════════════════════════════════════════════════════════════════════

with tab_vendors:
    st.subheader("Manage Vendors")

    # ── Session-state helpers for edit / delete workflows ─────────────
    if "vendor_edit_id" not in st.session_state:
        st.session_state.vendor_edit_id = None
    if "vendor_delete_id" not in st.session_state:
        st.session_state.vendor_delete_id = None

    vendors_df = get_vendors()

    # ── Current Vendors table with Edit / Delete buttons ──────────────
    if not vendors_df.empty:
        st.markdown("#### Current Vendors")

        for _, row in vendors_df.iterrows():
            vid = int(row["id"])
            is_editing = st.session_state.vendor_edit_id == vid
            is_deleting = st.session_state.vendor_delete_id == vid

            with st.container(border=True):
                # ── Header row: vendor name + action buttons ──────────
                hdr_left, hdr_right = st.columns([4, 1])
                with hdr_left:
                    st.markdown(f"**{row['name']}**")
                with hdr_right:
                    btn_cols = st.columns(2)
                    with btn_cols[0]:
                        if st.button("✏️", key=f"edit_{vid}",
                                     help="Edit this vendor",
                                     use_container_width=True):
                            st.session_state.vendor_edit_id = (
                                None if is_editing else vid
                            )
                            st.session_state.vendor_delete_id = None
                            st.rerun()
                    with btn_cols[1]:
                        if st.button("🗑️", key=f"del_{vid}",
                                     help="Delete this vendor",
                                     use_container_width=True):
                            st.session_state.vendor_delete_id = (
                                None if is_deleting else vid
                            )
                            st.session_state.vendor_edit_id = None
                            st.rerun()

                # ── Delete confirmation ───────────────────────────────
                if is_deleting:
                    st.warning(
                        f"Are you sure you want to delete **{row['name']}**? "
                        "This cannot be undone."
                    )
                    dc1, dc2, dc3 = st.columns([1, 1, 3])
                    with dc1:
                        if st.button("Yes, delete", key=f"confirm_del_{vid}",
                                     type="primary", use_container_width=True):
                            try:
                                session = get_session()
                                vendor_obj = session.query(InvVendor).get(vid)
                                if vendor_obj:
                                    session.delete(vendor_obj)
                                    session.commit()
                                    st.success(f"Deleted **{row['name']}**.")
                                session.close()
                                st.session_state.vendor_delete_id = None
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error deleting vendor: {e}")
                    with dc2:
                        if st.button("Cancel", key=f"cancel_del_{vid}",
                                     use_container_width=True):
                            st.session_state.vendor_delete_id = None
                            st.rerun()

                # ── Inline edit form ──────────────────────────────────
                elif is_editing:
                    with st.form(f"edit_vendor_{vid}"):
                        e1, e2 = st.columns(2)
                        with e1:
                            e_name = st.text_input(
                                "Vendor Name *", value=row["name"] or "")
                            e_contact = st.text_input(
                                "Contact Name",
                                value=row.get("contact_name") or "")
                            e_phone = st.text_input(
                                "Phone", value=row.get("phone") or "")
                            e_email = st.text_input(
                                "Email", value=row.get("email") or "")
                        with e2:
                            e_supply = st.text_input(
                                "Supply Categories",
                                value=row.get("supply_categories") or "")
                            e_delivery = st.text_input(
                                "Delivery Days",
                                value=row.get("delivery_days") or "")
                            deadline_opts = [
                                "", "monday", "tuesday", "wednesday",
                                "thursday", "friday", "saturday", "sunday",
                            ]
                            cur_deadline = row.get("order_deadline_day") or ""
                            e_deadline = st.selectbox(
                                "Order Deadline Day", deadline_opts,
                                index=deadline_opts.index(cur_deadline)
                                if cur_deadline in deadline_opts else 0)
                            e_lead = st.number_input(
                                "Lead Time (days)", min_value=0,
                                max_value=14,
                                value=int(row.get("lead_time_days") or 0))

                        fmt_opts = ["email_pdf", "paper", "portal"]
                        cur_fmt = row.get("invoice_format") or "email_pdf"
                        e_fmt = st.selectbox(
                            "Invoice Format", fmt_opts,
                            index=fmt_opts.index(cur_fmt)
                            if cur_fmt in fmt_opts else 0)
                        e_notes = st.text_area(
                            "Notes", value=row.get("notes") or "", height=60)

                        sf1, sf2 = st.columns(2)
                        with sf1:
                            save_clicked = st.form_submit_button(
                                "💾 Save Changes", type="primary",
                                use_container_width=True)
                        with sf2:
                            cancel_clicked = st.form_submit_button(
                                "Cancel", use_container_width=True)

                        if save_clicked:
                            if not e_name.strip():
                                st.error("Vendor name is required.")
                            else:
                                try:
                                    session = get_session()
                                    vendor_obj = session.query(
                                        InvVendor).get(vid)
                                    if vendor_obj:
                                        vendor_obj.name = e_name.strip()
                                        vendor_obj.contact_name = (
                                            e_contact.strip() or None)
                                        vendor_obj.phone = (
                                            e_phone.strip() or None)
                                        vendor_obj.email = (
                                            e_email.strip() or None)
                                        vendor_obj.supply_categories = (
                                            e_supply.strip() or None)
                                        vendor_obj.delivery_days = (
                                            e_delivery.strip() or None)
                                        vendor_obj.order_deadline_day = (
                                            e_deadline or None)
                                        vendor_obj.lead_time_days = (
                                            e_lead if e_lead > 0 else None)
                                        vendor_obj.invoice_format = e_fmt
                                        vendor_obj.notes = (
                                            e_notes.strip() or None)
                                        session.commit()
                                        st.success(
                                            f"Updated **{e_name.strip()}**!")
                                    session.close()
                                    st.session_state.vendor_edit_id = None
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error updating vendor: {e}")

                        if cancel_clicked:
                            st.session_state.vendor_edit_id = None
                            st.rerun()

                # ── Read-only summary row ─────────────────────────────
                else:
                    c1, c2, c3, c4, c5 = st.columns(5)
                    c1.caption("Contact")
                    c1.write(row.get("contact_name") or "—")
                    c2.caption("Phone")
                    c2.write(row.get("phone") or "—")
                    c3.caption("Email")
                    c3.write(row.get("email") or "—")
                    c4.caption("Supplies")
                    c4.write(row.get("supply_categories") or "—")
                    c5.caption("Delivery Days")
                    c5.write(row.get("delivery_days") or "—")

        st.markdown("---")

    # ── Add new vendor form ───────────────────────────────────────────
    st.markdown("#### Add New Vendor")

    with st.form("add_vendor_form"):
        v1, v2 = st.columns(2)
        with v1:
            v_name = st.text_input("Vendor Name *",
                                   placeholder="e.g., Beverage Distributor")
            v_contact = st.text_input("Contact Name", placeholder="Rep name")
            v_phone = st.text_input("Phone", placeholder="(555) 123-4567")
            v_email = st.text_input("Email", placeholder="rep@vendor.com")
        with v2:
            v_supply = st.text_input("Supply Categories",
                                     placeholder="e.g., spirits, wine")
            v_delivery = st.text_input("Delivery Days",
                                       placeholder="e.g., tue, thu")
            v_deadline_day = st.selectbox("Order Deadline Day",
                                          ["", "monday", "tuesday",
                                           "wednesday", "thursday", "friday",
                                           "saturday", "sunday"])
            v_lead_time = st.number_input("Lead Time (days)", min_value=0,
                                           max_value=14, value=2)

        v_invoice_format = st.selectbox("Invoice Format",
                                         ["email_pdf", "paper", "portal"])
        v_notes = st.text_area("Notes", height=60,
                               placeholder="Any notes about this vendor...")

        submitted = st.form_submit_button("💾 Add Vendor", type="primary",
                                           use_container_width=True)
        if submitted:
            if not v_name.strip():
                st.error("Vendor name is required.")
            else:
                try:
                    session = get_session()
                    existing = session.query(InvVendor).filter_by(
                        name=v_name.strip()
                    ).first()

                    if existing:
                        st.error(f"Vendor '{v_name}' already exists.")
                    else:
                        vendor = InvVendor(
                            name=v_name.strip(),
                            contact_name=v_contact.strip() or None,
                            phone=v_phone.strip() or None,
                            email=v_email.strip() or None,
                            supply_categories=v_supply.strip() or None,
                            delivery_days=v_delivery.strip() or None,
                            order_deadline_day=v_deadline_day or None,
                            lead_time_days=(v_lead_time
                                            if v_lead_time > 0 else None),
                            invoice_format=v_invoice_format,
                            notes=v_notes.strip() or None,
                        )
                        session.add(vendor)
                        session.commit()
                        st.success(f"Vendor '{v_name}' added successfully!")
                        session.close()
                        st.rerun()

                except Exception as e:
                    st.error(f"Error adding vendor: {e}")

st.markdown("---")
st.caption("Invoice Management | Bar Arbolada Analytics")
