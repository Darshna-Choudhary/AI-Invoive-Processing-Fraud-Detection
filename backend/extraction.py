import re
from decimal import Decimal, InvalidOperation

# --------------------------------------------------
# NORMALIZATION
# --------------------------------------------------

def normalize_text(text):
    text = (text or "").replace("\u00a0", " ")
    text = text.replace("–", "-").replace("—", "-")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*:\s*", ": ", text)
    text = re.sub(r"(?<=\$)\s+", "", text)
    return text.strip()


def parse_amount(value):
    if value is None:
        return None

    value = str(value)
    value = value.replace(",", "").replace(" ", "")
    value = value.replace("$", "").replace("€", "")
    value = value.replace("£", "").replace("₹", "")

    try:
        return float(Decimal(value))
    except (InvalidOperation, ValueError):
        return None


DATE_PATTERN = (
    r"\d{1,2}[-/]\d{1,2}[-/]\d{2,4}"
    r"|\d{1,2}[- ](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|"
    r"Sep|Oct|Nov|Dec)[- ]\d{2,4}"
    r"|\d{1,2}\s+(?:January|February|March|April|May|"
    r"June|July|August|September|October|November|"
    r"December)\s+\d{4}"
)


def extract_date(labels, text):
    for line in text.splitlines():
        line = line.strip()

        for label in labels:
            match = re.search(
                rf"^(?:{label})\s*[:#-]?\s*({DATE_PATTERN})",
                line,
                re.IGNORECASE
            )

            if match:
                return match.group(1).strip()

    return None


def find_first(patterns, text):
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


# --------------------------------------------------
# FINANCIAL EXTRACTION
# --------------------------------------------------

def find_amount(labels, text):
    currency = r"(?:INR|USD|EUR|GBP|Rs\.?|₹|\$|€|£)"

    for line in text.splitlines():
        line = line.strip()

        for label in labels:
            pattern = (
                rf"^\s*(?:{label})"
                rf"\s*(?:\([^)]*\))?"
                rf"\s*[:=]?\s*"
                rf"(?:\(\s*[-+]?\s*\)\s*)?"
                rf"(?:{currency}\s*)?"
                rf"(-?[\d,]+(?:\.\d{{1,2}})?)"
                rf"\s*(?:{currency})?\s*$"
            )

            match = re.search(pattern, line, re.IGNORECASE)

            if match:
                return parse_amount(match.group(1))

    return None


def extract_rate_and_amount(text, label):
    """
    Handles examples:
    TAX:VAT (6.71%): 34.66 USD
    DISCOUNT(3.42%): (-) 17.66
    """

    pattern = (
        rf"\b{label}\b"
        rf"\s*:?\s*"
        rf"(?P<type>VAT|GST|IGST|CGST|SGST)?"
        rf"\s*\(?\s*(?P<rate>\d+(?:\.\d+)?)\s*%\s*\)?"
        rf"\s*:?\s*"
        rf"(?:\(\s*[-+]\s*\)\s*)?"
        rf"(?:INR|USD|EUR|GBP|Rs\.?|₹|\$|€|£)?\s*"
        rf"(?P<amount>[\d,]+(?:\.\d{{1,2}})?)"
    )

    match = re.search(pattern, text, re.IGNORECASE)

    if not match:
        return None, None, None

    return (
        match.group("type").upper()
        if match.group("type") else None,
        float(match.group("rate")),
        parse_amount(match.group("amount"))
    )


def extract_tax(text):
    tax_type, tax_rate, tax_amount = extract_rate_and_amount(
        text, "TAX"
    )

    if tax_amount is None:
        tax_type, tax_rate, tax_amount = extract_rate_and_amount(
            text, "VAT|GST|IGST|CGST|SGST"
        )

    if tax_amount is None:
        tax_amount = find_amount(
            [r"TOTAL\s+TAX", r"TAX\s+AMOUNT"],
            text
        )

    return tax_type, tax_rate, tax_amount


