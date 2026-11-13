
import re
from decimal import Decimal, InvalidOperation


# ==========================================
# NORMALIZATION
# ==========================================

def normalize_text(text):
    """Normalize OCR output without destroying useful separators."""

    text = text.replace("\u00a0", " ")
    text = text.replace("–", "-").replace("—", "-")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*:\s*", ": ", text)

    return text.strip()


# ==========================================
# DATE EXTRACTION
# ==========================================

DATE_PATTERN = (
    r"(\d{1,2}[-/]\d{1,2}[-/]\d{2,4}"
    r"|\d{1,2}[- ]"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    r"[- ]\d{2,4}"
    r"|\d{1,2}\s+"
    r"(?:January|February|March|April|May|June|July|August|"
    r"September|October|November|December)"
    r"\s+\d{4})"
)


def extract_date(labels, text):

    for label in labels:

        pattern = (
            rf"\b(?:{label})\b\s*[:#-]?\s*"
            rf"{DATE_PATTERN}"
        )

        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:
            return match.group(1).strip()

    return None


# ==========================================
# GENERAL FIELD EXTRACTION
# ==========================================

def find_first(patterns, text):

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:
            return match.group(1).strip()

    return None


# ==========================================
# AMOUNT EXTRACTION
# ==========================================

AMOUNT_PATTERN = (
    r"(?<![A-Z0-9])"
    r"(?:(?:INR|USD|EUR|GBP|Rs\.?|₹|\$|€|£)\s*)?"
    r"(-?\s*[\d,]+(?:\.\d{1,2})?)"
)


def parse_amount(value):

    if not value:
        return None

    try:

        value = value.replace(",", "")
        value = value.replace(" ", "")

        return float(Decimal(value))

    except (InvalidOperation, ValueError):
        return None



def find_amount(labels, text):

    for line in text.splitlines():

        line = line.strip()

        for label in labels:

            pattern = (
                rf"^\s*(?:{label})"
                rf"\s*(?:\([^)]*\))?"
                rf"\s*[:=]?\s*"
                rf"(?:\(\s*[-+]\s*\)\s*)?"
                rf"(?:INR|USD|EUR|GBP|Rs\.?|₹|\$|€|£)?\s*"
                rf"(-?[\d,]+(?:\.\d{{1,2}})?)"
                rf"\s*(?:INR|USD|EUR|GBP)?\s*$"
            )

            match = re.search(
                pattern,
                line,
                re.IGNORECASE
            )

            if match:
                return parse_amount(match.group(1))

    return None



# ==========================================
# TAX EXTRACTION
# ==========================================

def extract_tax(text):

    # Handles:
    # TAX: VAT (3.88%): 28.18 EUR
    # VAT: 28.18
    # TAX AMOUNT: 28.18

    patterns = [

        r"\bTAX\s*:\s*"
        r"(VAT|GST|IGST|CGST|SGST)"
        r"\s*(?:\([^)]*\))?\s*:\s*"
        + AMOUNT_PATTERN,

        r"\b(VAT|IGST|CGST|SGST|GST)"
        r"\s*(?:AMOUNT)?\s*[:=]\s*"
        + AMOUNT_PATTERN,

        r"\bTOTAL\s+TAX\s*[:=]?\s*"
        + AMOUNT_PATTERN,

        r"\bTAX\s+AMOUNT\s*[:=]?\s*"
        + AMOUNT_PATTERN
    ]

    for index, pattern in enumerate(patterns):

        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:

            # First two patterns have tax type in group 1.
            amount_group = 2 if index < 2 else 1

            tax_type = (
                match.group(1).upper()
                if index < 2
                else None
            )

            return (
                parse_amount(match.group(amount_group)),
                tax_type
            )

    return None, None


# ==========================================
# GSTIN EXTRACTION
# ==========================================

def extract_gstin(text):

    # Standard Indian GSTIN structure:
    # 22AAAAA0000A1Z5

    pattern = (
        r"\b\d{2}[A-Z]{5}\d{4}[A-Z]"
        r"[1-9A-Z]Z[0-9A-Z]\b"
    )

    matches = re.findall(
        pattern,
        text.upper()
    )

    return matches[0] if matches else None


