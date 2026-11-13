import os
import sys
import uuid
import threading
import queue
import traceback
from dotenv import load_dotenv

# ---------------------------------
# PROJECT ROOT
# ---------------------------------

ROOT_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

load_dotenv(os.path.join(ROOT_DIR, ".env"))

import streamlit as st
import pandas as pd

from backend.config import UPLOAD_DIR
from backend.batch_processor import process_batch


# =================================
# PAGE CONFIGURATION
# =================================

st.set_page_config(
    page_title="Invoice Batch Processor",
    page_icon="📄",
    layout="wide"
)

st.title("📄 AI Invoice Processing System")
st.caption(
    "Bulk invoice OCR, automated extraction and Google Sheets integration"
)

# =================================
# SESSION STATE
# =================================

DEFAULT_STATE = {
    "running": False,
    "event_queue": None,
    "result": None,
    "batch_id": None,
    "progress_count": 0,
    "total_files": 0,
    "live_results": [],
    "fatal_error": None,
    "upload_batch_id": None
}

for key, value in DEFAULT_STATE.items():

    if key not in st.session_state:
        st.session_state[key] = value


# =================================
# BACKGROUND PROCESSING
# =================================

def run_batch(files, event_queue):

    try:

        def update_progress(result, completed, total):

            event_queue.put({
                "type": "progress",
                "result": result,
                "completed": completed,
                "total": total
            })

        report = process_batch(
            files,
            progress_callback=update_progress
        )

        event_queue.put({
            "type": "completed",
            "report": report
        })

    except Exception as error:

        event_queue.put({
            "type": "error",
            "message": str(error),
            "traceback": traceback.format_exc()
        })


# =================================
# FILE UPLOAD
# =================================

st.subheader("1. Upload invoices")

uploaded_files = st.file_uploader(
    "Select multiple invoice PDFs or images",
    type=[
        "pdf",
        "png",
        "jpg",
        "jpeg",
        "tif",
        "tiff"
    ],
    accept_multiple_files=True,
    disabled=st.session_state.running
)

if uploaded_files:

    st.success(
        f"{len(uploaded_files)} invoices selected"
    )

    st.write("### Selected files")

    for index, file in enumerate(uploaded_files):

        st.write(
            f"📄 {file.name} — {file.size / 1024:.1f} KB"
        )


# =================================
# START BATCH PROCESSING
# =================================

if st.button(
    "🚀 Start Batch Processing",
    disabled=(
        st.session_state.running
        or not uploaded_files
    ),
    use_container_width=True
):

    try:

        # Create a unique upload directory
        upload_batch_id = str(uuid.uuid4())

        batch_dir = os.path.join(
            UPLOAD_DIR,
            upload_batch_id
        )

        os.makedirs(
            batch_dir,
            exist_ok=True
        )

        saved_paths = []

        # Save uploaded files
        for index, file in enumerate(uploaded_files):

            original_name = os.path.basename(file.name)

            # Avoid filename collisions
            unique_name = (
                f"{index}_{uuid.uuid4().hex[:8]}_"
                f"{original_name}"
            )

            file_path = os.path.join(
                batch_dir,
                unique_name
            )

            with open(file_path, "wb") as f:
                f.write(file.getbuffer())

            saved_paths.append(file_path)

        if not saved_paths:
            raise ValueError("No files were uploaded")

        # Create event queue
        event_queue = queue.Queue()

        # Reset previous batch state
        st.session_state.running = True
        st.session_state.event_queue = event_queue
        st.session_state.result = None
        st.session_state.batch_id = None
        st.session_state.progress_count = 0
        st.session_state.total_files = len(saved_paths)
        st.session_state.live_results = []
        st.session_state.fatal_error = None
        st.session_state.upload_batch_id = upload_batch_id

        # Start background thread
        processing_thread = threading.Thread(
            target=run_batch,
            args=(
                saved_paths,
                event_queue
            ),
            daemon=True
        )

        processing_thread.start()

        st.rerun()

    except Exception as error:

        st.session_state.running = False

        st.error(
            f"Unable to start batch: {str(error)}"
        )

        st.exception(error)


# =================================
# PROCESSING DASHBOARD
# =================================

