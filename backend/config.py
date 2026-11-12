import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_FOLDER = BASE_DIR / "uploads"
LOGS_FOLDER = BASE_DIR / "logs"

UPLOAD_FOLDER.mkdir(exist_ok=True)
LOGS_FOLDER.mkdir(exist_ok=True)
