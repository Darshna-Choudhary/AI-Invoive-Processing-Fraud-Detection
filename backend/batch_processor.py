"""End-to-end batch pipeline: local PaddleOCR -> Cloudflare JSON -> Sheets."""
import asyncio
import hashlib
import multiprocessing
import os
import time
import uuid
import threading
from concurrent.futures import ProcessPoolExecutor

from backend.config import (
    ALLOWED_EXTENSIONS, OCR_WORKERS, CLOUDFLARE_CONCURRENCY, CLOUDFLARE_RPM_LIMIT,
)
from backend.ocr_worker import initialize_worker, process_single_invoice
from backend.cloudflare_extractor import (
    CloudflareQuotaOrCapacityError, extract_invoice_async,
)
from backend.sheet_sync import sync_batch_to_google_sheets, get_existing_invoice_index


class RequestPacer:
    """Process-wide request-start limiter shared across batches/event loops."""
    def __init__(self, rpm_limit):
        self.interval = 60.0 / max(1, rpm_limit)
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


_GLOBAL_REQUEST_PACER = RequestPacer(CLOUDFLARE_RPM_LIMIT)


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


def _result_from_ocr_failure(ocr_result, started):
    return {
        **ocr_result,
        "processing_time": round(time.perf_counter() - started, 2),
    }


async def _process_one(item, ocr_pool, llm_semaphore, quota_stop):
    started = time.perf_counter()
    loop = asyncio.get_running_loop()
    try:
        # PaddleOCR runs in a persistent local worker process, not in the UI thread.
        ocr_result = await loop.run_in_executor(ocr_pool, process_single_invoice, item)
        if ocr_result.get("status") != "ocr_success":
            return _result_from_ocr_failure(ocr_result, started)

        if quota_stop.is_set():
            return {
                **ocr_result,
                "status": "pending",
                "data": {},
                "error": "Cloudflare rate/quota limit reached; retry this invoice later.",
                "stage": "cloudflare_quota",
                "processing_time": round(time.perf_counter() - started, 2),
            }

        await _GLOBAL_REQUEST_PACER.wait()
        if quota_stop.is_set():
            return {
                **ocr_result, "status": "pending", "data": {},
                "error": "Cloudflare rate/quota limit reached; retry this invoice later.",
                "stage": "cloudflare_quota",
                "processing_time": round(time.perf_counter() - started, 2),
            }
        try:
            data = await extract_invoice_async(ocr_result["raw_text"], llm_semaphore)
            return {
                **ocr_result,
                "status": "success",
                "data": data,
                "error": None,
                "stage": "completed",
                "processing_time": round(time.perf_counter() - started, 2),
            }
        except CloudflareQuotaOrCapacityError as exc:
            quota_stop.set()
            return {
                **ocr_result,
                "status": "pending",
                "data": {},
                "error": str(exc),
                "stage": "cloudflare_quota",
                "processing_time": round(time.perf_counter() - started, 2),
            }
        except Exception as exc:
            return {
                **ocr_result,
                "status": "failed",
                "data": {},
                "error": str(exc),
                "stage": "cloudflare_extraction",
                "processing_time": round(time.perf_counter() - started, 2),
            }
    except Exception as exc:
        return {
            "invoice_id": item["invoice_id"],
            "filename": os.path.basename(item["path"]),
            "source_hash": item["source_hash"],
            "status": "failed",
            "raw_text": "",
            "data": {},
            "error": str(exc),
            "stage": "pipeline",
            "processing_time": round(time.perf_counter() - started, 2),
        }


async def process_batch(file_paths, progress_callback=None):
    batch_id = str(uuid.uuid4())
    manifest = create_file_manifest(file_paths)
    if not manifest:
        raise ValueError("No supported or unique invoice files found.")

    started = time.perf_counter()
    quota_stop = asyncio.Event()
    llm_semaphore = asyncio.Semaphore(CLOUDFLARE_CONCURRENCY)
    tasks = []
    results = []
    processed_results = []

    # Preflight duplicate check: don't spend OCR/LLM time on files already completed.
    # If Sheets is temporarily unavailable, fall back to normal processing and let sync report the error.
    try:
        existing_by_hash = await asyncio.to_thread(get_existing_invoice_index)
    except Exception:
        existing_by_hash = None

    process_manifest = []
    for item in manifest:
        existing = existing_by_hash.get(item["source_hash"]) if existing_by_hash is not None else None
        if existing and existing[1] not in ("failed", "pending"):
            skipped_result = {
                "invoice_id": item["invoice_id"],
                "filename": os.path.basename(item["path"]),
                "source_hash": item["source_hash"],
                "status": "duplicate_skipped",
                "raw_text": "",
                "data": {},
                "error": None,
                "stage": "duplicate_check",
                "processing_time": 0.0,
            }
            results.append(skipped_result)
            if progress_callback:
                try:
                    progress_callback(skipped_result, len(results), len(manifest))
                except Exception:
                    pass
        else:
            process_manifest.append(item)

    # Spawn avoids inheriting initialized native OCR/Paddle state from Streamlit.
    ocr_pool = None
    if process_manifest:
        ocr_pool = ProcessPoolExecutor(
            max_workers=OCR_WORKERS,
            mp_context=multiprocessing.get_context("spawn"),
            initializer=initialize_worker,
        )
    try:
        if process_manifest:
            tasks = [asyncio.create_task(_process_one(item, ocr_pool, llm_semaphore, quota_stop)) for item in process_manifest]
            for task in asyncio.as_completed(tasks):
                result = await task
                results.append(result)
                processed_results.append(result)
                if progress_callback:
                    try:
                        progress_callback(result, len(results), len(manifest))
                    except Exception:
                        pass
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if ocr_pool is not None:
            ocr_pool.shutdown(wait=True, cancel_futures=True)

    sync_error = None
    try:
        sync_report = await asyncio.to_thread(
            sync_batch_to_google_sheets, processed_results, batch_id, existing_by_hash
        )
    except Exception as exc:
        sync_error = str(exc)
        sync_report = {
            "spreadsheet_url": None, "inserted": 0, "updated": 0,
            "duplicates_skipped": 0, "line_items_inserted": 0, "review_inserted": 0,
        }

    pre_skipped = sum(1 for r in results if r["status"] == "duplicate_skipped")
    return {
        "batch_id": batch_id,
        "total": len(manifest),
        "completed": len(results),
        "success": sum(r["status"] == "success" for r in results),
        "review": sum(
            r["status"] == "success" and bool((r.get("data") or {}).get("validation", {}).get("issues"))
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
        "duplicates_skipped": pre_skipped + sync_report.get("duplicates_skipped", 0),
        "line_items_inserted": sync_report.get("line_items_inserted", 0),
        "review_inserted": sync_report.get("review_inserted", 0),
    }
