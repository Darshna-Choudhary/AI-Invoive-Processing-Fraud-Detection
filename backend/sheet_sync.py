import os
from datetime import datetime, date

import gspread
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_ID = os.getenv("GOOGLE_SHEET_ID")
CLIENT_FILE = os.getenv("GOOGLE_OAUTH_CLIENT_FILE", "credentials/client_secret.json")
TOKEN_FILE = os.getenv("GOOGLE_TOKEN_FILE", "credentials/token.json")

HEADERS = {
    "Invoices": [
        "Source Hash", "Invoice ID", "Batch ID", "Source File", "Status",
        "Vendor", "Vendor Tax ID", "Invoice No", "Invoice Date", "Due Date",
        "PO Number", "Bill To", "Currency", "Subtotal", "Tax", "Discount",
        "Shipping", "Total", "Payment Terms", "Confidence", "Flags",
        "Supplier Name", "Supplier Address", "Supplier Email", "Supplier Phone",
        "Supplier Website", "Customer Name", "Customer Address", "Customer Email",
        "Customer Phone", "Bank Name", "Branch Name", "Bank Account Number",
        "SWIFT Code", "Discount Rate", "Tax Rate",
    ],
    "Line Items": [
        "Source Hash", "Invoice ID", "Source File", "Invoice No", "Vendor",
        "Line #", "Description", "Qty", "Unit Price", "Tax", "Amount",
    ],
    "Needs Review": [
        "Source Hash", "Invoice ID", "Source File", "Status", "Vendor",
        "Invoice No", "Why",
    ],
}


def _absolute(path):
    return path if os.path.isabs(path) else os.path.join(BASE_DIR, path)


def get_google_credentials():
    client_path = _absolute(CLIENT_FILE)
    token_path = _absolute(TOKEN_FILE)
    if not os.path.exists(client_path):
        raise FileNotFoundError(f"Google OAuth client JSON not found: {client_path}")

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(client_path, SCOPES)
        creds = flow.run_local_server(port=0, prompt="consent")

    os.makedirs(os.path.dirname(token_path), exist_ok=True)
    with open(token_path, "w", encoding="utf-8") as token:
        token.write(creds.to_json())
    return creds


def get_spreadsheet():
    if not SPREADSHEET_ID:
        raise ValueError("GOOGLE_SHEET_ID is missing from .env")
    return gspread.authorize(get_google_credentials()).open_by_key(SPREADSHEET_ID)


def get_or_create_tab(spreadsheet, name, headers):
    try:
        ws = spreadsheet.worksheet(name)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=name, rows=1000, cols=len(headers))

    if ws.col_count < len(headers):
        ws.add_cols(len(headers) - ws.col_count)

    current = ws.row_values(1)
    if not current:
        ws.update(range_name="A1", values=[headers], value_input_option="RAW")
        ws.freeze(rows=1)
    elif current != headers:
        if len(current) <= len(headers) and current == headers[:len(current)]:
            ws.update(range_name="A1", values=[headers], value_input_option="RAW")
            ws.freeze(rows=1)
        else:
            raise ValueError(
                f"Header mismatch in '{name}'. Back up the tab and correct its "
                "header row before syncing; existing data was not cleared."
            )
    return ws


