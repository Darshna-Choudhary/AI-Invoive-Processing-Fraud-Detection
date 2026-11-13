import os
import uuid
import time
import multiprocessing
import hashlib
from concurrent.futures import ProcessPoolExecutor, as_completed

from backend.config import OCR_WORKERS, ALLOWED_EXTENSIONS
from backend.ocr_worker import initialize_worker, process_single_invoice
from backend.sheet_sync import sync_batch_to_google_sheets

def create_file_manifest(file_paths):
    manifest = []

    for file_path in file_paths:
        extension = os.path.splitext(file_path)[1].lower()

        if extension not in ALLOWED_EXTENSIONS:
            continue

        manifest.append({
            "invoice_id": str(uuid.uuid4()),
            "path": file_path,
            "source_hash": calculate_file_hash(file_path)
        })

    return manifest


def process_batch(file_paths, progress_callback=None):

    batch_id = str(uuid.uuid4())
    manifest = create_file_manifest(file_paths)

    results = []
    start_time = time.perf_counter()

    if not manifest:
        raise ValueError("No supported invoice files found")

    with ProcessPoolExecutor(
    max_workers=OCR_WORKERS,
    initializer=initialize_worker,
    mp_context=multiprocessing.get_context("spawn")
) as executor:

        futures = {
            executor.submit(process_single_invoice, item): item
            for item in manifest
        }

        for future in as_completed(futures):

            item = futures[future]

            try:
                 result = future.result()
            except Exception as error:
                 result = {
        "invoice_id": item["invoice_id"],
        "filename": os.path.basename(item["path"]),
        "status": "failed",
        "raw_text": "",
        "data": {},
        "error": str(error)
    }
            result["source_hash"] = item["source_hash"]

            results.append(result)

            if progress_callback:
                progress_callback(result, len(results), len(manifest))

    sync_report = sync_batch_to_google_sheets(results, batch_id)
    google_sheet_url = sync_report["spreadsheet_url"]
    elapsed = time.perf_counter() - start_time

    return {
        "batch_id": batch_id,
        "total": len(manifest),
        "success": sum(r["status"] == "success" for r in results),
        "failed": sum(r["status"] == "failed" for r in results),
        "processing_time": round(elapsed, 2),
        "google_sheet_url": google_sheet_url,
        "results": results,
        "google_sheet_url": google_sheet_url,
        "inserted": sync_report["inserted"],
        "duplicates_skipped": sync_report["duplicates_skipped"],
        "line_items_inserted": sync_report["line_items_inserted"],
        "review_inserted": sync_report["review_inserted"],
    }

def calculate_file_hash(file_path):
    sha256 = hashlib.sha256()

    with open(file_path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            sha256.update(chunk)

    return sha256.hexdigest()



# raw invoice data
# INVOICE
# Date: 21-Jan-2018
# Due Date : 30-Sep-2004
# PO Number :91
# Address:16424 Timothy Mission
# Bill to:Clifford Hubbard
# Markville, AK 58294 US
# 816 Tran Plaza Apt. 249
# Rebeccabury, KS 60646 US
# Email:melvin40@example.net
# Tel:+(871)109-5778
# www.ThompsonandSons.org
# Email:markgomez@example.com
# (GSTIN: 12345670 00070007
# Site:https://melendez.biz/
# GSTIN:OG@AAMFCO376K124
# ITEMS
# QUANTITY
# PRICE
# Turn compare throw.
# 4.00
# $31.88
# Exist significant know
# 1.00
# $60.02
# Use exactly soldier class.
# 6.00
# $54.82
# Total in words: five hundred and twenty-
# -nine point three three
# SUB TOTAL: 516.46 USD
# Bank Name
# Central Bank of USA
# DISCOUNT(3.42%): (-) 17.66
# Branch Name
# Raf CAMP
# TAX:VAT (6.71%): 34.66 USD
# Bank Account Number 11158150
# Bank Swift Code
# SBININBB250
# TOTAL: 529.33 USD
# Thank you for choosing us!