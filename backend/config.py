import os
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))


def get_secret(name, default=""):
    """Read an environment variable or a Streamlit secret (flat or nested)."""
    value = os.getenv(name)
    if value is not None:
        return value

    try:
        import streamlit as st
        secrets = st.secrets
    except Exception:
        return default

    try:
        value = secrets.get(name)
        if value is not None:
            return str(value)
    except Exception:
        pass

    for section_name in ("cloudflare", "google"):
        try:
            section = secrets.get(section_name)
            if section is not None:
                value = section.get(name)
                if value is not None:
                    return str(value)
        except Exception:
            pass

    return default

UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}
MAX_BATCH_FILES = max(1, int(os.getenv("MAX_BATCH_FILES", "100")))
MAX_UPLOAD_MB = max(1, int(os.getenv("MAX_UPLOAD_MB", "45")))
MAX_BATCH_TOTAL_MB = max(MAX_UPLOAD_MB, int(os.getenv("MAX_BATCH_TOTAL_MB", "500")))

# OCR runs locally in separate processes. Keep CPU threads * workers within
# the physical/logical CPU budget of the machine.
PDF_DPI = max(100, int(os.getenv("PDF_DPI", "150")))
MAX_PDF_PAGES = max(1, int(os.getenv("MAX_PDF_PAGES", "30")))
OCR_WORKERS = max(1, int(os.getenv("OCR_WORKERS", "1")))
OCR_CPU_THREADS = max(1, int(os.getenv("OCR_CPU_THREADS", "2")))

# Cloudflare Workers AI REST API settings.
CLOUDFLARE_ACCOUNT_ID = get_secret("CLOUDFLARE_ACCOUNT_ID").strip()
CLOUDFLARE_API_TOKEN = get_secret("CLOUDFLARE_API_TOKEN").strip()
CLOUDFLARE_MODEL = get_secret(
    "CLOUDFLARE_MODEL", "@cf/google/gemma-4-26b-a4b-it"
).strip()
CLOUDFLARE_CONCURRENCY = max(1, int(get_secret("CLOUDFLARE_CONCURRENCY", "1") or "1"))
CLOUDFLARE_RPM_LIMIT = max(1, int(get_secret("CLOUDFLARE_RPM_LIMIT", "5") or "5"))
CLOUDFLARE_MAX_RETRIES = max(0, int(get_secret("CLOUDFLARE_MAX_RETRIES", "0") or "0"))
CLOUDFLARE_TIMEOUT = max(10, int(get_secret("CLOUDFLARE_TIMEOUT", "60") or "60"))
CLOUDFLARE_MAX_INPUT_CHARS = max(10000, int(get_secret("CLOUDFLARE_MAX_INPUT_CHARS", "100000") or "100000"))
