"""
Invoice PDF Parser
====================
3-tier parsing pipeline:
  1. pdfplumber (text-based PDFs) — structured text extraction
  2. OCR fallback (image-based PDFs) — future enhancement
  3. Manual entry fallback — already built in the Streamlit UI

Vendor-specific parsers extract structured line items from
each vendor's unique invoice format.

Currently supported:
  - Food/supply distributor PDFs
  - Beverage distributor PDFs
  - Generic text-based invoices (best-effort)
"""

import re
from datetime import date, datetime
from decimal import Decimal
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False


@dataclass
class ParsedInvoiceLine:
    """A single line item parsed from an invoice."""
    line_number: int
    description: str
    quantity: float
    unit_of_measure: str = "bottle"
    unit_price: float = 0.0
    extended_price: float = 0.0
    item_code: str = ""
    pack_size: str = ""
    bottle_size: str = ""
    notes: str = ""


@dataclass
class ParsedInvoice:
    """A fully parsed invoice."""
    vendor_name: str = ""
    invoice_number: str = ""
    invoice_date: Optional[date] = None
    delivery_date: Optional[date] = None
    total_amount: float = 0.0
    lines: list[ParsedInvoiceLine] = field(default_factory=list)
    raw_text: str = ""
    confidence: str = "high"  # high, medium, low
    parse_method: str = "pdfplumber"
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def parse_invoice_pdf(pdf_path: str | Path) -> ParsedInvoice:
    """
    Parse an invoice PDF. Auto-detects vendor and applies
    the appropriate parser.

    Returns a ParsedInvoice with extracted data and confidence level.
    """
    pdf_path = Path(pdf_path)

    if not HAS_PDFPLUMBER:
        result = ParsedInvoice()
        result.errors.append("pdfplumber not installed. Run: pip install pdfplumber")
        result.confidence = "low"
        return result

    if not pdf_path.exists():
        result = ParsedInvoice()
        result.errors.append(f"File not found: {pdf_path}")
        return result

    # Extract text from all pages
    full_text = ""
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    full_text += text + "\n\n"
    except Exception as e:
        result = ParsedInvoice()
        result.errors.append(f"Failed to read PDF: {e}")
        result.confidence = "low"
        return result

    if not full_text.strip():
        result = ParsedInvoice()
        result.errors.append(
            "No text could be extracted from this PDF. "
            "It appears to be image-based (scanned). "
            "Use manual entry or scan with an OCR app (Adobe Scan, Microsoft Lens)."
        )
        result.confidence = "low"
        result.parse_method = "failed"
        return result

    # Detect vendor and apply parser
    text_lower = full_text.lower()

    if "beverage distributor a" in text_lower:
        return _parse_beverage_distributor_a(full_text)
    elif "beverage distributor b" in text_lower:
        return _parse_beverage_distributor_b(full_text)
    elif "spirits distributor" in text_lower:
        return _parse_generic_spirits(full_text, vendor_name="Spirits Distributor")
    elif "food distributor a" in text_lower:
        return _parse_food_distributor_a(full_text)
    elif "food distributor" in text_lower:
        return _parse_generic_food(full_text, vendor_name="Food Distributor")
    else:
        return _parse_generic(full_text)


# ============================================================================
# FOOD DISTRIBUTOR A PARSER
# ============================================================================

_FOOD_DISTRIBUTOR_A_CATEGORY_HEADERS = {
    "DAIRY PRODUCTS", "POULTRY", "MEATS", "FROZEN", "CANNED & DRY",
    "PAPER & DISP", "PRODUCE", "SEAFOOD", "BEVERAGES",
    "SUPPLIES & EQUIPMENT",
}

