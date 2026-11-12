import json
import os

def save_text(text, output_path):
    directory = os.path.dirname(output_path)

    if directory:
        os.makedirs(directory, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as file:
        file.write(text)

def save_json(data, output_path):
    directory = os.path.dirname(output_path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4, ensure_ascii=False)