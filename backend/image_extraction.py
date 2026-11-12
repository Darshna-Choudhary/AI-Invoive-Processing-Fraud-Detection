# import pandas as pd
# file = "data/raw/FATURA2-invoices/data/train-00000-of-00001.parquet"
# df = pd.read_parquet(file)
# print(df.columns)
# print(df.shape)
# print(type(df["image"].iloc[0]))
# print(df["image"].iloc[0])

# Index(['image', 'ner_tags', 'bboxes', 'tokens', 'id'], dtype='str')


import pandas as pd
import os

# df = pd.read_parquet("data/raw/FATURA2-invoices/data/test-00000-of-00001.parquet")
df = pd.read_parquet("data/raw/FATURA2-invoices/data/train-00000-of-00001.parquet")

# output_dir = "data/test_invoices"
output_dir = "data/train_invoices"

os.makedirs(output_dir, exist_ok=True)
for i, row in df.iterrows():
    image_data = row["image"]
    image_bytes = image_data["bytes"]
    image_name = image_data["path"]

    output_path = os.path.join(output_dir, image_name)

    with open(output_path, "wb") as f:
        f.write(image_bytes)

print("Images extracted successfully.")