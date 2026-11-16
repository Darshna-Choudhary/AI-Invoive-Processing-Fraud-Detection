import os
import uuid
from typing import List

from fastapi import FastAPI, UploadFile, File, HTTPException

from backend.config import (
    UPLOAD_DIR,
    ALLOWED_EXTENSIONS,
    MAX_BATCH_FILES,
    MAX_UPLOAD_MB,
    MAX_BATCH_TOTAL_MB,
)

from backend.batch_processor import process_batch


app = FastAPI(title="AI Invoice Batch Processor")


@app.post("/process-batch")
async def upload_batch(files: List[UploadFile] = File(...)):

    if not files:
        raise HTTPException(
            status_code=400,
            detail="No files provided."
        )

    if len(files) > MAX_BATCH_FILES:
        raise HTTPException(
            status_code=413,
            detail=f"Maximum {MAX_BATCH_FILES} files allowed per batch."
        )

    # Create a unique folder for this batch inside uploads/
    batch_dir = os.path.join(
        UPLOAD_DIR,
        str(uuid.uuid4())
    )

    os.makedirs(batch_dir, exist_ok=True)

    saved_paths = []
    total_bytes = 0

    file_limit = MAX_UPLOAD_MB * 1024 * 1024
    batch_limit = MAX_BATCH_TOTAL_MB * 1024 * 1024

    try:
        for upload in files:

            original_name = upload.filename or "invoice"

            extension = os.path.splitext(original_name)[1].lower()

            # Validate file extension
            if extension not in ALLOWED_EXTENSIONS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unsupported file format: {original_name}"
                )

            # Generate unique filename to avoid collisions
            filename = f"{uuid.uuid4().hex}{extension}"

            file_path = os.path.join(
                batch_dir,
                filename
            )

            file_bytes = 0

            # Save uploaded file in chunks
            with open(file_path, "wb") as output:

                while True:

                    chunk = await upload.read(1024 * 1024)

                    if not chunk:
                        break

                    file_bytes += len(chunk)
                    total_bytes += len(chunk)

                    # Individual file size validation
                    if file_bytes > file_limit:
                        raise HTTPException(
                            status_code=413,
                            detail=(
                                f"{original_name} exceeds "
                                f"{MAX_UPLOAD_MB} MB."
                            )
                        )

                    # Total batch size validation
                    if total_bytes > batch_limit:
                        raise HTTPException(
                            status_code=413,
                            detail=(
                                f"Batch exceeds "
                                f"{MAX_BATCH_TOTAL_MB} MB."
                            )
                        )

                    output.write(chunk)

            saved_paths.append(file_path)

        # Process all uploaded invoices
        report = await process_batch(saved_paths)

        return {
            "batch_id": report.get("batch_id"),
            "total": report.get("total"),
            "completed": report.get("completed"),
            "success": report.get("success"),
            "review": report.get("review"),
            "failed": report.get("failed"),
            "pending": report.get("pending"),
            "processing_time": report.get("processing_time"),

            "google_sheet_url": report.get("google_sheet_url"),

            "inserted": report.get("inserted"),
            "updated": report.get("updated"),
            "duplicates_skipped": report.get("duplicates_skipped"),

            "line_items_inserted": report.get("line_items_inserted"),
            "review_inserted": report.get("review_inserted"),

            "results": report.get("results"),
            "sync_error": report.get("sync_error"),
        }

    finally:
        for upload in files:
            await upload.close()


@app.get("/")
def home():

    return {
        "message": "AI Invoice Batch Processor is running."
    }