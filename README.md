# Invoice Batch Processing

Flask API that extracts invoice text and fields from PDF and image files, processes multiple files in a batch, and exports invoice summaries and line items to Excel.

## Project layout

```text
backend/
	__init__.py
	config.py
	batch_processor.py
	ocr_worker.py
	extraction.py
	excel_export.py
	api.py
	schemas.py
uploads/
outputs/
.env
requirements.txt
```

## Setup

Use Python 3.10 or later, install the packages in `requirements.txt`, and configure `.env` if the defaults need to change. The `.env` file supports `HOST`, `PORT`, `DEBUG`, `MAX_CONTENT_LENGTH` (bytes), and `OCR_LANG`.

Start the API from the project root with `python -m backend.api`. The health check is `GET /api/health`.

Send one file as `file` or multiple files as repeated `files` fields to `POST /api/extract`. Supported types are PDF, JPG, JPEG, PNG, and WEBP. The response includes extracted invoice data and an Excel download URL when at least one file is processed successfully. Uploaded files and generated artifacts are stored under `uploads/` and `outputs/` respectively.




uvicorn backend.app:app --host 127.0.0.1 --port 8000
pip install streamlit
streamlit run frontend/streamlit_app.py