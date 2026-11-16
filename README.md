# Invoice Processing final patch

## Architecture preserved
- Streamlit frontend
- FastAPI endpoint (optional)
- Async batch processor
- Direct Gemini Vision input (original PDF/image)
- Pydantic JSON schema
- Python financial validation
- Google Sheets tabs: Invoices, Line Items, Needs Review

## Replace these files
Copy into the existing project, keeping the folder structure:
- backend/config.py
- backend/gemini_extractor.py
- backend/batch_processor.py
- backend/sheet_sync.py
- backend/app.py
- backend/app2.py
- frontend/stream_app.py

Do not overwrite `.env`, `credentials/`, or `uploads/`.

## .env values
Add/update these entries in your existing `.env`:
```env
GEMINI_API_KEY=YOUR_KEY
GEMINI_MODEL=gemini-3.8-flash
GEMINI_CONCURRENCY=2
GEMINI_RPM_LIMIT=YOUR_PROJECT_RPM
GEMINI_RPM_SAFETY_FACTOR=0.80
GEMINI_MAX_RETRIES=2
MAX_BATCH_FILES=100
MAX_UPLOAD_MB=45
MAX_BATCH_TOTAL_MB=500
```
Use the RPM actually assigned to your selected model and project. The limiter is
process-local, so run one Uvicorn worker unless you use a shared distributed limiter.

## Important retry / duplicate behaviour
- Previously successful/reviewed files are skipped as duplicates.
- Previously failed or pending files are reprocessed when re-uploaded.
- The old failed/pending invoice row is updated in place.
- Old line-item and Needs Review rows for that source hash are replaced.
- The Streamlit dashboard also has a Retry failed/pending button.
- Retryable transient Gemini errors are retried automatically.
- Daily quota exhaustion makes remaining invoices pending; wait for quota reset
  before retrying them.

## Output / uploads
- No Excel workbook is generated.
- No outputs directory is created or used.
- Uploaded documents remain in `uploads/`.

## Install
```bash
pip install -U streamlit pandas fastapi uvicorn python-multipart \
  python-dotenv google-genai pydantic gspread google-auth google-auth-oauthlib
```

## Syntax check
```bash
python -m py_compile backend/config.py backend/gemini_extractor.py \
  backend/batch_processor.py backend/sheet_sync.py backend/app.py \
  backend/app2.py frontend/stream_app.py
```

## Run Streamlit
```bash
streamlit run frontend/stream_app.py
```

## Run FastAPI (optional)
```bash
uvicorn backend.app:app --host 127.0.0.1 --port 8000 --workers 1
```

## Remove only after repository-wide import search
The updated path does not use:
- `outputs/`
- `backend/excel_export.py`
- `backend/ocr_worker.py`
- `backend/schemas.py`
- `backend/extraction.py`

Check references before deleting:
```bash
grep -R -nE 'excel_export|ocr_worker|backend\.schemas|backend\.extraction' \
  . --exclude-dir=.venv --exclude-dir=venv --exclude-dir=.git \
  --exclude-dir=__pycache__
```
If the only reference is inside `ocr_worker.py` importing `backend.extraction`,
and no active module imports either file, both can be removed. Keep `uploads/`,
`.env`, `credentials/`, and the backend/frontend folders.