@st.fragment(run_every="1s")
def processing_dashboard():

    if not (
        st.session_state.running
        or st.session_state.result
        or st.session_state.fatal_error
    ):
        return

    event_queue = st.session_state.event_queue

    # ---------------------------------
    # READ EVENTS
    # ---------------------------------

    if event_queue is not None:

        while True:

            try:

                event = event_queue.get_nowait()

            except queue.Empty:

                break

            # Progress event
            if event["type"] == "progress":

                st.session_state.progress_count = (
                    event["completed"]
                )

                st.session_state.live_results.append(
                    event["result"]
                )

            # Completion event
            elif event["type"] == "completed":

                report = event["report"]

                st.session_state.result = report

                st.session_state.batch_id = (
                    report["batch_id"]
                )

                st.session_state.progress_count = (
                    report["total"]
                )

                st.session_state.running = False

            # Fatal batch error
            elif event["type"] == "error":

                st.session_state.running = False

                st.session_state.fatal_error = {
                    "message": event["message"],
                    "traceback": event.get(
                        "traceback",
                        ""
                    )
                }

    # =================================
    # DASHBOARD
    # =================================

    st.divider()

    st.subheader("2. Processing Dashboard")

    total = st.session_state.total_files

    completed = st.session_state.progress_count

    results = st.session_state.live_results

    successful = sum(
        r["status"] == "success"
        for r in results
    )

    failed = sum(
        r["status"] == "failed"
        for r in results
    )

    col1, col2, col3 = st.columns(3)

    col1.metric(
        "Total invoices",
        total
    )

    col2.metric(
        "Successful",
        successful
    )

    col3.metric(
        "Failed",
        failed
    )

    percentage = (
        completed / total
        if total > 0
        else 0
    )

    st.progress(
        percentage,
        text=f"{completed}/{total} invoices processed"
    )

    # ---------------------------------
    # RUNNING STATUS
    # ---------------------------------

    if st.session_state.running:

        st.info(
            "⚙️ Processing invoices... Please wait."
        )

    # ---------------------------------
    # FATAL ERROR
    # ---------------------------------

    if st.session_state.fatal_error:

        error = st.session_state.fatal_error

        st.error(
            f"Batch processing error: {error['message']}"
        )

        with st.expander(
            "View complete error traceback",
            expanded=True
        ):

            st.code(
                error["traceback"],
                language="python"
            )

    # ---------------------------------
    # COMPLETED STATUS
    # ---------------------------------

    if st.session_state.result:

        report = st.session_state.result

        st.success(
            "✅ Batch processing completed!"
        )

        a, b, c = st.columns(3)

        a.metric(
            "Successful",
            report["success"]
        )

        b.metric(
            "Failed",
            report["failed"]
        )

        c.metric(
            "Processing time",
            f'{report["processing_time"]} sec'
        )

        st.write(
            f"**Batch ID:** `{report['batch_id']}`"
        )
        st.write("### Google Sheets Sync")
        col1, col2, col3 = st.columns(3)
        col1.metric("New invoices", report.get("inserted", 0))
        col2.metric("Duplicates skipped", report.get("duplicates_skipped", 0))
        col3.metric("Line items added", report.get("line_items_inserted", 0))

    # =================================
    # RESULTS TABLE
    # =================================

    if results:

        st.divider()

        st.subheader("3. Invoice Processing Results")

        summary = []

        for result in results:

            data = result.get("data") or {}

            summary.append({

                "Invoice ID": result["invoice_id"],

                "Filename": result["filename"],

                "Status": result["status"],

                "Vendor": data.get("vendor"),

                "Invoice Number": data.get(
                    "invoice_number"
                ),

                "Total Amount": data.get(
                    "total_amount"
                ),

                "Error": result.get("error")

            })

        df = pd.DataFrame(summary)

        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True
        )

        # ---------------------------------
        # SUCCESSFUL INVOICE INSPECTION
        # ---------------------------------

        successful_results = [
            r for r in results
            if r["status"] == "success"
        ]

        if successful_results:

            with st.expander(
                "Inspect extracted invoice data"
            ):

                selected_index = st.selectbox(
                    "Choose invoice",
                    options=range(
                        len(successful_results)
                    ),
                    format_func=lambda i: (
                        successful_results[i]["filename"]
                    ),
                    key="invoice_selector"
                )

                selected = successful_results[
                    selected_index
                ]

                st.write("### Extracted Data")

                st.json(
                    selected.get("data", {})
                )

                with st.expander("Raw OCR Text"):

                    st.text(
                        selected.get("raw_text", "")
                    )

        # ---------------------------------
        # FAILED INVOICE INSPECTION
        # ---------------------------------

        failed_results = [
            r for r in results
            if r["status"] == "failed"
        ]

        if failed_results:

            with st.expander(
                f"Inspect failed invoices ({len(failed_results)})"
            ):

                for index, result in enumerate(
                    failed_results
                ):

                    st.error(
                        result["filename"]
                    )

                    st.write(
                        "**Failed stage:**",
                        result.get("stage", "Unknown")
                    )

                    st.write(
                        "**Error:**",
                        result.get("error", "Unknown error")
                    )

                    if result.get("traceback"):

                        st.code(
                            result["traceback"],
                            language="python"
                        )

                    st.divider()

    
# =================================
# GOOGLE SHEETS
# =================================

report = st.session_state.get("result")

if isinstance(report, dict):
    google_sheet_url = report.get("google_sheet_url")

    if google_sheet_url:
        st.success(
            "Invoices successfully synced to Google Sheets!"
        )

        st.link_button(
            "📊 Open Google Sheets",
            google_sheet_url,
            type="primary",
            use_container_width=True
        )
    else:
        st.warning(
            "Batch completed, but Google Sheets URL is unavailable."
        )


# =================================
# RENDER DASHBOARD
# =================================

processing_dashboard()
