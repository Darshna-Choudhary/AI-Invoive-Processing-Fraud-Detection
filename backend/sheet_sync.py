
import os
import gspread

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow


# Project root
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

load_dotenv(os.path.join(BASE_DIR, ".env"))

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets"
]

SPREADSHEET_ID = os.getenv("GOOGLE_SHEET_ID")

CLIENT_FILE = os.getenv(
    "GOOGLE_OAUTH_CLIENT_FILE",
    "credentials/client_secret.json"
)

TOKEN_FILE = os.getenv(
    "GOOGLE_TOKEN_FILE",
    "credentials/token.json"
)


def absolute_path(path):
    if os.path.isabs(path):
        return path
    return os.path.join(BASE_DIR, path)


def get_google_credentials():
    client_path = absolute_path(CLIENT_FILE)
    token_path = absolute_path(TOKEN_FILE)

    if not os.path.exists(client_path):
        raise FileNotFoundError(
            f"OAuth client JSON not found: {client_path}"
        )

    creds = None

    # Reuse previously authorized credentials.
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(
            token_path, SCOPES
        )

    # Refresh expired credentials when possible.
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())

    # First-time login or unusable token.
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(
            client_path,
            SCOPES
        )

        creds = flow.run_local_server(
            port=0,
            prompt="consent"
        )

    # Save token so login is not required every time.
    os.makedirs(os.path.dirname(token_path), exist_ok=True)

    with open(token_path, "w") as token:
        token.write(creds.to_json())

    return creds


def get_spreadsheet():
    if not SPREADSHEET_ID:
        raise ValueError(
            "GOOGLE_SHEET_ID is missing from .env"
        )

    credentials = get_google_credentials()

    client = gspread.authorize(credentials)

    return client.open_by_key(SPREADSHEET_ID)


HEADERS = {
    "Invoices": [
        "Source Hash", "Invoice ID", "Batch ID", "Source File",
        "Status", "Vendor", "Vendor Tax ID", "Invoice No",
        "Invoice Date", "Due Date", "PO Number", "Bill To",
        "Currency", "Subtotal", "Tax", "Discount", "Shipping",
        "Total", "Payment Terms", "Confidence", "Flags"
    ],

    "Line Items": [
        "Source Hash", "Invoice ID", "Source File", "Invoice No",
        "Vendor", "Line #", "Description", "Qty",
        "Unit Price", "Tax", "Amount"
    ],

    "Needs Review": [
        "Source Hash", "Invoice ID", "Source File", "Status",
        "Vendor", "Invoice No", "Why"
    ]
}



def get_or_create_tab(spreadsheet, tab_name, headers):
    try:
        worksheet = spreadsheet.worksheet(tab_name)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(
            title=tab_name,
            rows=1000,
            cols=len(headers)
        )

    current_headers = worksheet.row_values(1)

    if not current_headers:
        worksheet.update(
            range_name="A1",
            values=[headers],
            value_input_option="RAW"
        )
        worksheet.freeze(rows=1)

    elif current_headers != headers:
        raise ValueError(
            f"Incorrect headers in '{tab_name}'. "
            "Please run reset_sheet_tabs.py after backing up."
        )

    return worksheet


def get_existing_hashes(worksheet):
    return set(worksheet.col_values(1)[1:])


def write_rows_at_next_position(worksheet, rows):
    if not rows:
        return

    # Column A contains the source hash for every record.
    next_row = len(worksheet.col_values(1)) + 1

    start_col = "A"
    worksheet.update(
        range_name=f"{start_col}{next_row}",
        values=rows,
        value_input_option="RAW"
    )



def sync_batch_to_google_sheets(results, batch_id):
    spreadsheet = get_spreadsheet()

    invoice_ws = get_or_create_tab(
        spreadsheet, "Invoices", HEADERS["Invoices"]
    )

    items_ws = get_or_create_tab(
        spreadsheet, "Line Items", HEADERS["Line Items"]
    )

    review_ws = get_or_create_tab(
        spreadsheet, "Needs Review", HEADERS["Needs Review"]
    )

    # Read existing invoice hashes.
    existing_hashes = get_existing_hashes(invoice_ws)

    invoice_rows = []
    item_rows = []
    review_rows = []

    skipped_duplicates = 0

    for result in results:

        source_hash = result.get("source_hash", "")

        if not source_hash:
            raise ValueError(
                f"Missing source hash: {result.get('filename')}"
            )

        # Skip previously processed files.
        if source_hash in existing_hashes:
            skipped_duplicates += 1
            continue

        data = result.get("data") or {}

        filename = result.get("filename", "")
        invoice_id = result.get("invoice_id", "")
        status = result.get("status", "failed")

        validation = data.get("validation") or {}
        flags = validation.get("issues", [])

        vendor = data.get("vendor") or data.get("vendor_name", "")
        vendor_tax_id = data.get("gstin", "")
        invoice_no = data.get("invoice_number", "")
        invoice_date = data.get("invoice_date", "")
        due_date = data.get("due_date", "")
        po_number = data.get("po_number", "")
        bill_to = data.get("bill_to", "")
        currency = data.get("currency", "")

        subtotal = data.get("subtotal")
        tax = data.get("tax_amount")
        discount = data.get("discount")
        shipping = data.get("shipping")
        total = data.get("total_amount")

        payment_terms = data.get("payment_terms", "")
        confidence = data.get("confidence", "")

        if (
            status == "success"
            and validation.get("arithmetic_check") == "mismatch"
        ):
            status = "review"

        # One row per invoice.
        invoice_rows.append([
            source_hash,
            invoice_id,
            batch_id,
            filename,
            status,
            vendor,
            vendor_tax_id,
            invoice_no,
            invoice_date,
            due_date,
            po_number,
            bill_to,
            currency,
            subtotal,
            tax,
            discount,
            shipping,
            total,
            payment_terms,
            confidence,
            "; ".join(map(str, flags))
            if isinstance(flags, list) else flags
        ])

        # One row per line item.
        for index, item in enumerate(
            data.get("line_items", []), start=1
        ):
            item_rows.append([
                source_hash,
                invoice_id,
                filename,
                invoice_no,
                vendor,
                index,
                item.get("description", ""),
                item.get("quantity"),
                item.get("unit_price"),
                item.get("tax"),
                item.get("line_total", item.get("amount"))
            ])

        # Add problematic invoices to review tab.
        if (
            status != "success"
            or flags
            or not invoice_no
            or total is None
        ):
            if isinstance(flags, list):
                reason = "; ".join(map(str, flags))
            else:
                reason = str(flags or "")

            reason = result.get("error") or reason

            if not reason:
                reason = "Missing fields or validation issue"

            review_rows.append([
                source_hash,
                invoice_id,
                filename,
                status,
                vendor,
                invoice_no,
                reason
            ])

        # Important: prevents duplicates within the same batch too.
        existing_hashes.add(source_hash)

    # Explicit vertical writes: never use append_rows here.
    write_rows_at_next_position(invoice_ws, invoice_rows)
    write_rows_at_next_position(items_ws, item_rows)
    write_rows_at_next_position(review_ws, review_rows)

    return {
        "spreadsheet_url": spreadsheet.url,
        "inserted": len(invoice_rows),
        "duplicates_skipped": skipped_duplicates,
        "line_items_inserted": len(item_rows),
        "review_inserted": len(review_rows)
    }
