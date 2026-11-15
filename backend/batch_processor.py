import asyncio
import hashlib
import os
import time
import uuid

from backend.config import (
    ALLOWED_EXTENSIONS,
    GEMINI_CONCURRENCY,
)
from backend.gemini_extractor import (
    create_gemini_clients,
    extract_invoice_with_gemini,
    close_gemini_clients,
)
from backend.sheet_sync import sync_batch_to_google_sheets
from backend.excel_export import generate_excel


def calculate_file_hash(file_path):
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def create_file_manifest(file_paths):
    manifest = []
    for file_path in file_paths:
        extension = os.path.splitext(file_path)[1].lower()
        if extension not in ALLOWED_EXTENSIONS:
            continue

        manifest.append({
            "invoice_id": str(uuid.uuid4()),
            "path": file_path,
            "source_hash": calculate_file_hash(file_path),
        })
    return manifest


async def process_batch(file_paths, progress_callback=None):
    batch_id = str(uuid.uuid4())
    manifest = create_file_manifest(file_paths)

    if not manifest:
        raise ValueError("No supported invoice files found")

    started = time.perf_counter()
    semaphore = asyncio.Semaphore(GEMINI_CONCURRENCY)
    results = []
    manifest_by_id = {item["invoice_id"]: item for item in manifest}

    sync_client, async_client = create_gemini_clients()

    tasks = [
        asyncio.create_task(
            extract_invoice_with_gemini(
                item, semaphore, sync_client, async_client
            )
        )
        for item in manifest
    ]

    try:
        for task in asyncio.as_completed(tasks):
            result = await task

            # Attach original file hash for existing duplicate detection.
            manifest_item = manifest_by_id[result["invoice_id"]]
            result["source_hash"] = manifest_item["source_hash"]
            results.append(result)

            if progress_callback:
                progress_callback(result, len(results), len(manifest))

        # Google Sheets and openpyxl are synchronous. Run them in worker
        # threads so they do not block FastAPI's event loop.
        sync_report = await asyncio.to_thread(
            sync_batch_to_google_sheets,
            results,
            batch_id,
        )

        excel_path = await asyncio.to_thread(
            generate_excel,
            results,
            batch_id,
        )

        elapsed = time.perf_counter() - started

        return {
            "batch_id": batch_id,
            "total": len(manifest),
            "success": sum(r["status"] == "success" for r in results),
            "failed": sum(r["status"] == "failed" for r in results),
            "processing_time": round(elapsed, 2),
            "google_sheet_url": sync_report["spreadsheet_url"],
            "excel_path": excel_path,
            "results": results,
            "inserted": sync_report["inserted"],
            "duplicates_skipped": sync_report["duplicates_skipped"],
            "line_items_inserted": sync_report["line_items_inserted"],
            "review_inserted": sync_report["review_inserted"],
        }

    finally:
        # Cancel any outstanding tasks if the batch itself is interrupted.
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await close_gemini_clients(sync_client, async_client)
