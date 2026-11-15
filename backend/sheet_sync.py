import os
import gspread
from datetime import datetime, date
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

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


# --------------------------------------------------
# GOOGLE AUTHENTICATION
# --------------------------------------------------

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
            token_path,
            SCOPES
        )

    # Refresh expired credentials.
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())

    # First-time authorization.
    if not creds or not creds.valid:

        flow = InstalledAppFlow.from_client_secrets_file(
            client_path,
            SCOPES
        )

        creds = flow.run_local_server(
            port=0,
            prompt="consent"
        )

    os.makedirs(
        os.path.dirname(token_path),
        exist_ok=True
    )

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


# --------------------------------------------------
# SHEET HEADERS
# --------------------------------------------------

HEADERS = {

    "Invoices": [
        # Existing invoice fields
        "Source Hash",
        "Invoice ID",
        "Batch ID",
        "Source File",
        "Status",
        "Vendor",
        "Vendor Tax ID",
        "Invoice No",
        "Invoice Date",
        "Due Date",
        "PO Number",
        "Bill To",
        "Currency",
        "Subtotal",
        "Tax",
        "Discount",
        "Shipping",
        "Total",
        "Payment Terms",
        "Confidence",
        "Flags",

        # Supplier information
        "Supplier Name",
        "Supplier Address",
        "Supplier Email",
        "Supplier Phone",
        "Supplier Website",

        # Customer information
        "Customer Name",
        "Customer Address",
        "Customer Email",
        "Customer Phone",

        # Bank information
        "Bank Name",
        "Branch Name",
        "Bank Account Number",
        "SWIFT Code",

        # Tax and discount rates
        "Discount Rate",
        "Tax Rate"
    ],

    "Line Items": [
        "Source Hash",
        "Invoice ID",
        "Source File",
        "Invoice No",
        "Vendor",
        "Line #",
        "Description",
        "Qty",
        "Unit Price",
        "Tax",
        "Amount"
    ],

    "Needs Review": [
        "Source Hash",
        "Invoice ID",
        "Source File",
        "Status",
        "Vendor",
        "Invoice No",
        "Why"
    ]
}


# --------------------------------------------------
# WORKSHEET MANAGEMENT
# --------------------------------------------------

def get_or_create_tab(spreadsheet, tab_name, headers):

    try:
        worksheet = spreadsheet.worksheet(tab_name)

    except gspread.WorksheetNotFound:

        worksheet = spreadsheet.add_worksheet(
            title=tab_name,
            rows=1000,
            cols=len(headers)
        )

    # Ensure enough columns exist.
    if worksheet.col_count < len(headers):
        worksheet.add_cols(
            len(headers) - worksheet.col_count
        )

    current_headers = worksheet.row_values(1)

    if not current_headers:

        worksheet.update(
            range_name="A1",
            values=[headers],
            value_input_option="RAW"
        )

        worksheet.freeze(rows=1)

    elif current_headers == headers:
        pass

    elif (
        len(current_headers) < len(headers)
        and current_headers == headers[:len(current_headers)]
    ):
        # Safe header extension: preserves existing records.
        worksheet.update(
            range_name="A1",
            values=[headers],
            value_input_option="RAW"
        )

        worksheet.freeze(rows=1)

    else:
        raise ValueError(
            f"Header mismatch in '{tab_name}'. "
            "Back up the tab and restore the expected header order "
            "before syncing. Existing data has not been cleared."
        )

    return worksheet


# --------------------------------------------------
# DATA FORMATTING
# --------------------------------------------------

def safe_value(value):

    if value is None:
        return ""

    if isinstance(value, (dict, list)):
        return str(value)

    return value


def format_address(address):

    if not isinstance(address, dict):
        return str(address or "")

    # Keep address components in a consistent order.
    keys = [
        "line1",
        "line2",
        "city",
        "state",
        "postal_code",
        "country"
    ]

    parts = [
        str(address[key]).strip()
        for key in keys
        if address.get(key)
    ]

    return ", ".join(parts)


def get_existing_hashes(worksheet):

    return set(
        value.strip()
        for value in worksheet.col_values(1)[1:]
        if value.strip()
    )


def write_rows_at_next_position(worksheet, rows):

    if not rows:
        return

    # Column A contains Source Hash in every data tab.
    next_row = len(worksheet.col_values(1)) + 1

    worksheet.update(
        range_name=f"A{next_row}",
        values=[
            [safe_value(value) for value in row]
            for row in rows
        ],
        value_input_option="RAW"
    )