# ==========================================
# CURRENCY EXTRACTION
# ==========================================

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


# ==========================================
# TAX TYPE
# ==========================================

def extract_tax_type(text, detected_type=None):

    if detected_type:
        return detected_type

    if re.search(r"\bIGST\b", text, re.IGNORECASE):
        return "IGST"

    if (
        re.search(r"\bCGST\b", text, re.IGNORECASE)
        and re.search(r"\bSGST\b", text, re.IGNORECASE)
    ):
        return "CGST + SGST"

    if re.search(r"\bVAT\b", text, re.IGNORECASE):
        return "VAT"

    if re.search(r"\bGST\b", text, re.IGNORECASE):
        return "GST"

    return None


# ==========================================
# LINE ITEM EXTRACTION
# ==========================================


def extract_line_items(text):

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    items = []

    i = 0

    while i < len(lines) - 2:

        description = lines[i].strip()
        quantity_line = lines[i + 1].strip()
        price_line = lines[i + 2].strip()

        # Skip headings and invoice summary fields
        if re.search(
            r"(?i)^(items|quantity|price|subtotal|total|tax)",
            description
        ):
            i += 1
            continue

        quantity_match = re.fullmatch(
            r"(\d+(?:\.\d+)?)",
            quantity_line
        )

        price_match = re.fullmatch(
            r"(?:\$|€|£|₹)?\s*"
            r"([\d,]+\.\d{2})"
            r"(?:\s*(?:EUR|USD|INR|GBP))?",
            price_line,
            re.IGNORECASE
        )

        if quantity_match and price_match:

            quantity = float(quantity_match.group(1))

            unit_price = parse_amount(
                price_match.group(1)
            )

            items.append({

                "description": description,

                "quantity": quantity,

                "unit_price": unit_price,

                "line_total": round(
                    quantity * unit_price,
                    2
                )

            })

            i += 3

        else:
            i += 1

    return items



# ==========================================
# VALIDATION
# ==========================================

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

    calculated = round(
        subtotal - discount + tax,
        2
    )

    difference = round(
        total - calculated,
        2
    )

    return {
        "arithmetic_check": (
            "passed" if abs(difference) <= 0.02
            else "mismatch"
        ),
        "calculated_total": calculated,
        "difference": difference
    }


# ==========================================
# MAIN EXTRACTION FUNCTION
# ==========================================

def extract_invoice_data(text):

    text = normalize_text(text)

    result = {}

    # Invoice number
    result["invoice_number"] = find_first([

        r"\bINVOICE\s*(?:NO|NUMBER|#)\s*[:#.-]?\s*"
        r"([A-Z0-9/-]+)",

        r"\bBILL\s*(?:NO|NUMBER)\s*[:#.-]?\s*"
        r"([A-Z0-9/-]+)"

    ], text)

    # Dates
    result["invoice_date"] = extract_date(
        ["invoice date", "date"],
        text
    )

    result["due_date"] = extract_date(
        ["due date", "payment due date"],
        text
    )

    # PO number
    result["po_number"] = find_first([

        r"\b(?:PURCHASE\s*ORDER|PO)"
        r"\s*(?:NO|NUMBER|#)?\s*[:#.-]?\s*"
        r"([A-Z0-9/-]+)"

    ], text)

    # GSTIN
    result["gstin"] = extract_gstin(text)

    # Financial fields
    result["subtotal"] = find_amount([
    r"SUB\s*TOTAL",
    r"TAXABLE\s*VALUE"
    ], text)
    result["discount"] = find_amount([
    r"DISCOUNT"
], text)
    result["tax_amount"], detected_tax_type = extract_tax(text)
    result["total_amount"] = find_amount([
    r"GRAND\s*TOTAL",
    r"INVOICE\s*TOTAL",
    r"TOTAL\s*AMOUNT",
    r"TOTAL"
], text)

    # Tax type
    result["tax_type"] = extract_tax_type(
        text,
        detected_tax_type
    )

    # Currency
    result["currency"] = extract_currency(text)

    # Line items
    result["line_items"] = extract_line_items(text)

    # Financial validation
    result["validation"] = validate_invoice(result)

    return result
