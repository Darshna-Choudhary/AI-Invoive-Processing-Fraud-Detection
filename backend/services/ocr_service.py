from paddleocr import PaddleOCR

class OCRService:
    def __init__(self):
        self.ocr = PaddleOCR(
            lang="en",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            enable_mkldnn=False
        )

    def extract_text(self, image_path: str) -> str:
        results = self.ocr.predict(image_path)

        extracted_lines = []

        for result in results:
            # PaddleOCR result contains recognized text
            if hasattr(result, "json"):
                data = result.json

                if callable(data):
                    data = data()

                if isinstance(data, dict):
                    rec_texts = data.get("res", {}).get("rec_texts", [])

                    extracted_lines.extend(rec_texts)

        return "\n".join(extracted_lines)