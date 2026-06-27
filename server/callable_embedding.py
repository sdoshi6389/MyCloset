import torch
from PIL import Image
from transformers import CLIPProcessor, CLIPModel
from pillow_heif import register_heif_opener

# === HEIC Support ===
register_heif_opener()

# === CLIP Setup ===
device = "cuda" if torch.cuda.is_available() else "cpu"
model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32").to(device)
processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")

def generate_clip_embedding(image_path):
    image = Image.open(image_path).convert("RGB")
    inputs = processor(images=image, return_tensors="pt").to(device)
    with torch.no_grad():
        output = model.get_image_features(**inputs)
    embedding = output[0]
    embedding = embedding / embedding.norm()
    return embedding.cpu().tolist()

def save_embedding_to_db(user_id, filename, embedding):
    from db import get_supa
    filename = filename.lower()
    print(f"Saving embedding for user {user_id}, file: {filename}")
    try:
        result = get_supa().table("closet_items").update({
            "vector_embedding": embedding,
        }).eq("user_id", user_id).eq("filename", filename).execute()

        if result.data:
            print(f"Vector embedding saved for user {user_id}, file '{filename}' -> {len(embedding)} dimensions")
        else:
            print(f"No matching row found — update failed for user {user_id}, file '{filename}'")
    except Exception as e:
        print(f"Failed to save embedding: {e}")