_FOOD_DISTRIBUTOR_A_SKIP_FRAGMENTS = [
    "GROUP TOTAL", "ORDER SUMMARY", "OPEN:", "CONT. ON PAGE",
    "LAST PAGE", "TRUCK STOP", "CUSTOMER NAME",
    "EQUAL", "OPPORTUNITY", "AFFRIMATIVE", "CLAUSES",
    "PACA PROVISION", "PAYABLE ON", "DRIVER", "MANIFEST",
    "CONFIDENTIAL", "DELIVERY COPY",
    "ROLLING", "TERMS -", "TERMS ", "ROUTE", "PURCHASE ORDER", "FISH LIC",
    "SHELL FISH", "PLEASE REGISTER", "REFERENCE :",
    "AMOUNT DUE", "IF PAID BEFORE", "P.O.", "SHIPPER INVOICE",
    "DROP-SHIP", "IMPORTANT PACA", "AUTHORIZED BY", "RETAINS A",
    "AND ANY RECEIVABLE", "REPRESENTATIVE", "RESPECT TO",
    "CASES SPLIT", "CUST.SIGNED", "NO. PCS", "SIGN",
    "TERRITORY:", "REMIT TO", "INVOICE ADJUSTMENTS",
    "EXTENDED", "PACK SIZE", "ITEM DESCRIPTION",
    "* * CREDIT MEMO", "NOT FOR SHIPMENT",
    "TECUMSEH", "W MAIN ST", "NW 17TH", "637 W",
    "DAMAGED", "INVOICE", "T OT A L", "T AX", "S UB",
    "SPLITTOT", "GROSS WT", "I MP O RT",
]


def _parse_food_distributor_a(text: str) -> ParsedInvoice:
    """
    Parse a food/supply distributor invoice PDF.

    Handles three sub-formats:
      - Standard delivery invoices (426* invoice numbers)
      - Special-order invoices (126A* invoice numbers)
      - Credit memos (negative amounts, "CREDIT MEMO" marker)

    Line item format (after header stripping):
      [ZONE] QTY[S] [CS|ONLY|SCS] PACK_SIZE DESCRIPTION ITEM_CODES UNIT_PRICE [TAX] EXT_PRICE [*]
    """
    result = ParsedInvoice(
        vendor_name="Food Distributor A",
        raw_text=text,
        parse_method="pdfplumber_food_distributor_a",
    )

    is_credit = "CREDIT MEMO" in text

    # --- Invoice number ---
    # Standard distributor header with customer, route, and invoice identifiers.
    inv_match = re.search(r'TRUCK\s+STOP\s+\d+\s+(\S+)', text)
    if inv_match:
        result.invoice_number = inv_match.group(1)
    else:
        # 126A format: "974392 126A3423Z 1"
        inv_match = re.search(r'974392\s+(\S+)\s+\d+\s*$', text, re.MULTILINE)
        if inv_match:
            result.invoice_number = inv_match.group(1)

    # --- Delivery date ---
    # pdfplumber: date on its own line, followed by a line containing TRUCK STOP
    date_match = re.search(
        r'(\d{1,2}/\d{1,2}/\d{2,4})\s*\n.*?TRUCK\s+STOP', text
    )
    if not date_match:
        # 126A format: date appears elsewhere in the header
        date_match = re.search(
            r'DELV\.\s+DATE.*?\n.*?TRUCK\s+STOP.*?\n'
            r'.*?(\d{1,2}/\d{1,2}/\d{2,4})',
            text, re.DOTALL,
        )
    if not date_match:
        # Last resort: first standalone date near the top
        date_match = re.search(r'^(\d{1,2}/\d{1,2}/\d{2,4})\s*$', text, re.MULTILINE)
    if date_match:
        try:
            result.delivery_date = _parse_date(date_match.group(1))
            result.invoice_date = result.delivery_date
        except ValueError:
            result.warnings.append(
                f"Could not parse delivery date: {date_match.group(1)}"
            )

    # --- Invoice total ---
    # pdfplumber renders "TOTAL" as "T OT A L" with spaced letters.
    # The last occurrence of "T OT A L ###.##" is the invoice total.
    total_matches = list(re.finditer(
        r'T\s*OT\s*A\s*L\s+([\d,]+\.\d{2})-?', text
    ))
    if total_matches:
        total_val = float(total_matches[-1].group(1).replace(",", ""))
        result.total_amount = -total_val if is_credit else total_val

    # 126A format: "IF PAID BEFORE: ... INVOICE ###.##"
    if not result.total_amount:
        paid_match = re.search(
            r'IF\s+PAID\s+BEFORE:.*?([\d,]+\.\d{2})', text
        )
        if paid_match:
            result.total_amount = float(
                paid_match.group(1).replace(",", "")
            )

    # --- Parse line items ---
    current_category = ""
    line_num = 0

    for raw_line in text.split("\n"):
        stripped = raw_line.strip()
        if not stripped:
            continue

        # Category headers
        if stripped in _FOOD_DISTRIBUTOR_A_CATEGORY_HEADERS:
            current_category = stripped
            continue

        # Fuel surcharge
        fuel_match = re.match(
            r'MISC\s+CHARGES\s+CHGS\s+FOR\s+FUEL\s+SURCHARGE\s+'
            r'([\d,]+\.\d{2})',
            stripped,
        )
        if fuel_match:
            line_num += 1
            amt = float(fuel_match.group(1).replace(",", ""))
            result.lines.append(ParsedInvoiceLine(
                line_number=line_num,
                description="Fuel Surcharge",
                quantity=1.0,
                unit_of_measure="each",
                unit_price=amt,
                extended_price=amt,
                notes="fee",
            ))
            continue

        # Freight charge (126A format)
        freight_match = re.match(
            r'\d+\s+Charge\s+Freight\s+\S+\s+'
            r'([\d,]+\.\d{2})\s+([\d,]+\.\d{2})',
            stripped,
        )
        if freight_match:
            line_num += 1
            result.lines.append(ParsedInvoiceLine(
                line_number=line_num,
                description="Freight Charge",
                quantity=1.0,
                unit_of_measure="each",
                unit_price=float(freight_match.group(1).replace(",", "")),
                extended_price=float(freight_match.group(2).replace(",", "")),
                notes="fee",
            ))
            continue

        # Standard line item
        parsed = _parse_food_distributor_a_line(stripped, current_category, is_credit)
        if parsed:
            line_num += 1
            parsed.line_number = line_num
            result.lines.append(parsed)

    # --- Confidence ---
    if not result.lines:
        result.confidence = "low"
        result.warnings.append("No line items could be parsed")
    elif len(result.lines) < 2:
        result.confidence = "medium"

    # --- Validate total ---
    computed = sum(abs(ln.extended_price) for ln in result.lines)
    if result.total_amount and abs(computed - abs(result.total_amount)) > 2.0:
        result.warnings.append(
            f"Computed total (${computed:.2f}) differs from "
            f"invoice total (${abs(result.total_amount):.2f})"
        )

    return result


