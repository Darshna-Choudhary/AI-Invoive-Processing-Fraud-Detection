import os
from utils.pdf_utils import pdf_to_images
from utils.text_utils import save_text, save_json
from services.ocr_service import OCRService
from services.cleaning_service import clean_text
from services.field_extraction_service import extract_invoice_fields


class ExtractionService:
    def __init__(self):
        self.ocr_service = OCRService()

    def process_file(self, file_path):
        filename = os.path.basename(file_path)
        file_name_without_extension = os.path.splitext(filename)[0]
        extension = os.path.splitext(filename)[1].lower()
        output_dir = os.path.join("resultant_data","outputs",file_name_without_extension)
        os.makedirs(output_dir,exist_ok=True)

        all_pages_text = []

        # -----------------------------
        # PDF
        # -----------------------------

        if extension == ".pdf":
            image_dir = os.path.join(output_dir,"pages")
            image_paths = pdf_to_images(file_path,image_dir)

            for page_number, image_path in enumerate(image_paths,start=1):
                print(f"Processing page {page_number}...")
                text = self.ocr_service.extract_text(image_path)
                all_pages_text.append(f"--- PAGE {page_number} ---\n{text}")
            page_count = len(image_paths)

        # -----------------------------
        # IMAGE
        # -----------------------------

        elif extension in [".jpg",".jpeg",".png",".webp"]:
            print("Processing image...")
            text = self.ocr_service.extract_text(file_path)
            all_pages_text.append(text)
            page_count = 1

        else:
            raise ValueError("Unsupported file type")

        # -----------------------------
        # Combine text
        # -----------------------------

        final_text = "\n\n".join(
            all_pages_text
        )
        cleaned_text = clean_text(final_text)
        structured_data = extract_invoice_fields(cleaned_text)

        # -----------------------------
        # Save TXT
        # -----------------------------

        text_path = os.path.join(output_dir,f"{file_name_without_extension}.txt")
        save_text(cleaned_text, text_path)

        # -----------------------------
        # Save JSON
        # -----------------------------

        json_path = os.path.join(output_dir,f"{file_name_without_extension}.json")
        result = {
            "filename": filename,
            "pages": page_count,
            "text": final_text,
            "raw_text": final_text,
            "cleaned_text": cleaned_text,
            "invoice": structured_data
        }
        save_json(result,json_path)

        return result