def normalize_date(value):
    if not value:
        return ""

    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")

    value = str(value).strip()

    formats = [
        "%Y-%m-%d",
        "%d-%b-%Y",
        "%d-%B-%Y",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%d-%m-%Y",
        "%Y/%m/%d",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    return value

# --------------------------------------------------
# GOOGLE SHEETS SYNCHRONIZATION
# --------------------------------------------------

def sync_batch_to_google_sheets(results, batch_id):

    spreadsheet = get_spreadsheet()

    invoice_ws = get_or_create_tab(
        spreadsheet,
        "Invoices",
        HEADERS["Invoices"]
    )

    items_ws = get_or_create_tab(
        spreadsheet,
        "Line Items",
        HEADERS["Line Items"]
    )

    review_ws = get_or_create_tab(
        spreadsheet,
        "Needs Review",
        HEADERS["Needs Review"]
    )

    # Existing hashes prevent re-uploading the same file.
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

        # Skip duplicates from previous runs and this batch.
        if source_hash in existing_hashes:
            skipped_duplicates += 1
            continue

        data = result.get("data") or {}

        filename = result.get("filename", "")
        invoice_id = result.get("invoice_id", "")
        status = result.get("status", "failed")

        # --------------------------------------------------
        # EXISTING FIELDS
        # --------------------------------------------------

        validation = data.get("validation") or {}
        flags = validation.get("issues", [])

        vendor = (
            data.get("vendor")
            or data.get("vendor_name")
            or (data.get("supplier") or {}).get("name")
            or ""
        )

        vendor_tax_id = data.get("gstin") or ""
        invoice_no = data.get("invoice_number") or ""
        invoice_date = normalize_date(data.get("invoice_date"))
        due_date = normalize_date(data.get("due_date"))
        po_number = data.get("po_number") or ""

        currency = data.get("currency") or ""
        subtotal = data.get("subtotal")
        tax = data.get("tax_amount")
        discount = data.get("discount")
        shipping = data.get("shipping")
        total = data.get("total_amount")
        if total is None:
            calculated_total = data.get("validation", {}).get("calculated_total")
        if calculated_total is not None:
            total = calculated_total
        elif data.get("subtotal") is not None:
            subtotal_value = float(data["subtotal"])
            discount_value = float(data.get("discount") or 0)
            tax_value = float(data.get("tax_amount") or 0)
            shipping_value = float(data.get("shipping") or 0)
            total = round(
            subtotal_value - discount_value
            + tax_value + shipping_value,
            2
        )

        payment_terms = data.get("payment_terms") or ""
        confidence = data.get("confidence") or ""

        # --------------------------------------------------
        # NEW NESTED FIELDS
        # --------------------------------------------------

        supplier = data.get("supplier") or {}
        customer = data.get("customer") or {}
        bank = data.get("bank_details") or {}

        supplier_address = format_address(
            supplier.get("address")
        )

        customer_address = format_address(
            customer.get("address")
        )

        supplier_name = supplier.get("name") or vendor

        supplier_email = supplier.get("email") or ""
        supplier_phone = supplier.get("phone") or ""
        supplier_website = supplier.get("website") or ""

        customer_name = customer.get("name") or ""
        customer_email = customer.get("email") or ""
        customer_phone = customer.get("phone") or ""

        bank_name = bank.get("bank_name") or ""
        branch_name = bank.get("branch_name") or ""
        bank_account = bank.get("account_number") or ""
        swift_code = bank.get("swift_code") or ""

        discount_rate = data.get("discount_rate")
        tax_rate = data.get("tax_rate")

        # --------------------------------------------------
        # STATUS AND VALIDATION
        # --------------------------------------------------

        if (
            status == "success"
            and validation.get("arithmetic_check") == "mismatch"
        ):
            status = "review"

        flags_text = (
            "; ".join(map(str, flags))
            if isinstance(flags, list)
            else str(flags or "")
        )

        # --------------------------------------------------
        # ONE ROW PER INVOICE
        # --------------------------------------------------

        invoice_rows.append([

            # Existing 21 fields
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
            customer_name or "",
            currency,
            subtotal,
            tax,
            discount,
            shipping,
            total,
            payment_terms,
            confidence,
            flags_text,

            # Supplier
            supplier_name,
            supplier_address,
            supplier_email,
            supplier_phone,
            supplier_website,

            # Customer
            customer_name,
            customer_address,
            customer_email,
            customer_phone,

            # Bank
            bank_name,
            branch_name,
            bank_account,
            swift_code,

            # Rates
            discount_rate,
            tax_rate
        ])

        # --------------------------------------------------
        # ONE ROW PER LINE ITEM
        # --------------------------------------------------

        for index, item in enumerate(
            data.get("line_items", []),
            start=1
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
                item.get(
                    "line_total",
                    item.get("amount")
                )
            ])

        # --------------------------------------------------
        # NEEDS REVIEW
        # --------------------------------------------------

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
                reason = (
                    "Missing fields or validation issue"
                )

            review_rows.append([

                source_hash,
                invoice_id,
                filename,
                status,
                vendor,
                invoice_no,
                reason
            ])

        # Prevent duplicates within the same batch.
        existing_hashes.add(source_hash)

    # --------------------------------------------------
    # WRITE VERTICALLY
    # --------------------------------------------------

    write_rows_at_next_position(
        invoice_ws,
        invoice_rows
    )

    write_rows_at_next_position(
        items_ws,
        item_rows
    )

    write_rows_at_next_position(
        review_ws,
        review_rows
    )

    return {

        "spreadsheet_url": spreadsheet.url,

        "inserted": len(invoice_rows),

        "duplicates_skipped": skipped_duplicates,

        "line_items_inserted": len(item_rows),

        "review_inserted": len(review_rows)
    }
