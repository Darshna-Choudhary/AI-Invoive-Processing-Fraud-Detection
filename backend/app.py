import os
import uuid
from typing import List

from fastapi import FastAPI, UploadFile, File, HTTPException

from backend.config import UPLOAD_DIR, ALLOWED_EXTENSIONS
from backend.batch_processor import process_batch

app = FastAPI(title="Gemini Invoice Batch Processor")


@app.post("/process-batch")
async def upload_batch(files: List[UploadFile] = File(...)):
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    # Validate all extensions before saving any files.
    for file in files:
        extension = os.path.splitext(file.filename or "")[1].lower()
        if extension not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file: {file.filename}",
            )

    saved_files = []

    try:
        for file in files:
            extension = os.path.splitext(file.filename or "")[1].lower()
            filename = f"{uuid.uuid4()}{extension}"
            path = os.path.join(UPLOAD_DIR, filename)

            with open(path, "wb") as output:
                while chunk := await file.read(1024 * 1024):
                    output.write(chunk)

            saved_files.append(path)

        report = await process_batch(saved_files)

        return {
            "message": "Batch processed",
            "batch_id": report["batch_id"],
            "total": report["total"],
            "success": report["success"],
            "failed": report["failed"],
            "processing_time": report["processing_time"],
            "excel_file": report["excel_path"],
            "google_sheet_url": report["google_sheet_url"],
            "inserted": report["inserted"],
            "duplicates_skipped": report["duplicates_skipped"],
            "line_items_inserted": report["line_items_inserted"],
            "review_inserted": report["review_inserted"],
        }

    finally:
        for file in files:
            await file.close()


@app.get("/")
def home():
    return {"message": "Gemini invoice batch processor running"}
