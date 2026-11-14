from pathlib import Path
from typing import Any, TypedDict

ALLOWED_EXTENSIONS = frozenset({".pdf", ".jpg", ".jpeg", ".png", ".webp"})

class ApiError(TypedDict):
    filename: str
    error: str

class BatchResponse(TypedDict, total=False):
    batch_id: str
    processed: int
    failed: int
    results: list[dict[str, Any]]
    errors: list[ApiError]
    excel_file: str | None


def allowed_file(filename: str) -> bool:
    """Return whether the filename has a supported invoice file extension."""
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS