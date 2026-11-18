# AI Invoice Processing & Fraud Detection

An AI-powered invoice processing system that extracts structured information from PDF and image invoices, validates financial data, identifies potential issues, and syncs results to Google Sheets.

## 1. Project Overview

The system automates invoice data extraction using local OCR and Cloudflare Workers AI.

**Key Features**
- Batch processing of multiple invoices (up to 100 files).
- Supports PDF, PNG, JPG, JPEG and WEBP formats.
- Local OCR using PaddleOCR.
- AI-based structured data extraction using Cloudflare Workers AI.
- Financial data validation and issue detection.
- Duplicate invoice file detection using SHA-256 hashing.
- Automatic retry handling for failed and pending invoices.
- Google Sheets integration for storing extracted results.
- Real-time processing progress through Streamlit.

## 2. System Architecture

```text
          Invoice Upload
                 |
                 v
       Streamlit Frontend
                 |
                 v
          Batch Processor
                 |
                 v
       Duplicate File Check
          (SHA-256 Hash)
                 |
                 v
       Local PaddleOCR Engine
                 |
                 v
          Extracted OCR Text
                 |
                 v
       Cloudflare Workers AI
          (GLM-4.7-Flash)
                 |
                 v
       Structured JSON Output
                 |
                 v
       Python Validation Layer
                 |
                 v
        Google Sheets Sync
                 |
        -------------------
        |        |        |
     Invoices  Line Items  Needs Review
```

## 3. Technology Stack

| Component | Technology |
|---|---|
| Frontend | Streamlit |
| Backend | Python |
| OCR | PaddleOCR |
| AI Extraction | Cloudflare Workers AI |
| AI Model | GLM-4.7-Flash |
| Data Processing | Python |
| API Framework | FastAPI (optional) |
| Database / Storage | Google Sheets |
| File Processing | PyMuPDF, OpenCV |
| Configuration | Python dotenv |

## 4. Project Structure

```text
invoice-processing-fraud/
│
├── backend/
│   ├── __init__.py
│   ├── app.py
│   ├── batch_processor.py
│   ├── cloudflare_extractor.py
│   ├── config.py
│   ├── ocr_worker.py
│   └── sheet_sync.py
│
├── frontend/
│   └── stream_app.py
│
├── credentials/
│   ├── client_secret.json
│   └── token.json
│
├── data/
├── uploads/
│
├── .env
├── .gitignore
├── requirements.txt
└── README.md
```

**Note:** Credentials, environment variables, uploaded invoices and local datasets are excluded from version control.

## 5. Installation and Setup

### Prerequisites
- Python 3.11
- pip
- Cloudflare account with Workers AI access
- Google Cloud OAuth credentials
- Google Spreadsheet

### Clone the Repository

```bash
git clone <YOUR_GITHUB_REPOSITORY_URL>
cd invoice-processing-fraud
```

### Create Virtual Environment

```bash
python3.11 -m venv .venv
source .venv/bin/activate
```

### Install Dependencies

```bash
pip install -r requirements.txt
```

## 6. Environment Configuration

Create a `.env` file in the project root.

Configure the following variables:

```env
# Google Sheets
GOOGLE_SHEET_ID=your_google_sheet_id
GOOGLE_OAUTH_CLIENT_FILE=credentials/client_secret.json
GOOGLE_TOKEN_FILE=credentials/token.json

# Cloudflare Workers AI
CLOUDFLARE_ACCOUNT_ID=your_account_id
CLOUDFLARE_API_TOKEN=your_api_token
CLOUDFLARE_MODEL=@cf/zai-org/glm-4.7-flash

# Processing Configuration
OCR_WORKERS=1
OCR_CPU_THREADS=2

CLOUDFLARE_TIMEOUT=60
CLOUDFLARE_MAX_RETRIES=0
CLOUDFLARE_CONCURRENCY=1
CLOUDFLARE_RPM_LIMIT=5
```

Use your actual Cloudflare model and configuration values. Never commit API keys, OAuth tokens or other credentials.

## 7. Google Sheets Configuration

1. Create a Google Cloud project.
2. Enable the Google Sheets API.
3. Configure OAuth credentials.
4. Download the OAuth client JSON file.
5. Place it inside the `credentials/` directory.
6. Configure the Google Spreadsheet ID in `.env`.
7. Authorize the application when prompted.

The application maintains three worksheets:

- **Invoices:** Extracted invoice-level information.
- **Line Items:** Individual product or service details.
- **Needs Review:** Invoices requiring manual inspection.

## 8. Run the Application

Start the Streamlit frontend:

```bash
streamlit run frontend/stream_app.py
```

Open the local URL displayed in the terminal.

### Optional FastAPI Backend

```bash
uvicorn backend.app:app --host 0.0.0.0 --port 8000
```

The FastAPI endpoint accepts invoice batches through `/process-batch`.

## 9. Processing Workflow

1. Upload invoice documents through the Streamlit interface.
2. Validate file formats and batch size.
3. Generate SHA-256 hashes to identify exact duplicate files.
4. Process invoice documents using local PaddleOCR.
5. Send extracted OCR text to Cloudflare Workers AI.
6. Receive structured invoice information in JSON format.
7. Normalize extracted values and validate financial information.
8. Identify missing fields and financial inconsistencies.
9. Synchronize invoice records, line items and review flags with Google Sheets.
10. Display processing status and batch results in the dashboard.

## 10. Validation and Duplicate Handling

The system performs:
- Required-field checks.
- Financial arithmetic validation.
- Missing information detection.
- Exact file duplicate detection.
- Failed and pending invoice retry handling.
- Review flag generation for suspicious or inconsistent data.

**Note:** SHA-256 duplicate detection identifies byte-identical files. It does not guarantee detection of visually identical invoices saved in different file formats.

## 11. Security

- Store API keys and credentials in environment variables and local credential files.
- Never upload `.env` or `credentials/` to GitHub.
- Keep uploaded invoice documents outside version control.
- Restrict access to the Google Spreadsheet and Cloudflare API token.

## 12. Future Enhancements

- Advanced invoice fraud detection.
- Purchase Order (PO) matching and verification.
- Improved semantic duplicate detection.
- Persistent processing history and audit logs.
- Database integration for scalable invoice management.
- Deployment and production monitoring.

---

**Project:** AI Invoice Processing & Fraud Detection  
**Primary Workflow:** Local OCR → Cloud AI Extraction → Python Validation → Google Sheets