def _parse_food_distributor_a_line(
    line: str, current_category: str, is_credit: bool
) -> Optional[ParsedInvoiceLine]:
    """
    Parse a single food distributor invoice line item.

    Returns None for non-item lines (boilerplate, headers, OUT items).
    """
    if not line or len(line) < 20:
        return None

    upper = line.upper()

    # Skip boilerplate / header lines
    for frag in _FOOD_DISTRIBUTOR_A_SKIP_FRAGMENTS:
        if frag in upper:
            return None

    # Skip single-letter/number orphan lines and category headers
    if re.match(r'^[A-Z]$', line) or re.match(r'^\d{1,2}$', line):
        return None
    if upper == "SUBSTITUTE":
        return None

    # Skip weight detail lines (e.g. "20.000 20.000 20.000 T/WT= 120.000")
    if "T/WT=" in upper:
        return None
    if re.match(r'^[\d.\s]+$', line):
        return None

    # Must contain at least one price (##.##)
    if not re.search(r'\d+\.\d{2}', line):
        return None

    # --- Match line start ---
    # With zone: [CDFX] QTY[S] [CS|ONLY|SCS]
    start_match = re.match(
        r'^([CDFX])\s+'
        r'(\d+|OUT)(S?)\s*'
        r'(CS|ONLY|SCS)?\s*',
        line,
    )

    zone = ""
    qty_str = ""
    is_split = False
    rest_start = 0

    if start_match:
        zone = start_match.group(1)
        qty_str = start_match.group(2)
        is_split = bool(start_match.group(3))
        rest_start = start_match.end()
    else:
        # Without zone (credit memos, 126A specials)
        no_zone = re.match(r'^(\d+)(S?)\s*(CS|ONLY|SCS)?\s*', line)
        if no_zone:
            qty_str = no_zone.group(1)
            is_split = bool(no_zone.group(2))
            rest_start = no_zone.end()
        else:
            return None

    if qty_str == "OUT":
        return None

    try:
        qty = int(qty_str)
    except ValueError:
        return None
    if qty <= 0:
        return None

    rest = line[rest_start:]

    # --- Extract prices from end of line ---
    has_tax_flag = rest.rstrip().endswith("*")
    is_negative = bool(re.search(r'\d\.\d{2}\s*-', rest))

    all_prices = list(re.finditer(r'([\d,]+\.\d{2})', rest))
    if not all_prices:
        return None

    if has_tax_flag and len(all_prices) >= 3:
        unit_price = float(all_prices[-3].group(1).replace(",", ""))
        ext_price = float(all_prices[-1].group(1).replace(",", ""))
        info_end = all_prices[-3].start()
    elif len(all_prices) >= 2:
        unit_price = float(all_prices[-2].group(1).replace(",", ""))
        ext_price = float(all_prices[-1].group(1).replace(",", ""))
        info_end = all_prices[-2].start()
    else:
        unit_price = float(all_prices[0].group(1).replace(",", ""))
        ext_price = unit_price * qty
        info_end = all_prices[0].start()

    if is_negative or is_credit:
        ext_price = -abs(ext_price)

    # --- Parse product info (pack + description + item codes) ---
    product_info = rest[:info_end].strip()
    if not product_info:
        return None

    tokens = product_info.split()

    # Extract item codes from the end (purely numeric tokens, 4+ digits)
    item_code = ""
    while tokens and re.match(r'^[\d]{4,}$', tokens[-1]):
        item_code = tokens.pop()

    # Also pop alphanumeric customer codes (e.g. "90101-COM", "02116-BBC")
    if tokens and re.match(r'^[\d]+-[A-Z]+$', tokens[-1]):
        tokens.pop()

    description = " ".join(tokens)

    # Extract pack size from start of description
    pack_size = ""
    pack_match = re.match(
        r'^([\d.]+\s*(?:LB|OZ|CT|EA|GAL|PK|PCS|ML|QT|PT))\b\s*',
        description,
        re.IGNORECASE,
    )
    if pack_match:
        pack_size = pack_match.group(1).strip()
        description = description[pack_match.end():].strip()

    if not description:
        return None

    uom = "each" if is_split else "case"

    return ParsedInvoiceLine(
        line_number=0,
        description=description,
        quantity=float(qty),
        unit_of_measure=uom,
        unit_price=unit_price,
        extended_price=ext_price,
        item_code=item_code,
        pack_size=pack_size,
        notes=current_category,
    )


