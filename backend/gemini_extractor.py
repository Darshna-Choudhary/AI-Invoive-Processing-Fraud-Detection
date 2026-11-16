import asyncio
import json
import os
import random
import re
import time
from typing import Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

from backend.config import BASE_DIR, GEMINI_MODEL, GEMINI_MAX_RETRIES


class DailyQuotaExceeded(Exception):
    pass


def create_gemini_clients():
    load_dotenv(os.path.join(BASE_DIR, ".env"), override=False)
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is missing from .env")
    client = genai.Client(api_key=api_key)
    return client, client.aio


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
You are a highly accurate invoice data extraction engine.
Read the complete supplied invoice, every page and every visible line item.
Use visual layout and column relationships, not fixed positions.

Rules:
- Extract only information supported by the document. Never invent values.
- Return null for missing or genuinely unreadable scalar fields.
- Preserve invoice numbers exactly, including leading zeros and punctuation.
- Do not confuse invoice date, due date, PO number or delivery date.
- Distinguish subtotal, taxable value, discount, tax, shipping, amount paid,
  balance due and final invoice total.
- Preserve printed amounts. Never replace a printed amount with a calculation.
- Extract every visible line item, preserving row-to-column relationships.
- Do not confuse unit price with line total or merge separate line items.
- Identify supplier/seller and customer/bill-to separately.
- Extract tax IDs and bank details only when explicitly printed.
- Use ISO currency codes when unambiguous.
- Return YYYY-MM-DD dates only when interpretation is unambiguous; otherwise
  preserve the original date text.
- If uncertain, return null rather than guessing.
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
    raise TypeError(f"Unexpected response type: {type(parsed)!r}")


def _validate(data):
    subtotal = data.get("subtotal")
    total = data.get("total_amount")
    discount = data.get("discount") or 0
    tax = data.get("tax_amount") or 0
    shipping = data.get("shipping") or 0

    if subtotal is None or total is None:
        check = {"arithmetic_check": "not_verifiable",
                 "calculated_total": None, "difference": None}
    else:
        calculated = round(float(subtotal) - float(discount) +
                           float(tax) + float(shipping), 2)
        difference = round(float(total) - calculated, 2)
        check = {
            "arithmetic_check": "passed" if abs(difference) <= 0.02 else "mismatch",
            "calculated_total": calculated,
            "difference": difference,
        }

    issues = []
    if check["arithmetic_check"] == "mismatch":
        issues.append(
            f"Financial total mismatch: calculated={check['calculated_total']}, "
            f"printed={total}, difference={check['difference']}"
        )
    elif check["arithmetic_check"] == "not_verifiable":
        issues.append("Financial arithmetic could not be verified")

    for key, label in (("invoice_number", "Invoice number"),
                       ("invoice_date", "Invoice date"),
                       ("total_amount", "Total amount")):
        if data.get(key) in (None, ""):
            issues.append(f"{label} missing")

    data["validation"] = {**check, "issues": issues}
    return data


async def _upload(path, client):
    return await asyncio.to_thread(client.files.upload, file=path)


async def _delete_remote(name, client):
    if not name:
        return
    try:
        await asyncio.to_thread(client.files.delete, name=name)
    except Exception:
        pass


def _daily_quota(exc):
    message = str(exc).lower()
    return ("per day" in message or "perday" in message or
            "requestsperday" in message or
            ("generate_content_free_tier_requests" in message and "day" in message))


def _retryable(exc):
    message = str(exc).lower()
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    return code in (408, 429, 500, 502, 503, 504) or any(
        word in message for word in (
            "429", "503", "temporarily unavailable", "resource exhausted",
            "timeout", "rate limit", "internal server error"
        )
    )


def _retry_delay(exc, attempt):
    message = str(exc)
    for pattern in (
        r"retry in\s+([0-9]+(?:\.[0-9]+)?)\s*s",
        r'"retryDelay"\s*:\s*"([0-9]+(?:\.[0-9]+)?)s"',
        r"retrydelay.*?([0-9]+(?:\.[0-9]+)?)s",
    ):
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            return min(180.0, max(1.0, float(match.group(1)) + 1.0))
    return min(60.0, 2 ** attempt) + random.uniform(0.2, 0.8)


async def extract_invoice_with_gemini(
    file_info, semaphore, client, async_client, request_pacer, quota_stop_event
):
    started = time.perf_counter()
    uploaded = None
    path = file_info["path"]

    def make_result(status, data=None, error=None, stage="completed"):
        return {
            "invoice_id": file_info["invoice_id"],
            "filename": os.path.basename(path),
            "source_hash": file_info["source_hash"],
            "status": status,
            "raw_text": "",
            "data": data or {},
            "error": error,
            "stage": stage,
            "processing_time": round(time.perf_counter() - started, 2),
        }

    async with semaphore:
        if quota_stop_event.is_set():
            return make_result("pending", error="Daily Gemini quota exhausted; retry later.",
                               stage="quota")

        try:
            uploaded = await _upload(path, client)

            for attempt in range(GEMINI_MAX_RETRIES + 1):
                if quota_stop_event.is_set():
                    return make_result("pending", error="Daily Gemini quota exhausted; retry later.",
                                       stage="quota")
                try:
                    await request_pacer.wait()
                    response = await async_client.models.generate_content(
                        model=GEMINI_MODEL,
                        contents=[SYSTEM_PROMPT,
                                  "Extract this invoice into the requested schema.",
                                  uploaded],
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_schema=InvoiceExtraction,
                            temperature=0,
                        ),
                    )
                    parsed = getattr(response, "parsed", None)
                    if parsed is None and getattr(response, "text", None):
                        parsed = json.loads(response.text)
                    data = _to_dict(parsed)
                    data["supplier"] = data.get("supplier") or {}
                    data["customer"] = data.get("customer") or {}
                    data["bank_details"] = data.get("bank_details") or {}
                    data["line_items"] = data.get("line_items") or []
                    if not data.get("vendor") and isinstance(data["supplier"], dict):
                        data["vendor"] = data["supplier"].get("name")
                    if not data.get("bill_to") and isinstance(data["customer"], dict):
                        data["bill_to"] = data["customer"].get("name")
                    return make_result("success", data=_validate(data))

                except Exception as exc:
                    if _daily_quota(exc):
                        quota_stop_event.set()
                        return make_result("pending", error=str(exc), stage="quota")
                    if not _retryable(exc) or attempt >= GEMINI_MAX_RETRIES:
                        raise
                    await asyncio.sleep(_retry_delay(exc, attempt))

            return make_result("failed", error="Gemini retries exhausted.",
                               stage="gemini_extraction")

        except Exception as exc:
            return make_result("failed", error=str(exc), stage="gemini_extraction")
        finally:
            if uploaded is not None:
                await _delete_remote(getattr(uploaded, "name", None), client)


async def close_gemini_clients(client, async_client):
    try:
        await async_client.aclose()
    finally:
        client.close()
