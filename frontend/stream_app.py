import os
import sys
import uuid
import threading
import queue
import traceback
import asyncio

from dotenv import load_dotenv

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
load_dotenv(os.path.join(ROOT_DIR, ".env"))

import streamlit as st
import pandas as pd

from backend.config import (
    UPLOAD_DIR, MAX_BATCH_FILES, MAX_UPLOAD_MB, MAX_BATCH_TOTAL_MB,
)
from backend.batch_processor import process_batch

st.set_page_config(page_title="Invoice Batch Processor", page_icon="📄", layout="wide")
st.title("📄 AI Invoice Processing System")
st.caption("Local PaddleOCR + Cloudflare Workers AI extraction with Google Sheets integration")

DEFAULTS = {
    "running": False, "event_queue": None, "result": None,
    "batch_id": None, "progress_count": 0, "total_files": 0,
    "live_results": [], "fatal_error": None, "current_file_paths": [],
}
for key, value in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = value


def _progress_callback(event_queue):
    def callback(result, completed, total):
        event_queue.put({
            "type": "progress", "result": result,
            "completed": completed, "total": total,
        })
    return callback


def _run_batch(paths, event_queue):
    try:
        report = asyncio.run(
            process_batch(paths, progress_callback=_progress_callback(event_queue))
        )
        event_queue.put({"type": "completed", "report": report})
    except Exception as exc:
        event_queue.put({
            "type": "error", "message": str(exc),
            "traceback": traceback.format_exc(),
        })


def start_processing(paths):
    if not paths:
        st.error("No invoice files to process.")
        return
    q = queue.Queue()
    st.session_state.running = True
    st.session_state.event_queue = q
    st.session_state.result = None
    st.session_state.batch_id = None
    st.session_state.progress_count = 0
    st.session_state.total_files = len(paths)
    st.session_state.live_results = []
    st.session_state.fatal_error = None
    st.session_state.current_file_paths = list(paths)

    thread = threading.Thread(target=_run_batch, args=(list(paths), q), daemon=True)
    thread.start()


st.subheader("1. Upload invoices")
uploads = st.file_uploader(
    "Select invoice PDFs or images",
    type=["pdf", "png", "jpg", "jpeg", "webp"],
    accept_multiple_files=True,
    disabled=st.session_state.running,
)

if uploads:
    total_bytes = sum(f.size for f in uploads)
    st.success(f"{len(uploads)} invoice file(s) selected")
    st.caption(f"Combined size: {total_bytes / (1024 * 1024):.2f} MB")
    with st.expander("Selected files"):
        for f in uploads:
            st.write(f"{f.name} — {f.size / 1024:.1f} KB")

valid_upload = bool(uploads)
if uploads and len(uploads) > MAX_BATCH_FILES:
    st.error(f"Maximum {MAX_BATCH_FILES} files per batch.")
    valid_upload = False
if uploads and any(f.size > MAX_UPLOAD_MB * 1024 * 1024 for f in uploads):
    st.error(f"Each file must be no larger than {MAX_UPLOAD_MB} MB.")
    valid_upload = False
if uploads and sum(f.size for f in uploads) > MAX_BATCH_TOTAL_MB * 1024 * 1024:
    st.error(f"Combined upload size must not exceed {MAX_BATCH_TOTAL_MB} MB.")
    valid_upload = False

if st.button(
    "🚀 Start Batch Processing",
    disabled=not valid_upload or st.session_state.running,
    use_container_width=True,
):
    try:
        batch_folder = os.path.join(UPLOAD_DIR, str(uuid.uuid4()))
        os.makedirs(batch_folder, exist_ok=True)
        saved = []
        for index, uploaded in enumerate(uploads):
            ext = os.path.splitext(uploaded.name)[1].lower()
            original = os.path.basename(uploaded.name)
            name = f"{index:03d}_{uuid.uuid4().hex[:8]}_{original}"
            path = os.path.join(batch_folder, name)
            with open(path, "wb") as destination:
                destination.write(uploaded.getbuffer())
            saved.append(path)
        start_processing(saved)
        st.rerun()
    except Exception as exc:
        st.error(f"Unable to start batch: {exc}")
        st.exception(exc)