# ============================================================================
# BEVERAGE DISTRIBUTOR A PARSER
# ============================================================================


def _parse_beverage_distributor_a(text: str) -> ParsedInvoice:
    """
    Parse a beverage distributor invoice format.

    Line item pattern:
        QTY/QTY ITEM_NAME PROOF UNIT_PRICE DISC NET TOTAL
        ITEM#: XXXXX BPC: N SIZE: 750ML

    Example:
        2/2 SAMPLE PRODUCT 22 10.00 0.00 10.00 20.00
        ITEM#: 557367 BPC: 6 SIZE: 1LT
    """
    result = ParsedInvoice(
        vendor_name="Beverage Distributor A",
        raw_text=text,
        parse_method="pdfplumber",
    )

    # Extract invoice number
    inv_match = re.search(r'INVOICE\s*\n?\s*(\d{7,})', text)
    if inv_match:
        result.invoice_number = inv_match.group(1)

    # Extract invoice date
    date_match = re.search(
        r'INVOICE\s+DATE\s+DELIVERY\s+DATE.*?\n'
        r'.*?(\d{1,2}/\d{1,2}/\d{2,4})\s+(\d{1,2}/\d{1,2}/\d{2,4})',
        text, re.DOTALL
    )
    if date_match:
        try:
            result.invoice_date = _parse_date(date_match.group(1))
            result.delivery_date = _parse_date(date_match.group(2))
        except ValueError:
            result.warnings.append("Could not parse invoice/delivery dates")

    # Extract total amount
    total_match = re.search(r'PAY\s+THIS\s+AMOUNT\s*\n?\s*([\d,]+\.\d{2})', text)
    if total_match:
        result.total_amount = float(total_match.group(1).replace(",", ""))

    # Parse line items
    # Pattern: QTY/QTY ITEM_NAME PROOF UNIT_PRICE DISC NET TOTAL
    # Followed by: ITEM#: XXXXX BPC: N SIZE: XXX
    line_pattern = re.compile(
        r'^\*?\s*(\d+)/(\d+)\s+'        # ordered/delivered qty
        r'(.+?)\s+'                       # item name
        r'(\d+)\s+'                       # proof
        r'([\d,]+\.\d{2})\s+'            # unit price
        r'([\d,]+\.\d{2})\s+'            # discount
        r'([\d,]+\.\d{2})\s+'            # net price
        r'([\d,]+\.\d{2})',              # total
        re.MULTILINE
    )

    detail_pattern = re.compile(
        r'ITEM#:\s*(\d+)\s+BPC:\s*(\d+)\s+SIZE:\s*(\S+)',
        re.MULTILINE
    )

    # Find all line items
    line_matches = list(line_pattern.finditer(text))
    detail_matches = list(detail_pattern.finditer(text))

    # Build detail lookup by position
    for idx, match in enumerate(line_matches):
        ordered = int(match.group(1))
        delivered = int(match.group(2))
        item_name = match.group(3).strip()
        unit_price = float(match.group(5).replace(",", ""))
        net_price = float(match.group(7).replace(",", ""))
        total = float(match.group(8).replace(",", ""))

        # Find the matching detail line (closest one AFTER this line item)
        item_code = ""
        pack_size = ""
        bottle_size = ""
        match_pos = match.end()

        for detail in detail_matches:
            if detail.start() > match_pos:
                item_code = detail.group(1)
                pack_size = detail.group(2)
                bottle_size = detail.group(3)
                break

        # Skip breakage lines (qty 0)
        if delivered == 0:
            result.warnings.append(
                f"Skipped 0-delivery line: {item_name} "
                f"(ordered {ordered}, delivered {delivered})"
            )
            continue

        line = ParsedInvoiceLine(
            line_number=idx + 1,
            description=item_name,
            quantity=float(delivered),
            unit_of_measure="case" if delivered > 1 and pack_size else "bottle",
            unit_price=net_price,
            extended_price=total,
            item_code=item_code,
            pack_size=pack_size,
            bottle_size=bottle_size,
        )
        result.lines.append(line)

    if not result.lines:
        result.warnings.append("No line items could be parsed from this invoice")
        result.confidence = "low"
    elif len(result.lines) < 3:
        result.confidence = "medium"

    # Validate total
    computed_total = sum(l.extended_price for l in result.lines)
    if result.total_amount > 0 and abs(computed_total - result.total_amount) > 1.0:
        result.warnings.append(
            f"Computed total (${computed_total:.2f}) differs from "
            f"invoice total (${result.total_amount:.2f})"
        )

    return result


