import asyncio
import json
import os
import random
import time
from typing import Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

from backend.config import BASE_DIR, GEMINI_MODEL, GEMINI_MAX_RETRIES
from backend.extraction import validate_invoice

load_dotenv(os.path.join(BASE_DIR, ".env"))

API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    raise RuntimeError("GEMINI_API_KEY is missing from the project .env file")

def create_gemini_clients():
    """Create one sync/async client pair for a batch."""
    if not API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is missing from the project .env file"
        )
    sync_client = genai.Client(api_key=API_KEY)
    return sync_client, sync_client.aio


class Address(BaseModel):
    line1: Optional[str] = None
    line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None


class Party(BaseModel):
    name: Optional[str] = None
    address: Optional[Address] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None


class BankDetails(BaseModel):
    bank_name: Optional[str] = None
    branch_name: Optional[str] = None
    account_number: Optional[str] = None
    swift_code: Optional[str] = None
    iban: Optional[str] = None


class LineItem(BaseModel):
    description: Optional[str] = None
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    tax: Optional[float] = None
    line_total: Optional[float] = None


class InvoiceExtraction(BaseModel):
    vendor: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    due_date: Optional[str] = None
    po_number: Optional[str] = None

    gstin: Optional[str] = None
    currency: Optional[str] = None
    subtotal: Optional[float] = None
    discount: Optional[float] = None
    discount_rate: Optional[float] = None
    tax_type: Optional[str] = None
    tax_rate: Optional[float] = None
    tax_amount: Optional[float] = None
    shipping: Optional[float] = None
    total_amount: Optional[float] = None
    payment_terms: Optional[str] = None

    supplier: Optional[Party] = None
    customer: Optional[Party] = None
    bank_details: Optional[BankDetails] = None

    line_items: list[LineItem] = Field(default_factory=list)


SYSTEM_PROMPT = """
You are a careful invoice data extraction system.

Read the complete supplied invoice PDF or image. Invoice layouts and field
labels vary. Use the document's visual layout and context, not fixed positions.

Rules:
- Extract only values supported by the document.
- Never invent, infer, or repair a missing value. Use null.
- Do not confuse invoice date with due date.
- Do not confuse subtotal, tax, discount, amount paid, balance due and total.
- Preserve monetary values as printed. Do not recalculate or silently correct them.
- Extract all visible line items. Keep quantity, unit price, tax and line total
  in their correct fields. Do not treat a unit price as a line total.
- Identify supplier and customer separately. Do not swap their details.
- Extract bank details only when explicitly printed.
- If a field is ambiguous, return null rather than guessing.
- Dates should be returned as printed, preferably YYYY-MM-DD only when the
  date interpretation is unambiguous. If ambiguous, preserve the original text.
- Currency should be an ISO code where identifiable (for example USD, INR, EUR).
- Ignore unrelated text and marketing content.
"""


def _to_dict(parsed):
    if parsed is None:
        raise ValueError("Gemini returned no structured result")
    if hasattr(parsed, "model_dump"):
        return parsed.model_dump()
    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, str):
        return json.loads(parsed)
    raise TypeError(f"Unexpected parsed response type: {type(parsed)!r}")


def _build_validation(data):
    validation = validate_invoice(data)
    issues = []

    if validation["arithmetic_check"] == "mismatch":
        issues.append(
            "Financial total mismatch: "
            f"calculated={validation.get('calculated_total')}, "
            f"printed={data.get('total_amount')}, "
            f"difference={validation.get('difference')}"
        )
    elif validation["arithmetic_check"] == "not_verifiable":
        issues.append("Financial arithmetic could not be verified")

    for key, label in (
        ("invoice_number", "Invoice number"),
        ("invoice_date", "Invoice date"),
        ("total_amount", "Total amount"),
    ):
        if data.get(key) is None:
            issues.append(f"{label} missing")

    validation["issues"] = issues
    data["validation"] = validation
    return data


async def _upload_file(path, sync_client):
    # Files API upload is synchronous in the SDK. Move it off the event loop.
    return await asyncio.to_thread(sync_client.files.upload, file=path)


async def _delete_remote_file(file_name, sync_client):
    if not file_name:
        return
    try:
        await asyncio.to_thread(
            sync_client.files.delete,
            name=file_name
        )
    except Exception:
        # Gemini Files are temporary (normally retained for up to 48 hours).
        # A cleanup failure should not turn a successful extraction into failure.
        pass


async def extract_invoice_with_gemini(
    file_info, semaphore, sync_client, async_client
):
    path = file_info["path"]
    uploaded = None
    started = time.perf_counter()

    async with semaphore:
        try:
            uploaded = await _upload_file(path, sync_client)

            last_error = None
            for attempt in range(GEMINI_MAX_RETRIES + 1):
                try:
                    response = await async_client.models.generate_content(
                        model=GEMINI_MODEL,
                        contents=[
                            SYSTEM_PROMPT,
                            "Extract this invoice into the requested schema.",
                            uploaded,
                        ],
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_schema=InvoiceExtraction,
                            temperature=0,
                        ),
                    )

                    parsed = getattr(response, "parsed", None)
                    if parsed is None and response.text:
                        parsed = json.loads(response.text)

                    data = _to_dict(parsed)

                    # Normalize nested objects and preserve the keys expected
                    # by the existing Google Sheets and Excel modules.
                    data["supplier"] = data.get("supplier") or {}
                    data["customer"] = data.get("customer") or {}
                    data["bank_details"] = data.get("bank_details") or {}
                    data["line_items"] = data.get("line_items") or []

                    if not data.get("vendor"):
                        data["vendor"] = (
                            data["supplier"].get("name")
                            if isinstance(data["supplier"], dict)
                            else None
                        )

                    if not data.get("bill_to"):
                        customer = data["customer"]
                        data["bill_to"] = (
                            customer.get("name")
                            if isinstance(customer, dict)
                            else None
                        )

                    data = _build_validation(data)

                    return {
                        "invoice_id": file_info["invoice_id"],
                        "filename": os.path.basename(path),
                        "status": "success",
                        "raw_text": "",
                        "data": data,
                        "error": None,
                        "stage": "completed",
                        "processing_time": round(time.perf_counter() - started, 2),
                    }

                except Exception as exc:
                    last_error = exc
                    code = getattr(exc, "code", None)

                    # Retry transient throttling/server errors only.
                    retryable = (
                        code in (408, 429, 500, 502, 503, 504)
                        or any(s in str(exc).lower() for s in (
                            "429", "503", "temporarily unavailable",
                            "resource exhausted", "timeout"
                        ))
                    )
                    if not retryable or attempt >= GEMINI_MAX_RETRIES:
                        raise

                    await asyncio.sleep(
                        min(2 ** attempt, 12) + random.uniform(0, 0.5)
                    )

            raise last_error

        except Exception as exc:
            return {
                "invoice_id": file_info["invoice_id"],
                "filename": os.path.basename(path),
                "status": "failed",
                "raw_text": "",
                "data": {},
                "error": str(exc),
                "stage": "gemini_extraction",
                "processing_time": round(time.perf_counter() - started, 2),
            }

        finally:
            if uploaded is not None:
                await _delete_remote_file(
                    getattr(uploaded, "name", None),
                    sync_client
                )


async def close_gemini_clients(sync_client, async_client):
    try:
        await async_client.aclose()
    finally:
        sync_client.close()
