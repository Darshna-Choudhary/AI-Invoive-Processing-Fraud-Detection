import os
import uuid

from fastapi import FastAPI, UploadFile, File, HTTPException
from typing import List

from backend.config import UPLOAD_DIR, ALLOWED_EXTENSIONS
from backend.batch_processor import process_batch

app = FastAPI(title="Batch Invoice Processor")


@app.post("/process-batch")
async def upload_batch(
    files: List[UploadFile] = File(...)
):

    if not files:
        raise HTTPException(400, "No files provided")

    saved_files = []

    try:

        for file in files:

            extension = os.path.splitext(
                file.filename
            )[1].lower()

            if extension not in ALLOWED_EXTENSIONS:
                raise HTTPException(
                    400,
                    f"Unsupported file: {file.filename}"
                )

            filename = f"{uuid.uuid4()}{extension}"

            path = os.path.join(UPLOAD_DIR, filename)

            with open(path, "wb") as output:

                while chunk := await file.read(1024 * 1024):
                    output.write(chunk)

            saved_files.append(path)

        report = process_batch(saved_files)

        return {
            "message": "Batch processed",
            "batch_id": report["batch_id"],
            "total": report["total"],
            "success": report["success"],
            "failed": report["failed"],
            "processing_time": report["processing_time"],
            "excel_file": report["excel_path"]
        }

    finally:

        for file in files:
            await file.close()


@app.get("/")
def home():
    return {"message": "Invoice batch processor running"}