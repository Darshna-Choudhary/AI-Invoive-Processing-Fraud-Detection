from backend.config import (
    PDF_DPI,
    MAX_PDF_PAGES,
    OCR_CPU_THREADS
)

import os
import fitz
import cv2
import numpy as np

from paddleocr import PaddleOCR
from backend.extraction import extract_invoice_data
import traceback



OCR_ENGINE = None



def initialize_worker():

    global OCR_ENGINE

    OCR_ENGINE = PaddleOCR(
        device="cpu",

        # Disable oneDNN to avoid PIR compatibility error
        enable_mkldnn=False,

        # CPU configuration
        cpu_threads=2,

        # Disable unnecessary processing
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False
    )

    print(
        f"OCR initialized in process {os.getpid()}",
        flush=True
    )



def extract_text_from_image(image):

    results = OCR_ENGINE.predict(image)

    page_text = []

    for result in results:

        data = result.json

        if isinstance(data, str):
            import json
            data = json.loads(data)

        res = data.get("res", data)

        texts = res.get("rec_texts", [])

        page_text.extend(texts)

    return "\n".join(page_text)


def process_image(path):

    image = cv2.imread(path)

    if image is None:
        raise ValueError("Unable to read image")

    return extract_text_from_image(image)


def process_pdf(path):

    document = fitz.open(path)

    if len(document) > MAX_PDF_PAGES:
        document.close()
        raise ValueError("PDF exceeds maximum page limit")

    all_text = []

    try:
        for page in document:

            pix = page.get_pixmap(
                matrix=fitz.Matrix(
                    PDF_DPI / 72,
                    PDF_DPI / 72
                ),
                alpha=False
            )

            image = np.frombuffer(
                pix.samples,
                dtype=np.uint8
            ).reshape(
                pix.height,
                pix.width,
                pix.n
            )

            if pix.n == 4:
                image = cv2.cvtColor(
                    image, cv2.COLOR_RGBA2RGB
                )

            page_text = extract_text_from_image(image)

            all_text.append(page_text)

    finally:
        document.close()

    return "\n".join(all_text)


def process_single_invoice(file_info):

    invoice_id = file_info["invoice_id"]
    path = file_info["path"]

    text = ""
    stage = "initialization"

    try:
        if OCR_ENGINE is None:
            raise RuntimeError("OCR engine not initialized")

        extension = os.path.splitext(path)[1].lower()

        # Stage 1: OCR
        stage = "ocr"

        if extension == ".pdf":
            text = process_pdf(path)
        else:
            text = process_image(path)

        if not text.strip():
            raise ValueError("No text detected by OCR")

        # Stage 2: Data extraction
        stage = "extraction"

        extracted_data = extract_invoice_data(text)

        return {
            "invoice_id": invoice_id,
            "filename": os.path.basename(path),
            "status": "success",
            "raw_text": text,
            "data": extracted_data,
            "error": None,
            "stage": "completed"
        }

    except Exception as error:

        error_details = traceback.format_exc()

        print(
            f"\nFAILED: {os.path.basename(path)}"
            f"\nStage: {stage}"
            f"\nError: {error_details}",
            flush=True
        )

        return {
            "invoice_id": invoice_id,
            "filename": os.path.basename(path),
            "status": "failed",
            "raw_text": text,
            "data": {},
            "error": str(error),
            "traceback": error_details,
            "stage": stage
        }
