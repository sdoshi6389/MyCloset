import os
from PIL import Image
from pillow_heif import register_heif_opener
from transformers import CLIPProcessor, CLIPModel
import torch
import psycopg2
from psycopg2.extras import execute_values
from io import BytesIO

# === Database config ===
PG_USER = "postgres"
PG_PASSWORD = "#Sohildoshi123"
PG_HOST = "localhost"
PG_PORT = "5432"
DB_NAME = "closet_images"
TABLE_NAME = "image_metadata"

def get_connection():
    return psycopg2.connect(dbname=DB_NAME, user=PG_USER, password=PG_PASSWORD, host=PG_HOST, port=PG_PORT)

# === HEIC Setup ===
register_heif_opener()

# === CLIP Setup ===
model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")

# === Folder Setup ===
INPUT_FOLDER = "downloaded_images"
CONVERTED_FOLDER = "converted_images"
os.makedirs(CONVERTED_FOLDER, exist_ok=True)

# === Process + Update ===
def update_embeddings():
    conn = get_connection()
    cur = conn.cursor()
    updated = 0

    for filename in os.listdir(INPUT_FOLDER):
        if filename.lower().endswith(".heic"):
            input_path = os.path.abspath(os.path.join(INPUT_FOLDER, filename))
            jpg_filename = filename.lower().replace(".heic", ".jpg")
            jpg_path = os.path.join(CONVERTED_FOLDER, jpg_filename)

            try:
                # Convert HEIC to JPG
                image = Image.open(input_path)
                image.save(jpg_path, format="JPEG")
                image = Image.open(jpg_path).convert("RGB")

                # Generate embedding
                inputs = processor(images=image, return_tensors="pt")
                with torch.no_grad():
                    output = model.get_image_features(**inputs)
                    embedding = output[0]
                    embedding = embedding / embedding.norm()

                # Insert into DB
                cur.execute(f"""
                    UPDATE {TABLE_NAME}
                    SET vector_embedding = %s
                    WHERE filename = %s AND filepath = %s
                """, (
                    embedding.tolist(),
                    filename,
                    input_path
                ))

                if cur.rowcount == 1:
                    updated += 1
                    print(f"✅ Updated embedding for: {filename}")
                else:
                    print(f"⚠️ No matching row found for {filename} → skipped")

            except Exception as e:
                print(f"❌ Error on {filename}: {e}")

    conn.commit()
    cur.close()
    conn.close()
    print(f"\n🎉 Embedding update complete: {updated} rows updated.")

if __name__ == "__main__":
    update_embeddings()
