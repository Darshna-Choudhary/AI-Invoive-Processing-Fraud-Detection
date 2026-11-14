import os
import json
import traceback

import fitz
import cv2
import numpy as np

from paddleocr import PaddleOCR

from backend.config import PDF_DPI, MAX_PDF_PAGES
from backend.extraction import extract_invoice_data


OCR_ENGINE = None


def initialize_worker():
    global OCR_ENGINE

    OCR_ENGINE = PaddleOCR(
        device="cpu",
        enable_mkldnn=False,
        cpu_threads=2,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False
    )

    print(
        f"OCR initialized in process {os.getpid()}",
        flush=True
    )


def _get_bbox(box):
    """Convert PaddleOCR box/polygon into [x1, y1, x2, y2]."""

    if box is None:
        return None

    points = np.asarray(box, dtype=float)

    if points.size < 4:
        return None

    if points.ndim == 1 and points.size == 4:
        x1, y1, x2, y2 = points
    else:
        points = points.reshape(-1, 2)
        x1 = points[:, 0].min()
        y1 = points[:, 1].min()
        x2 = points[:, 0].max()
        y2 = points[:, 1].max()

    return [
        round(float(x1), 2),
        round(float(y1), 2),
        round(float(x2), 2),
        round(float(y2), 2)
    ]


def extract_page_from_image(image, page_number=1):
    """Return OCR text and spatial information for one page."""

    if OCR_ENGINE is None:
        raise RuntimeError("OCR engine is not initialized")

    results = OCR_ENGINE.predict(image)

    page_blocks = []
    page_text = []

    for result in results:
        data = result.json

        if isinstance(data, str):
            data = json.loads(data)

        res = data.get("res", data)

        texts = res.get("rec_texts", [])
        scores = res.get("rec_scores", [])

        # PaddleOCR versions may expose either rec_boxes or rec_polys.
        boxes = res.get("rec_boxes")
        if boxes is None:
            boxes = res.get("rec_polys")
        if boxes is None:
            boxes = res.get("dt_polys")

        for index, text in enumerate(texts):
            text = str(text).strip()

            if not text:
                continue

            page_text.append(text)

            box = None
            if boxes is not None and index < len(boxes):
                box = _get_bbox(boxes[index])

            score = None
            if index < len(scores):
                try:
                    score = float(scores[index])
                except (TypeError, ValueError):
                    pass

            page_blocks.append({
                "text": text,
                "bbox": box,
                "confidence": score
            })

    height, width = image.shape[:2]

    return {
        "text": "\n".join(page_text),
        "layout": {
            "page_number": page_number,
            "width": width,
            "height": height,
            "blocks": page_blocks
        }
    }


def extract_text_from_image(image):
    """Backward-compatible text-only OCR function."""

    return extract_page_from_image(image)["text"]


def process_image(path):
    image = cv2.imread(path)

    if image is None:
        raise ValueError("Unable to read image")

    page = extract_page_from_image(image, page_number=1)

    return page["text"], [page["layout"]]


def process_pdf(path):
    document = fitz.open(path)

    if len(document) > MAX_PDF_PAGES:
        document.close()
        raise ValueError("PDF exceeds maximum page limit")

    all_text = []
    all_layout = []

    try:
        for page_index, page in enumerate(document, start=1):
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
                    image,
                    cv2.COLOR_RGBA2RGB
                )

            page_result = extract_page_from_image(
                image,
                page_number=page_index
            )

            all_text.append(page_result["text"])
            all_layout.append(page_result["layout"])

    finally:
        document.close()

    return "\n".join(all_text), all_layout


def process_single_invoice(file_info):
    invoice_id = file_info["invoice_id"]
    path = file_info["path"]

    text = ""
    layout = []
    stage = "initialization"

    try:
        if OCR_ENGINE is None:
            raise RuntimeError("OCR engine not initialized")

        extension = os.path.splitext(path)[1].lower()

        stage = "ocr"

        if extension == ".pdf":
            text, layout = process_pdf(path)
        else:
            text, layout = process_image(path)

        if not text.strip():
            raise ValueError("No text detected by OCR")

        stage = "extraction"

        extracted_data = extract_invoice_data(
            text,
            layout=layout
        )

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