# ============================================================================
# BEVERAGE DISTRIBUTOR B PARSER
# ============================================================================


def _parse_beverage_distributor_b(text: str) -> ParsedInvoice:
    """Parse a second beverage distributor invoice format."""
    result = ParsedInvoice(
        vendor_name="Beverage Distributor B",
        raw_text=text,
        parse_method="pdfplumber",
    )

    # Try generic parsing since format is unknown
    return _parse_generic(text, result)


# ============================================================================
# GENERIC PARSERS
# ============================================================================


def _parse_generic_spirits(text: str, vendor_name: str = "Unknown") -> ParsedInvoice:
    """Generic parser for spirits distributor invoices."""
    result = ParsedInvoice(vendor_name=vendor_name, raw_text=text)
    return _parse_generic(text, result)


def _parse_generic_food(text: str, vendor_name: str = "Unknown") -> ParsedInvoice:
    """Generic parser for food distributor invoices."""
    result = ParsedInvoice(vendor_name=vendor_name, raw_text=text)
    return _parse_generic(text, result)


def _parse_generic(text: str, result: ParsedInvoice = None) -> ParsedInvoice:
    """
    Best-effort parser for unknown invoice formats.
    Tries to extract invoice number, date, and any tabular line items.
    """
    if result is None:
        result = ParsedInvoice(raw_text=text)

    result.confidence = "medium"
    result.parse_method = "pdfplumber_generic"

    # Try to find invoice number
    inv_patterns = [
        r'[Ii]nvoice\s*#?\s*:?\s*(\S+)',
        r'INV[\s#-]*(\S+)',
        r'[Nn]o\.?\s*:?\s*(\d+)',
    ]
    for pat in inv_patterns:
        m = re.search(pat, text)
        if m:
            result.invoice_number = m.group(1)
            break

    # Try to find date
    date_patterns = [
        r'(\d{1,2}/\d{1,2}/\d{2,4})',
        r'(\d{4}-\d{2}-\d{2})',
        r'([A-Z][a-z]+\s+\d{1,2},?\s+\d{4})',
    ]
    for pat in date_patterns:
        m = re.search(pat, text)
        if m:
            try:
                result.invoice_date = _parse_date(m.group(1))
                break
            except ValueError:
                continue

    # Try to find total
    total_patterns = [
        r'[Tt]otal\s*:?\s*\$?([\d,]+\.\d{2})',
        r'[Aa]mount\s+[Dd]ue\s*:?\s*\$?([\d,]+\.\d{2})',
        r'[Bb]alance\s+[Dd]ue\s*:?\s*\$?([\d,]+\.\d{2})',
    ]
    for pat in total_patterns:
        m = re.search(pat, text)
        if m:
            result.total_amount = float(m.group(1).replace(",", ""))
            break

    # Try to find line items: look for patterns like
    # QTY DESCRIPTION PRICE TOTAL
    line_pat = re.compile(
        r'(\d+)\s+'                    # quantity
        r'(.{10,60}?)\s+'             # description (10-60 chars)
        r'\$?([\d,]+\.\d{2})\s+'      # unit price
        r'\$?([\d,]+\.\d{2})',         # total
        re.MULTILINE
    )

    for idx, m in enumerate(line_pat.finditer(text)):
        qty = int(m.group(1))
        desc = m.group(2).strip()
        unit_price = float(m.group(3).replace(",", ""))
        total = float(m.group(4).replace(",", ""))

        # Skip if description looks like a header or total row
        if any(kw in desc.lower() for kw in
               ["total", "subtotal", "tax", "shipping", "delivery"]):
            continue

        line = ParsedInvoiceLine(
            line_number=idx + 1,
            description=desc,
            quantity=float(qty),
            unit_price=unit_price,
            extended_price=total,
        )
        result.lines.append(line)

    if not result.lines:
        result.confidence = "low"
        result.warnings.append(
            "Could not auto-parse line items. "
            "Use the review form to manually enter items, or "
            "try uploading a clearer PDF."
        )

    return result


# ============================================================================
# HELPERS
# ============================================================================


def _parse_date(date_str: str) -> date:
    """Try multiple date formats."""
    formats = [
        "%m/%d/%Y", "%m/%d/%y",
        "%Y-%m-%d",
        "%B %d, %Y", "%B %d %Y",
        "%b %d, %Y", "%b %d %Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {date_str}")
