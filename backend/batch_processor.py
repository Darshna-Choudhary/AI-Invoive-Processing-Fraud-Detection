import asyncio
import hashlib
import os
import time
import uuid
import threading

from backend.config import (
    ALLOWED_EXTENSIONS, GEMINI_CONCURRENCY, GEMINI_RPM_LIMIT,
    GEMINI_RPM_SAFETY_FACTOR,
)
from backend.gemini_extractor import (
    create_gemini_clients, extract_invoice_with_gemini, close_gemini_clients,
)
from backend.sheet_sync import sync_batch_to_google_sheets


class ProcessSemaphore:
    """A process-wide concurrency cap shared across batches and event loops."""
    def __init__(self, limit):
        self._semaphore = threading.BoundedSemaphore(limit)

    async def __aenter__(self):
        await asyncio.to_thread(self._semaphore.acquire)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self._semaphore.release()


class RequestPacer:
    """Process-local limiter for Gemini generate_content request starts."""
    def __init__(self, rpm_limit, safety_factor):
        effective_rpm = max(0.1, rpm_limit * safety_factor)
        self.interval = 60.0 / effective_rpm
        # threading.Lock makes this limiter shared across concurrent batches
        # and across the separate event loops created by Streamlit's asyncio.run.
        self.lock = threading.Lock()
        self.next_start = 0.0

    async def wait(self):
        with self.lock:
            now = time.monotonic()
            start_at = max(now, self.next_start)
            self.next_start = start_at + self.interval
        delay = start_at - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)


# One limiter per Python process, shared by all batches in that process.
_GLOBAL_REQUEST_PACER = RequestPacer(
    GEMINI_RPM_LIMIT, GEMINI_RPM_SAFETY_FACTOR
)
_GLOBAL_CONCURRENCY_SEMAPHORE = ProcessSemaphore(GEMINI_CONCURRENCY)


def calculate_file_hash(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_file_manifest(paths):
    manifest, seen = [], set()
    for path in paths:
        extension = os.path.splitext(path)[1].lower()
        if extension not in ALLOWED_EXTENSIONS:
            continue
        file_hash = calculate_file_hash(path)
        if file_hash in seen:
            continue
        seen.add(file_hash)
        manifest.append({
            "invoice_id": str(uuid.uuid4()),
            "path": path,
            "source_hash": file_hash,
        })
    return manifest


async def process_batch(file_paths, progress_callback=None):
    batch_id = str(uuid.uuid4())
    manifest = create_file_manifest(file_paths)
    if not manifest:
        raise ValueError("No supported or unique invoice files found.")

    started = time.perf_counter()
    semaphore = _GLOBAL_CONCURRENCY_SEMAPHORE
    pacer = _GLOBAL_REQUEST_PACER
    quota_stop = asyncio.Event()
    client, async_client = create_gemini_clients()
    tasks = []

    try:
        tasks = [
            asyncio.create_task(
                extract_invoice_with_gemini(
                    item, semaphore, client, async_client, pacer, quota_stop
                )
            )
            for item in manifest
        ]
        results = []
        for task in asyncio.as_completed(tasks):
            result = await task
            results.append(result)
            if progress_callback:
                try:
                    progress_callback(result, len(results), len(manifest))
                except Exception:
                    pass

        sync_error = None
        try:
            sync_report = await asyncio.to_thread(
                sync_batch_to_google_sheets, results, batch_id
            )
        except Exception as exc:
            # Keep extraction results visible even if the Sheets API is unavailable.
            sync_error = str(exc)
            sync_report = {
                "spreadsheet_url": None,
                "inserted": 0,
                "updated": 0,
                "duplicates_skipped": 0,
                "line_items_inserted": 0,
                "review_inserted": 0,
            }

        return {
            "batch_id": batch_id,
            "total": len(manifest),
            "completed": len(results),
            "success": sum(r["status"] == "success" for r in results),
            "review": sum(
                r["status"] == "success" and
                bool((r.get("data") or {}).get("validation", {}).get("issues"))
                for r in results
            ),
            "failed": sum(r["status"] == "failed" for r in results),
            "pending": sum(r["status"] == "pending" for r in results),
            "processing_time": round(time.perf_counter() - started, 2),
            "google_sheet_url": sync_report.get("spreadsheet_url"),
            "sync_error": sync_error,
            "results": results,
            "inserted": sync_report.get("inserted", 0),
            "updated": sync_report.get("updated", 0),
            "duplicates_skipped": sync_report.get("duplicates_skipped", 0),
            "line_items_inserted": sync_report.get("line_items_inserted", 0),
            "review_inserted": sync_report.get("review_inserted", 0),
        }
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await close_gemini_clients(client, async_client)