def _safe(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return str(value)
    return value


def _format_address(value):
    if not isinstance(value, dict):
        return str(value or "")
    keys = ("line1", "line2", "city", "state", "postal_code", "country")
    return ", ".join(str(value[k]).strip() for k in keys if value.get(k))


def _normalize_date(value):
    if not value:
        return ""
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")
    value = str(value).strip()
    for fmt in (
        "%Y-%m-%d", "%d-%b-%Y", "%d-%B-%Y",
        "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d",
    ):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return value


def _append_rows(ws, rows):
    if not rows:
        return
    next_row = len(ws.col_values(1)) + 1
    ws.update(
        range_name=f"A{next_row}",
        values=[[_safe(v) for v in row] for row in rows],
        value_input_option="RAW",
    )


def _delete_hash_rows(ws, source_hash):
    values = ws.col_values(1)
    matches = [
        row_number for row_number, value in enumerate(values[1:], start=2)
        if value.strip() == source_hash
    ]
    for row_number in reversed(matches):
        ws.delete_rows(row_number)


def _build_rows(result, batch_id):
    source_hash = result["source_hash"]
    data = result.get("data") or {}
    validation = data.get("validation") or {}
    flags = validation.get("issues") or []
    status = result.get("status", "failed")

    if status == "success" and (
        validation.get("arithmetic_check") == "mismatch" or flags
    ):
        status = "review"

    supplier = data.get("supplier") or {}
    customer = data.get("customer") or {}
    bank = data.get("bank_details") or {}
    vendor = data.get("vendor") or data.get("vendor_name") or supplier.get("name") or ""
    invoice_no = data.get("invoice_number") or ""
    filename = result.get("filename", "")
    invoice_id = result.get("invoice_id", "")
    total = data.get("total_amount")

    invoice_row = [
        source_hash, invoice_id, batch_id, filename, status,
        vendor, data.get("gstin") or "", invoice_no,
        _normalize_date(data.get("invoice_date")),
        _normalize_date(data.get("due_date")),
        data.get("po_number") or "",
        customer.get("name") or data.get("bill_to") or "",
        data.get("currency") or "", data.get("subtotal"), data.get("tax_amount"),
        data.get("discount"), data.get("shipping"), total,
        data.get("payment_terms") or "", data.get("confidence") or "",
        "; ".join(map(str, flags)),
        supplier.get("name") or vendor, _format_address(supplier.get("address")),
        supplier.get("email") or "", supplier.get("phone") or "",
        supplier.get("website") or "",
        customer.get("name") or "", _format_address(customer.get("address")),
        customer.get("email") or "", customer.get("phone") or "",
        bank.get("bank_name") or "", bank.get("branch_name") or "",
        bank.get("account_number") or "", bank.get("swift_code") or "",
        data.get("discount_rate"), data.get("tax_rate"),
    ]

    line_rows = []
    for index, item in enumerate(data.get("line_items") or [], start=1):
        line_rows.append([
            source_hash, invoice_id, filename, invoice_no, vendor, index,
            item.get("description") or "", item.get("quantity"),
            item.get("unit_price"), item.get("tax"),
            item.get("line_total") if item.get("line_total") is not None
            else item.get("amount"),
        ])

    review_rows = []
    if status in ("review", "failed", "pending") or flags or not invoice_no or total is None:
        reason = result.get("error") or "; ".join(map(str, flags))
        if not reason:
            reason = "Missing required fields or validation issue"
        review_rows.append([
            source_hash, invoice_id, filename, status, vendor, invoice_no, reason
        ])

    return status, invoice_row, line_rows, review_rows


def sync_batch_to_google_sheets(results, batch_id):
    spreadsheet = get_spreadsheet()
    invoice_ws = get_or_create_tab(spreadsheet, "Invoices", HEADERS["Invoices"])
    items_ws = get_or_create_tab(spreadsheet, "Line Items", HEADERS["Line Items"])
    review_ws = get_or_create_tab(spreadsheet, "Needs Review", HEADERS["Needs Review"])

    existing_values = invoice_ws.get_all_values()
    existing_by_hash = {}
    for row_number, row in enumerate(existing_values[1:], start=2):
        if row and row[0]:
            old_status = row[4].strip().lower() if len(row) > 4 else ""
            existing_by_hash[row[0].strip()] = (row_number, old_status)

    # If the same file is accidentally included twice in this batch, use one
    # result. Prefer successful extraction over pending/failed.
    priority = {"success": 0, "pending": 1, "failed": 2}
    best = {}
    for result in results:
        key = result.get("source_hash")
        if not key:
            raise ValueError(f"Missing source hash for {result.get('filename')}")
        old = best.get(key)
        if old is None or priority.get(result.get("status"), 3) < priority.get(old.get("status"), 3):
            best[key] = result

    new_invoice_rows, new_line_rows, new_review_rows = [], [], []
    inserted = updated = skipped = 0

    for source_hash, result in best.items():
        existing = existing_by_hash.get(source_hash)

        # A previously failed/pending record is eligible for a real retry.
        # Successful/review records remain protected against duplicate insertion.
        if existing and existing[1] not in ("failed", "pending"):
            skipped += 1
            continue

        status, invoice_row, line_rows, review_rows = _build_rows(result, batch_id)

        if existing:
            row_number = existing[0]
            invoice_ws.update(
                range_name=f"A{row_number}",
                values=[[_safe(v) for v in invoice_row]],
                value_input_option="RAW",
            )
            _delete_hash_rows(items_ws, source_hash)
            _delete_hash_rows(review_ws, source_hash)
            updated += 1
        else:
            new_invoice_rows.append(invoice_row)
            inserted += 1

        new_line_rows.extend(line_rows)
        new_review_rows.extend(review_rows)

    _append_rows(invoice_ws, new_invoice_rows)
    _append_rows(items_ws, new_line_rows)
    _append_rows(review_ws, new_review_rows)

    return {
        "spreadsheet_url": spreadsheet.url,
        "inserted": inserted,
        "updated": updated,
        "duplicates_skipped": skipped,
        "line_items_inserted": len(new_line_rows),
        "review_inserted": len(new_review_rows),
    }