@st.fragment(run_every="1s")
def processing_dashboard():
    if not (
        st.session_state.running or st.session_state.result
        or st.session_state.fatal_error
    ):
        return

    q = st.session_state.event_queue
    if q is not None:
        while True:
            try:
                event = q.get_nowait()
            except queue.Empty:
                break

            if event["type"] == "progress":
                st.session_state.progress_count = event["completed"]
                st.session_state.total_files = event["total"]
                st.session_state.live_results.append(event["result"])
            elif event["type"] == "completed":
                st.session_state.result = event["report"]
                st.session_state.batch_id = event["report"]["batch_id"]
                st.session_state.progress_count = event["report"]["completed"]
                st.session_state.running = False
            elif event["type"] == "error":
                st.session_state.running = False
                st.session_state.fatal_error = event

    st.divider()
    st.subheader("2. Processing Dashboard")

    total = st.session_state.total_files
    completed = st.session_state.progress_count
    results = st.session_state.live_results
    successful = sum(r["status"] == "success" for r in results)
    failed = sum(r["status"] == "failed" for r in results)
    pending = sum(r["status"] == "pending" for r in results)
    review = sum(
        r["status"] == "success"
        and bool((r.get("data") or {}).get("validation", {}).get("issues"))
        for r in results
    )

    cols = st.columns(6)
    for col, label, value in zip(
        cols,
        ["Total", "Completed", "Successful", "Needs review", "Failed", "Pending"],
        [total, completed, successful, review, failed, pending],
    ):
        col.metric(label, value)

    st.progress(
        completed / total if total else 0.0,
        text=f"{completed}/{total} invoices processed",
    )

    if st.session_state.running:
        st.info("Processing invoices. Progress refreshes automatically.")

    if st.session_state.fatal_error:
        st.error(st.session_state.fatal_error.get("message", "Batch failed"))
        with st.expander("Full traceback"):
            st.code(st.session_state.fatal_error.get("traceback", ""), language="python")

    report = st.session_state.result
    if report:
        st.success("Batch processing finished.")
        st.write(f"**Batch ID:** `{report['batch_id']}`")
        st.write(f"**Processing time:** {report['processing_time']} seconds")

        if report.get("google_sheet_url"):
            st.link_button("📊 Open Google Sheets", report["google_sheet_url"])
        else:
            st.warning("No Google Sheets URL was returned. Check the backend logs.")

        a, b, c = st.columns(3)
        a.metric("New invoice rows", report.get("inserted", 0))
        b.metric("Failed/pending rows updated", report.get("updated", 0))
        c.metric("Successful duplicates skipped", report.get("duplicates_skipped", 0))

        path_by_name = {
            os.path.basename(path): path
            for path in st.session_state.current_file_paths
        }
        retry_paths = [
            path_by_name[result.get("filename", "")]
            for result in report.get("results", [])
            if result.get("status") in ("failed", "pending")
            and result.get("filename", "") in path_by_name
        ]
        if retry_paths:
            if pending:
                st.warning(
                    "Pending invoices may be waiting for Cloudflare rate limits or daily quota to reset. "
                    "Retry after quota is available."
                )
            if st.button(
                f"↻ Retry failed/pending invoices ({len(retry_paths)})",
                disabled=st.session_state.running or not retry_paths,
                use_container_width=True,
            ):
                start_processing(retry_paths)
                st.rerun()

    if results:
        st.divider()
        st.subheader("3. Invoice Processing Results")
        table = []
        for r in results:
            data = r.get("data") or {}
            table.append({
                "Filename": r.get("filename"),
                "Status": r.get("status"),
                "Vendor": data.get("vendor"),
                "Invoice Number": data.get("invoice_number"),
                "Total Amount": data.get("total_amount"),
                "Stage": r.get("stage"),
                "Processing Time": r.get("processing_time"),
                "Error": r.get("error"),
            })
        st.dataframe(pd.DataFrame(table), use_container_width=True, hide_index=True)

        good = [r for r in results if r["status"] == "success"]
        if good:
            with st.expander("Inspect extracted invoice data"):
                idx = st.selectbox(
                    "Choose invoice",
                    range(len(good)),
                    format_func=lambda i: good[i]["filename"],
                    key="invoice_inspector",
                )
                st.json(good[idx].get("data", {}))


processing_dashboard()
