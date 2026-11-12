import re
from datetime import datetime

def find_match(pattern, text, group=1, flags=re.IGNORECASE):
    match = re.search(pattern, text, flags)
    return match.group(group).strip() if match else None

def parse_date(value):
    if not value:
        return None
    for fmt in ("%d-%b-%Y", "%d-%B-%Y",
                "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), fmt).date().isoformat()
        except ValueError:
            continue

    return None


def parse_number(value):
    if not value:
        return None
    value = value.replace(",", "").strip()

    try:
        return float(value)
    except ValueError:
        return None


def extract_invoice_fields(cleaned_text):
    lines = cleaned_text.splitlines()
    invoice = {
        "invoice_number": find_match(
            r"\bINVOICE\s+ID\s*:?\s*([A-Z0-9/-]+)",
            cleaned_text
        ),
        "invoice_date": parse_date(
            find_match(
                r"\bDate\s*:\s*(\d{1,2}-[A-Za-z]+-\d{4})",
                cleaned_text
            )
        ),
        "po_number": find_match(
            r"\bPO\s+Number\s*:?\s*([A-Z0-9/-]+)",
            cleaned_text
        ),
        "due_date": parse_date(
            find_match(
                r"\bDue\s+Date\s*:?\s*(\d{1,2}-[A-Za-z]+-\d{4})",
                cleaned_text
            )
        ),

        "vendor_name": None,
        "vendor_address": None,
        "vendor_phone": None,
        "vendor_email": None,
        "vendor_website": None,

        "customer_name": None,
        "customer_address": None,
        "customer_phone": None,
        "customer_email": None,
        "customer_website": None,

        "subtotal": None,
        "tax_type": None,
        "tax_rate": None,
        "tax_amount": None,
        "total_amount": None,
        "currency": None,

        "payment_method": None,
        "payment_terms": None,

        "items": [],
        "validation_warnings": []
    }

    # Vendor name:
    # For this layout, use the first meaningful line after INVOICE.
    try:
        invoice_index = next(
            i for i, line in enumerate(lines)
            if line.strip().upper() == "INVOICE"
        )

        for line in lines[invoice_index + 1:]:
            if (
                not line
                or len(line.strip()) <= 1
                or re.search(
                    r"\b(Date|Invoice ID|PO Number|Bill To)\b",
                    line,
                    re.IGNORECASE
                )
            ):
                continue

            invoice["vendor_name"] = line.strip()
            break

    except StopIteration:
        invoice["validation_warnings"].append(
            "Invoice heading not found"
        )

    # Customer / Bill To section
    try:
        start = next(
            i for i, line in enumerate(lines)
            if re.match(r"^\s*BILL\s+TO\s*:?", line, re.I)
        )

        end = next(
            (
                i for i in range(start + 1, len(lines))
                if re.match(r"^\s*Due\s+Date", lines[i], re.I)
            ),
            len(lines)
        )

        customer_lines = lines[start + 1:end]

        if customer_lines:
            invoice["customer_name"] = customer_lines[0]

        address_lines = []

        for line in customer_lines[1:]:
            if re.match(r"^Tel\s*:", line, re.I):
                invoice["customer_phone"] = line.split(":", 1)[1].strip()

            elif re.match(r"^Email\s*:", line, re.I):
                invoice["customer_email"] = line.split(":", 1)[1].strip()

            elif re.match(r"^Site\s*:", line, re.I):
                invoice["customer_website"] = line.split(":", 1)[1].strip()

            else:
                address_lines.append(line)

        invoice["customer_address"] = (
            ", ".join(address_lines) or None
        )

    except StopIteration:
        invoice["validation_warnings"].append(
            "Bill To section not found"
        )

    # Tax details
    tax_match = re.search(
        r"\bTAX\s*:\s*([A-Za-z]+)"
        r"\s*\(\s*([\d.]+)\s*%\s*\)"
        r"\s*:\s*([\d,.]+)\s*([$€£₹])?",
        cleaned_text,
        re.I
    )

    if tax_match:
        invoice["tax_type"] = tax_match.group(1)
        invoice["tax_rate"] = float(tax_match.group(2))
        invoice["tax_amount"] = parse_number(tax_match.group(3))
        invoice["currency"] = tax_match.group(4)

    # Total amount
    total_match = re.search(
        r"\bTOTAL\s*:\s*([$€£₹])?\s*([\d,]+\.\d{2})",
        cleaned_text,
        re.I
    )

    if total_match:
        invoice["total_amount"] = parse_number(total_match.group(2))

        if total_match.group(1):
            invoice["currency"] = (
                invoice["currency"] or total_match.group(1)
            )

    # Payment note
    note_match = re.search(
        r"\bNote\s*:\s*(.+)",
        cleaned_text,
        re.I
    )

    if note_match:
        note = note_match.group(1).strip()
        invoice["payment_terms"] = note

        if re.search(r"\bcash\b", note, re.I):
            invoice["payment_method"] = "Cash"

    # Product table
    # This parser supports both rows WITH and WITHOUT a product code,
    # provided each row has quantity, description, unit price and amount.

    try:
        table_start = next(
            i for i, line in enumerate(lines)
            if re.match(r"^\s*Qty\s*$", line, re.I)
        )

        table_end = next(
            (
                i for i in range(table_start + 1, len(lines))
                if re.match(r"^\s*(Note\s*:|TAX\s*:)", lines[i], re.I)
            ),
            len(lines)
        )

        table_lines = lines[table_start + 1:table_end]
        i = 0

        while i < len(table_lines):
            quantity = parse_number(table_lines[i])

            if quantity is None:
                i += 1
                continue

            i += 1
            product_code = None

            # A product code is typically an integer string,
            # whereas quantity and monetary fields are decimals.
            if i < len(table_lines) and re.fullmatch(
                r"\d{3,}", table_lines[i].strip()
            ):
                product_code = table_lines[i].strip()
                i += 1

            if i + 2 >= len(table_lines):
                invoice["validation_warnings"].append(
                    "Incomplete product row near table end"
                )
                break

            description = table_lines[i].strip()
            unit_price = parse_number(table_lines[i + 1])
            amount = parse_number(table_lines[i + 2])

            # Don't accept an incomplete or misaligned row.
            if unit_price is None or amount is None:
                invoice["validation_warnings"].append(
                    f"Could not parse product row: {description}"
                )
                continue

            invoice["items"].append({
                "product_code": product_code,
                "description": description or None,
                "quantity": quantity,
                "unit_price": unit_price,
                "amount": amount
            })

            i += 3

    except StopIteration:
        invoice["validation_warnings"].append(
            "Product table header not found"
        )

    # Arithmetic checks: flag discrepancies; never alter source values.
    items_sum = round(
        sum(item["amount"] for item in invoice["items"]), 2
    )

    if invoice["items"] and invoice["total_amount"] is not None:
        expected_total = round(
            items_sum + (invoice["tax_amount"] or 0), 2
        )

        if abs(expected_total - invoice["total_amount"]) > 0.02:
            invoice["validation_warnings"].append(
                f"Line item sum plus tax is {expected_total:.2f}, "
                f"but invoice total is {invoice['total_amount']:.2f}"
            )

    return invoice
