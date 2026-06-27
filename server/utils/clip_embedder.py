"""
Shared CLIP embedding utility.  Loaded lazily — model downloads only when
generate_embedding() is first called, not on import.
"""

import requests as _requests
from io import BytesIO
from PIL import Image

_model = None
_processor = None
_device = None


def _load():
    global _model, _processor, _device
    if _model is not None:
        return
    import torch
    from transformers import CLIPProcessor, CLIPModel
    _device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Loading CLIP model on {_device}…")
    _model     = CLIPModel.from_pretrained("openai/clip-vit-base-patch32").to(_device)
    _processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
    print("CLIP ready.")


def generate_embedding(title: str, image_url: str) -> list | None:
    """
    Returns a 512-d combined (image + text) CLIP embedding as a Python list,
    or None if the image can't be fetched / processed.
    """
    import torch
    _load()
    try:
        resp  = _requests.get(image_url, timeout=15)
        resp.raise_for_status()
        image = Image.open(BytesIO(resp.content)).convert("RGB")
    except Exception as e:
        print(f"  ⚠️  image fetch failed ({image_url[:60]}…): {e}")
        return None

    try:
        inputs = _processor(text=[title], images=image, return_tensors="pt", padding=True)
        inputs = {k: v.to(_device) for k, v in inputs.items()}
        with torch.no_grad():
            out         = _model(**inputs)
            img_emb     = out.image_embeds[0]
            txt_emb     = out.text_embeds[0]
            combined    = (img_emb + txt_emb) / 2
            combined    = combined / combined.norm()
        return combined.cpu().tolist()
    except Exception as e:
        print(f"  ⚠️  embedding failed for '{title[:40]}': {e}")
        return None
