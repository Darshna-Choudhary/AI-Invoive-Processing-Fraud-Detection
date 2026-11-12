import re

def clean_text(raw_text):
    """
    Clean OCR text while preserving line order
    and the original meaning.
    """
    text = raw_text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")
    text = text.replace("\x00", "")

    cleaned_lines = []

    for line in text.split("\n"):
        line = re.sub(r"[ \t]+", " ", line).strip()
        if line:
            cleaned_lines.append(line)

    return "\n".join(cleaned_lines)
