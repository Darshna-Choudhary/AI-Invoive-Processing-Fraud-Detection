# Gemini concurrent invoice extraction patch

This patch changes the primary extraction path from local PaddleOCR + regex
to Gemini PDF/image understanding. It keeps the existing Google Sheets sync
and Excel export modules.

## Files in this patch

Copy these files into your project, preserving the paths:

- `app.py` -> project root (replace uploaded FastAPI `app.py`)
- `backend/config.py` -> `backend/config.py`
- `backend/batch_processor.py` -> `backend/batch_processor.py`
- `backend/gemini_extractor.py` -> new file `backend/gemini_extractor.py`

Keep your existing:
- `backend/sheet_sync.py`
- `backend/excel_export.py`
- `backend/extraction.py` (only its `validate_invoice()` helper is reused)
- `backend/ocr_worker.py` (retained, but not used in the Gemini path)

## Install

Inside your existing Python 3.11 virtual environment:

```bash
pip install -U google-genai pydantic python-dotenv fastapi uvicorn python-multipart
```

Keep the packages required by your existing Google Sheets and Excel modules.

## .env

Add:

```env
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-3.8-flash
GEMINI_CONCURRENCY=3
GEMINI_MAX_RETRIES=3
```

Keep your existing Google Sheets environment variables unchanged.

Model availability, free-tier eligibility and quotas vary by account and can
change. A free quota is not unlimited usage. Check the quota shown in Google
AI Studio before increasing concurrency.

## Run

From your project root:

```bash
uvicorn app:app --reload
```

Open:

```text
http://127.0.0.1:8000/docs
```

Use `POST /process-batch` and upload multiple PDF/JPG/PNG/WEBP invoices.

## How concurrency works

`GEMINI_CONCURRENCY=3` means at most three invoices are being uploaded/
processed by Gemini at once. One API key and one SDK client are shared.
When one request finishes, the next queued invoice starts.

Start at 2 or 3. Increase only after checking the actual Gemini API rate limits
and free-tier quota for your selected model.

## Important implementation notes

- Gemini receives the original invoice PDF/image. PaddleOCR is not run first.
- Each invoice gets its own request and structured JSON response.
- The Python validation helper independently checks subtotal - discount + tax
  against the printed total. It does not overwrite the extracted total.
- The existing Google Sheets writer is called once after all invoices finish.
- The existing Excel export is called once after all invoices finish.
- Uploaded local invoice files are retained in `uploads/`.
- Gemini Files API uploads are deleted after processing when possible. Google
  documents temporary file retention of up to 48 hours.
- This is a synchronous HTTP batch endpoint: the request remains open until
  the batch finishes. For very large batches, move to a background job system
  later.
- Check Google's data-use terms before sending confidential customer invoices.
