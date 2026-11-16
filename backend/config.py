import os
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))

UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
GEMINI_CONCURRENCY = max(1, int(os.getenv("GEMINI_CONCURRENCY", "2")))
GEMINI_MAX_RETRIES = max(0, int(os.getenv("GEMINI_MAX_RETRIES", "2")))
GEMINI_RPM_LIMIT = max(1, int(os.getenv("GEMINI_RPM_LIMIT", "5")))
GEMINI_RPM_SAFETY_FACTOR = min(1.0, max(0.1, float(os.getenv("GEMINI_RPM_SAFETY_FACTOR", "0.80"))))
MAX_BATCH_FILES = max(1, int(os.getenv("MAX_BATCH_FILES", "100")))
MAX_UPLOAD_MB = max(1, int(os.getenv("MAX_UPLOAD_MB", "45")))
MAX_BATCH_TOTAL_MB = max(MAX_UPLOAD_MB, int(os.getenv("MAX_BATCH_TOTAL_MB", "500")))