def extract_currency(text):
    currencies = {
        "EUR": r"\bEUR\b|€",
        "USD": r"\bUSD\b|\$",
        "INR": r"\bINR\b|\bRs\.?\b|₹",
        "GBP": r"\bGBP\b|£"
    }

    for currency, pattern in currencies.items():
        if re.search(pattern, text, re.IGNORECASE):
            return currency

    return None


# --------------------------------------------------
# LAYOUT UTILITIES
# --------------------------------------------------

def valid_blocks(layout):
    blocks = []

    for page in layout or []:
        for block in page.get("blocks", []):
            bbox = block.get("bbox")

            if not bbox or len(bbox) != 4:
                continue

            try:
                x1, y1, x2, y2 = map(float, bbox)
            except (TypeError, ValueError):
                continue

            blocks.append({
                "text": str(block.get("text", "")).strip(),
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
                "xc": (x1 + x2) / 2,
                "yc": (y1 + y2) / 2,
                "height": max(1, y2 - y1),
                "page_number": page.get("page_number", 1),
                "page_width": page.get("width", 0),
                "page_height": page.get("height", 0),
                "confidence": block.get("confidence")
            })

    return blocks


def group_visual_rows(blocks):
    """Group OCR detections sharing approximately the same baseline."""

    if not blocks:
        return []

    ordered = sorted(blocks, key=lambda b: (b["yc"], b["x1"]))

    heights = sorted(b["height"] for b in ordered)
    median_height = heights[len(heights) // 2]

    tolerance = max(5, median_height * 0.65)

    rows = []

    for block in ordered:
        target = None

        for row in rows:
            if abs(row["yc"] - block["yc"]) <= tolerance:
                target = row
                break

        if target is None:
            rows.append({
                "yc": block["yc"],
                "blocks": [block]
            })
        else:
            target["blocks"].append(block)
            target["yc"] = sum(
                b["yc"] for b in target["blocks"]
            ) / len(target["blocks"])

    for row in rows:
        row["blocks"].sort(key=lambda b: b["x1"])
        row["text"] = " ".join(
            b["text"] for b in row["blocks"]
        )

    return sorted(rows, key=lambda row: row["yc"])


# --------------------------------------------------
# PARTY / ADDRESS EXTRACTION
# --------------------------------------------------

def parse_address_line(value):
    result = {
        "line1": value or None,
        "city": None,
        "state": None,
        "postal_code": None,
        "country": None
    }

    if not value:
        return result

    # Example: Markville, AK 58294 US
    match = re.search(
        r"(.+?),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)"
        r"\s+([A-Z]{2,3})$",
        value.strip()
    )

    if match:
        result.update({
            "line1": None,
            "city": match.group(1).strip(),
            "state": match.group(2),
            "postal_code": match.group(3),
            "country": match.group(4)
        })

    return result


def extract_contact_fields(text):
    email = re.findall(
        r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        text,
        re.IGNORECASE
    )

    website = re.findall(
        r"(?:https?://)?(?:www\.)?[A-Z0-9.-]+\."
        r"(?:com|org|net|biz|in|co)\b",
        text,
        re.IGNORECASE
    )

    phone = re.findall(
        r"(?:\+?\(?\d{1,4}\)?[\s.-]*)?"
        r"\d{2,4}[\s.-]*\d{3,5}[\s.-]*\d{3,5}",
        text
    )

    return {
        "emails": list(dict.fromkeys(email)),
        "website": website[0] if website else None,
        "phone": phone[0] if phone else None
    }



def extract_party_blocks(blocks, full_text):
    empty_address = {
        "line1": None,
        "city": None,
        "state": None,
        "postal_code": None,
        "country": None
    }

    supplier = {
        "name": None,
        "address": empty_address.copy(),
        "email": None,
        "phone": None,
        "website": None
    }

    customer = {
        "name": None,
        "address": empty_address.copy(),
        "email": None,
        "phone": None
    }

    if not blocks:
        return supplier, customer

    # Find the label that marks the beginning of the customer column.
    anchor_pattern = (
        r"\b(?:bill\s*to|buyer|customer|sold\s*to)\b"
    )

    anchor = next(
        (
            b for b in blocks
            if re.search(anchor_pattern, b["text"], re.I)
        ),
        None
    )

    if anchor is None:
        return supplier, customer

    page_number = anchor["page_number"]

    page_blocks = [
        b for b in blocks
        if b["page_number"] == page_number
    ]

    page_width = anchor.get("page_width") or max(
        b["x2"] for b in page_blocks
    )

    page_height = anchor.get("page_height") or max(
        b["y2"] for b in page_blocks
    )

    # Keep the top invoice header, where supplier/customer details live.
    top_blocks = [
        b for b in page_blocks
        if b["yc"] < page_height * 0.45
    ]

    # The customer label establishes the left/right column boundary.
    split_x = anchor["x1"]

    supplier_blocks = sorted(
        [
            b for b in top_blocks
            if b["xc"] < split_x
        ],
        key=lambda b: (b["yc"], b["x1"])
    )

    customer_blocks = sorted(
        [
            b for b in top_blocks
            if b["xc"] >= split_x
        ],
        key=lambda b: (b["yc"], b["x1"])
    )

    supplier_lines = [
    row["text"].strip()
    for row in group_visual_rows(supplier_blocks)
    if row["text"].strip()
    ]
    customer_lines = [
    row["text"].strip()
    for row in group_visual_rows(customer_blocks)
    if row["text"].strip()
    ]

    def clean_label(line, labels):
        for label in labels:
            line = re.sub(
                rf"^\s*{label}\s*[:#-]?\s*",
                "",
                line,
                flags=re.I
            )
        return line.strip()

    def parse_column_address(lines, supplier_side=False):
        address = empty_address.copy()

        if supplier_side:
            start_index = next(
                (
                    i for i, line in enumerate(lines)
                    if re.search(r"\bAddress\s*:", line, re.I)
                ),
                None
            )

            if start_index is None:
                return address

            first_line = clean_label(
                lines[start_index],
                [r"Address"]
            )

            following_lines = lines[start_index + 1:]

        else:
            # Customer address generally starts immediately after
            # the Buyer / Bill To name.
            anchor_index = next(
                (
                    i for i, line in enumerate(lines)
                    if re.search(anchor_pattern, line, re.I)
                ),
                None
            )

            if anchor_index is None:
                return address

            first_line = None
            following_lines = lines[anchor_index + 1:]

        candidates = []

        if first_line:
            candidates.append(first_line)

        for line in following_lines:
            if re.search(
                r"\b(email|e-mail|tel|telephone|phone|site|website|"
                r"gstin|tax id|vat|buyer|bill\s*to|customer|sold\s*to)\b",
                line,
                re.I
            ):
                break

            if re.search(r"@", line):
                break

            if re.search(
                r"https?://|www\.",
                line,
                re.I
            ):
                break

            if line.strip():
                candidates.append(line.strip())

            if len(candidates) >= 3:
                break

        if candidates:
            address["line1"] = candidates[0]

        # Identify the city/state/postal/country line.
        for line in candidates:
            parsed = parse_address_line(line)

            if parsed["city"]:
                address.update(parsed)

                if len(candidates) > 1:
                    address["line1"] = candidates[0]

                break

        return address

    # Supplier details.
    supplier["address"] = parse_column_address(
        supplier_lines,
        supplier_side=True
    )

    # Supplier name is deliberately not guessed from a logo.
    # Extract contacts from the supplier's own column.
    supplier_contact = extract_contact_fields(
        "\n".join(supplier_lines)
    )

    supplier["email"] = (
        supplier_contact["emails"][0]
        if supplier_contact["emails"] else None
    )
    supplier["phone"] = supplier_contact["phone"]
    supplier["website"] = supplier_contact["website"]

    # Customer name from Buyer / Bill To / Customer / Sold To.
    for line in customer_lines:
        match = re.search(
            r"\b(?:Bill\s*To|Buyer|Customer|Sold\s*To)"
            r"\s*[:#-]\s*(.+)$",
            line,
            re.I
        )

        if match:
            customer["name"] = match.group(1).strip()
            break

    customer["address"] = parse_column_address(
        customer_lines,
        supplier_side=False
    )

    customer_contact = extract_contact_fields(
        "\n".join(customer_lines)
    )

    customer["email"] = (
        customer_contact["emails"][0]
        if customer_contact["emails"] else None
    )
    customer["phone"] = customer_contact["phone"]

    return supplier, customer


# --------------------------------------------------
# BANK DETAILS
# --------------------------------------------------

def extract_bank_details(text):
    def field(pattern):
        return find_first([pattern], text)

    return {
        "bank_name": field(
            r"\bBank\s*Name\s*:?\s*([^\n]+)"
        ),
        "branch_name": field(
            r"\bBranch\s*Name\s*:?\s*([^\n]+)"
        ),
        "account_number": field(
            r"\bBank\s*Account\s*Number\s*:?\s*([A-Z0-9-]+)"
        ),
        "swift_code": field(
            r"\bBank\s*Swift\s*Code\s*:?\s*([A-Z0-9]+)"
        )
    }


# --------------------------------------------------
# GSTIN
# --------------------------------------------------

def extract_gstin(text):
    pattern = (
        r"\b\d{2}[A-Z]{5}\d{4}[A-Z]"
        r"[1-9A-Z]Z[0-9A-Z]\b"
    )

    matches = re.findall(pattern, text.upper())

    return matches[0] if matches else None


# --------------------------------------------------
# LINE ITEMS
# --------------------------------------------------

def extract_line_items_from_layout(blocks):
    """
    Detect table columns from ITEMS / QUANTITY / PRICE headers.
    Group cells by vertical position.
    """

    if not blocks:
        return []

    rows = group_visual_rows(blocks)

    header_row = next(
        (
            row for row in rows
            if re.search(r"\bITEMS?\b", row["text"], re.I)
            and re.search(r"\bQUANTITY\b", row["text"], re.I)
            and re.search(r"\bPRICE\b", row["text"], re.I)
        ),
        None
    )

    if not header_row:
        return []

    headers = header_row["blocks"]

    desc_header = next(
        b for b in headers
        if re.search(r"\bITEMS?\b", b["text"], re.I)
    )
    qty_header = next(
        b for b in headers
        if re.search(r"\bQUANTITY\b", b["text"], re.I)
    )
    price_header = next(
        b for b in headers
        if re.search(r"\bPRICE\b", b["text"], re.I)
    )

    desc_qty_boundary = (
        desc_header["xc"] + qty_header["xc"]
    ) / 2

    qty_price_boundary = (
        qty_header["xc"] + price_header["xc"]
    ) / 2

    table_page = desc_header["page_number"]

    page_blocks = [
        b for b in blocks
        if b["page_number"] == table_page
    ]

    table_rows = group_visual_rows(page_blocks)

    items = []

    for row in table_rows:
        if row["yc"] <= header_row["yc"]:
            continue

        if re.search(
            r"\b(SUB\s*TOTAL|DISCOUNT|TAX|GRAND\s*TOTAL|TOTAL)\b",
            row["text"],
            re.I
        ):
            break

        description_parts = []
        quantity = None
        price = None

        for block in row["blocks"]:
            text = block["text"].strip()
            x = block["xc"]

            if x < desc_qty_boundary:
                description_parts.append(text)

            elif x < qty_price_boundary:
                match = re.search(
                    r"\d+(?:\.\d+)?",
                    text
                )
                if match:
                    quantity = float(match.group())

            else:
                match = re.search(
                    r"[\d,]+\.\d{2}",
                    text.replace("$", "").replace(" ", "")
                )
                if match:
                    price = parse_amount(match.group())

        description = " ".join(description_parts).strip()

        if description and quantity is not None and price is not None:
            items.append({
                "description": description,
                "quantity": quantity,
                "unit_price": price,
                "line_total": round(quantity * price, 2)
            })

    return items


def extract_line_items_from_text(text):
    """Fallback for documents where OCR coordinates are unavailable."""

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    items = []

    for i in range(len(lines) - 2):
        description = lines[i]
        quantity_line = lines[i + 1]
        price_line = lines[i + 2]

        if re.search(
            r"^(ITEMS?|QUANTITY|PRICE|SUB\s*TOTAL|TOTAL|TAX)",
            description,
            re.I
        ):
            continue

        quantity_match = re.fullmatch(
            r"\d+(?:\.\d+)?",
            quantity_line
        )

        price_match = re.fullmatch(
            r"(?:\$|€|£|₹)?\s*([\d,]+\.\d{2})",
            price_line.replace("*", "")
        )

        if quantity_match and price_match:
            quantity = float(quantity_match.group())
            price = parse_amount(price_match.group(1))

            items.append({
                "description": description,
                "quantity": quantity,
                "unit_price": price,
                "line_total": round(quantity * price, 2)
            })

    return items


# --------------------------------------------------
# VALIDATION
# --------------------------------------------------

def validate_invoice(data):
    subtotal = data.get("subtotal")
    discount = data.get("discount") or 0
    tax = data.get("tax_amount") or 0
    total = data.get("total_amount")

    if subtotal is None or total is None:
        return {
            "arithmetic_check": "not_verifiable",
            "calculated_total": None,
            "difference": None
        }

    calculated = round(subtotal - discount + tax, 2)
    difference = round(total - calculated, 2)

    return {
        "arithmetic_check": (
            "passed" if abs(difference) <= 0.02
            else "mismatch"
        ),
        "calculated_total": calculated,
        "difference": difference
    }


# --------------------------------------------------
# MAIN EXTRACTION
# --------------------------------------------------

def extract_invoice_data(text, layout=None):
    text = normalize_text(text)

    result = {}

    result["invoice_number"] = find_first([
        r"\bINVOICE\s*(?:NO|NUMBER|#)\s*[:#.-]?\s*([A-Z0-9/-]+)",
        r"\bBILL\s*(?:NO|NUMBER)\s*[:#.-]?\s*([A-Z0-9/-]+)"
    ], text)

    result["invoice_date"] = extract_date(
        ["invoice date", "date"], text
    )

    result["due_date"] = extract_date(
        ["due date", "payment due date"], text
    )

    result["po_number"] = find_first([
        r"\b(?:PURCHASE\s*ORDER|PO)\s*"
        r"(?:NO|NUMBER|#)?\s*[:#.-]?\s*([A-Z0-9/-]+)"
    ], text)

    result["subtotal"] = find_amount(
        [r"SUB\s*TOTAL", r"TAXABLE\s*VALUE"],
        text
    )

    discount_type, discount_rate, discount_amount = (
        extract_rate_and_amount(text, "DISCOUNT")
    )

    if discount_amount is None:
        discount_amount = find_amount([r"DISCOUNT"], text)

    result["discount"] = discount_amount
    result["discount_rate"] = discount_rate

    tax_type, tax_rate, tax_amount = extract_tax(text)

    result["tax_type"] = tax_type or (
        "VAT" if re.search(r"\bVAT\b", text, re.I)
        else "GST" if re.search(r"\bGST\b", text, re.I)
        else None
    )
    result["tax_rate"] = tax_rate
    result["tax_amount"] = tax_amount

    result["total_amount"] = find_amount([
        r"GRAND\s*TOTAL",
        r"INVOICE\s*TOTAL",
        r"TOTAL\s*AMOUNT",
        r"TOTAL"
    ], text)

    result["currency"] = extract_currency(text)
    result["gstin"] = extract_gstin(text)

    blocks = valid_blocks(layout)

    supplier, customer = extract_party_blocks(
        blocks,
        text
    )

    result["supplier"] = supplier
    result["customer"] = customer
    result["bank_details"] = extract_bank_details(text)

    layout_items = extract_line_items_from_layout(blocks)

    result["line_items"] = (
        layout_items
        if layout_items
        else extract_line_items_from_text(text)
    )

    result["validation"] = validate_invoice(result)

    return result
