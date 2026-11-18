"""Local PaddleOCR worker. This module does OCR only; no regex/LLM extraction."""
import json
import os
import traceback

import cv2
import fitz
import numpy as np
from paddleocr import PaddleOCR

from backend.config import PDF_DPI, MAX_PDF_PAGES, OCR_CPU_THREADS

OCR_ENGINE = None


def initialize_worker():
    global OCR_ENGINE
    OCR_ENGINE = PaddleOCR(
        device="cpu",
        enable_mkldnn=False,
        cpu_threads=OCR_CPU_THREADS,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )
    print(f"PaddleOCR initialized in process {os.getpid()}", flush=True)


def _get_bbox(box):
    if box is None:
        return None
    points = np.asarray(box, dtype=float)
    if points.size < 4:
        return None
    if points.ndim == 1 and points.size == 4:
        x1, y1, x2, y2 = points
    else:
        points = points.reshape(-1, 2)
        x1, y1 = points[:, 0].min(), points[:, 1].min()
        x2, y2 = points[:, 0].max(), points[:, 1].max()
    return [round(float(x1), 2), round(float(y1), 2), round(float(x2), 2), round(float(y2), 2)]


def extract_page_from_image(image, page_number=1):
    if OCR_ENGINE is None:
        raise RuntimeError("OCR engine is not initialized")
    results = OCR_ENGINE.predict(image)
    page_blocks, page_text = [], []
    for result in results:
        data = result.json
        if isinstance(data, str):
            data = json.loads(data)
        res = data.get("res", data)
        texts = res.get("rec_texts", [])
        scores = res.get("rec_scores", [])
        boxes = res.get("rec_boxes")
        if boxes is None:
            boxes = res.get("rec_polys")
        if boxes is None:
            boxes = res.get("dt_polys")
        for index, raw in enumerate(texts):
            value = str(raw).strip()
            if not value:
                continue
            page_text.append(value)
            box = _get_bbox(boxes[index]) if boxes is not None and index < len(boxes) else None
            try:
                score = float(scores[index]) if index < len(scores) else None
            except (TypeError, ValueError):
                score = None
            page_blocks.append({"text": value, "bbox": box, "confidence": score})
    height, width = image.shape[:2]
    return {
        "text": "\n".join(page_text),
        "layout": {"page_number": page_number, "width": width, "height": height, "blocks": page_blocks},
    }


def process_image(path):
    image = cv2.imread(path)
    if image is None:
        raise ValueError(f"Unable to read image: {path}")
    page = extract_page_from_image(image, 1)
    return page["text"]


def process_pdf(path):
    document = fitz.open(path)
    page_count = len(document)
    if page_count > MAX_PDF_PAGES:
        document.close()
        raise ValueError(f"PDF has {page_count} pages; maximum allowed is {MAX_PDF_PAGES}")
    pages = []
    try:
        for page_index, page in enumerate(document, start=1):
            pix = page.get_pixmap(matrix=fitz.Matrix(PDF_DPI / 72, PDF_DPI / 72), alpha=False)
            image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
            if pix.n == 4:
                image = cv2.cvtColor(image, cv2.COLOR_RGBA2RGB)
            pages.append(extract_page_from_image(image, page_index)["text"])
    finally:
        document.close()
    return "\n\n".join(f"--- PAGE {i} ---\n{value}" for i, value in enumerate(pages, start=1))


def process_single_invoice(file_info):
    """Picklable ProcessPoolExecutor target; returns OCR text only."""
    path = file_info["path"]
    stage = "ocr"
    raw_text = ""
    try:
        if OCR_ENGINE is None:
            raise RuntimeError("OCR engine not initialized")
        extension = os.path.splitext(path)[1].lower()
        raw_text = process_pdf(path) if extension == ".pdf" else process_image(path)
        if not raw_text.strip():
            raise ValueError("No text detected by OCR")
        return {
            "invoice_id": file_info["invoice_id"],
            "filename": os.path.basename(path),
            "source_hash": file_info["source_hash"],
            "status": "ocr_success",
            "raw_text": raw_text,
            "data": {},
            "error": None,
            "stage": "ocr_completed",
        }
    except Exception as exc:
        return {
            "invoice_id": file_info["invoice_id"],
            "filename": os.path.basename(path),
            "source_hash": file_info["source_hash"],
            "status": "failed",
            "raw_text": raw_text,
            "data": {},
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "stage": stage,
        }
