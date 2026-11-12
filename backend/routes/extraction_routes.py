import os
from flask import Blueprint, request, jsonify
from services.extraction_service import ExtractionService


extraction_bp = Blueprint("extraction",__name__)

ALLOWED_EXTENSIONS = {"pdf", "jpg", "jpeg", "png", "webp"}

def allowed_file(filename):
    if "." not in filename:
        return False

    extension = filename.rsplit(".", 1)[1].lower()
    return extension in ALLOWED_EXTENSIONS


@extraction_bp.route("/extract", methods=["POST"])
def extract():
    if "file" not in request.files:
        return jsonify({
            "success": False,
            "error": "No file uploaded"
        }), 400

    file = request.files["file"]

    if file.filename == "":
        return jsonify({
            "success": False,
            "error": "No file selected"
        }), 400

    if not allowed_file(file.filename):
        return jsonify({
            "success": False,
            "error": "Only PDF, JPG, JPEG, PNG and WEBP files are allowed"
        }), 400

    upload_dir = "resultant_data/uploads"

    os.makedirs(upload_dir, exist_ok=True)

    filename = file.filename

    file_path = os.path.join(
        upload_dir,
        filename
    )
    file.save(file_path)

    try:
        extractor = ExtractionService()
        result = extractor.process_file(file_path)

        return jsonify({
            "success": True,
            "data": result
        }), 200

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500