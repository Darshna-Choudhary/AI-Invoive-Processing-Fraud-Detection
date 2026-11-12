import os
import pymupdf

def pdf_to_images(pdf_path, output_dir):
    os.makedirs(output_dir,exist_ok=True)

    doc = pymupdf.open(pdf_path)
    image_paths = []

    for page_number, page in enumerate(doc):
        matrix = pymupdf.Matrix(2, 2)
        pix = page.get_pixmap(matrix=matrix)

        image_path = os.path.join(output_dir,f"page_{page_number + 1}.png")
        pix.save(image_path)

        image_paths.append(image_path)
    doc.close()

    return image_paths