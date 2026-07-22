from PIL import Image
from pillow_heif import register_heif_opener

# === HEIC Support ===
register_heif_opener()

# === CLIP setup (fully lazy) ===
# torch + CLIP load on the first embedding call, not at import. This keeps the
# web app's baseline RAM low (no ~1 GB torch runtime at boot), which also lets
# the FAISS rebuild run without competing for memory.
_MODEL = None
_PROCESSOR = None
_DEVICE = None


def _get_clip():
    global _MODEL, _PROCESSOR, _DEVICE
    if _MODEL is None:
        import torch
        from transformers import CLIPProcessor, CLIPModel
        _DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
        _MODEL = CLIPModel.from_pretrained("openai/clip-vit-base-patch32").to(_DEVICE)
        _PROCESSOR = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
    return _MODEL, _PROCESSOR


def generate_clip_embedding(image_path):
    import torch
    model, processor = _get_clip()
    image = Image.open(image_path).convert("RGB")
    inputs = processor(images=image, return_tensors="pt").to(_DEVICE)
    with torch.no_grad():
        output = model.get_image_features(**inputs)
    embedding = output[0]
    embedding = embedding / embedding.norm()
    return embedding.cpu().tolist()


def encode_text(text: str) -> list:
    """CLIP text encoder — returns a 512-dim normalized embedding in the same space as image embeddings."""
    import torch
    model, processor = _get_clip()
    inputs = processor(text=[text], return_tensors="pt", padding=True).to(_DEVICE)
    with torch.no_grad():
        output = model.get_text_features(**inputs)
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
