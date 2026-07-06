"""
Catalog item icon extraction via gpt-image-1 image-edit.

Same pipeline as the closet icon generator:
  1. Download the retailer product photo
  2. Call gpt-image-1 edit with a slot-aware isolation prompt
  3. Save the transparent-bg PNG to catalog_extracted/
  4. Cache the path in catalog_icon_cache so the API is only called once per URL

Subsequent requests for the same (image_url, slot) are served instantly from disk
or from the DB cache (survives server restarts).
"""
import os
import io
import hashlib
import tempfile
import base64

# Re-use download helpers from bg_remove (headers, redirect handling)
from bg_remove import CACHE_DIR, _build_headers

try:
    from replicate_icon_clothing import OPENAI_API_KEY
except Exception:
    try:
        from config import OPENAI_API_KEY
    except Exception:
        OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

# Slot → plain-English garment description for the prompt
_SLOT_GARMENT = {
    "inner_top":    "the top, shirt, blouse, or t-shirt being worn",
    "outer_top":    "the jacket, coat, blazer, or outerwear being worn",
    "inner_bottom": "the pants, trousers, or jeans being worn",
    "outer_bottom": "the shorts, skirt, or bottom garment being worn",
    "left_shoe":    "the shoes or footwear shown",
    "right_shoe":   "the shoes or footwear shown",
    "hat":          "the hat or cap shown",
    "bag":          "the bag, purse, or accessory shown",
    "innerwear":    "the innerwear or undergarment shown",
    "underwear":    "the underwear or undergarment shown",
}


def _icon_path(image_url: str, slot: str | None = None) -> str:
    key = f"gpt|{image_url}|{slot or ''}"
    h = hashlib.md5(key.encode()).hexdigest()
    return os.path.join(CACHE_DIR, f"gpt_{h}.png")


def _db_lookup(image_url: str, slot: str | None) -> str | None:
    cache_key = f"{image_url}|{slot or ''}"
    try:
        from db import get_supa
        res = (get_supa().table("catalog_icon_cache")
               .select("icon_path")
               .eq("cache_key", cache_key)
               .limit(1)
               .execute())
        if res.data:
            p = res.data[0]["icon_path"]
            if os.path.exists(p):
                return p
    except Exception as e:
        print(f"⚠️  catalog_icon DB lookup: {e}")
    return None


def _db_save(image_url: str, slot: str | None, icon_path: str):
    cache_key = f"{image_url}|{slot or ''}"
    try:
        from db import get_supa
        get_supa().table("catalog_icon_cache").upsert({
            "cache_key": cache_key,
            "image_url": image_url,
            "slot":      slot,
            "icon_path": icon_path,
        }).execute()
    except Exception as e:
        print(f"⚠️  catalog_icon DB save: {e}")


def _download(image_url: str) -> str | None:
    """Download to a temp file. Returns path or None."""
    import requests as _req
    headers = _build_headers(image_url)
    session = _req.Session()
    session.headers.update(headers)

    def _reattach(resp, *args, **kwargs):
        if resp.is_redirect:
            resp.request.headers.update(headers)
    session.hooks["response"].append(_reattach)

    try:
        resp = session.get(image_url, timeout=15)
        resp.raise_for_status()
        ct = resp.headers.get("Content-Type", "image/jpeg")
        ext = ".png" if "png" in ct else ".jpg"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
        tmp.write(resp.content)
        tmp.close()
        return tmp.name
    except Exception as e:
        print(f"⛔ catalog_icon download failed ({image_url[:60]}…): {e}")
        return None


def _call_gpt(source_path: str, slot: str | None, out_path: str) -> str | None:
    """Call gpt-image-1 edit to isolate and re-pose the garment."""
    import openai
    import requests as _req
    from PIL import Image

    garment = _SLOT_GARMENT.get(slot, "the clothing item") if slot else "the clothing item"
    prompt = (
        f"Using this exact photo, isolate only {garment}. "
        "Keep its exact color, pattern, print, logo, and fabric texture completely unchanged — "
        "do not invent or alter any details. "
        "Remove the person wearing it, any model or mannequin, all background, and all shadows. "
        "Make the background fully transparent. "
        "Re-pose the garment into a flat, front-facing, symmetrical product-catalog layout — "
        "as if laid flat or worn by an invisible ghost mannequin facing the camera straight-on — "
        "with sleeves, body, and hems straightened and uncreased."
    )

    # Convert to RGBA PNG (required by the edit API)
    png_path = source_path + "_edit.png"
    try:
        with Image.open(source_path) as img:
            img.convert("RGBA").save(png_path, "PNG")
    except Exception as e:
        print(f"⚠️  catalog_icon PNG convert failed: {e}")
        return None

    try:
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        with open(png_path, "rb") as img_file:
            response = client.images.edit(
                model="gpt-image-1",
                image=img_file,
                prompt=prompt,
                size="1024x1024",
                background="transparent",
                input_fidelity="high",
                n=1,
            )
        item = response.data[0]
        b64 = getattr(item, "b64_json", None)
        if b64:
            img_bytes = base64.b64decode(b64)
        elif getattr(item, "url", None):
            img_bytes = _req.get(item.url, timeout=60).content
        else:
            print("⚠️  catalog_icon: gpt-image-1 returned no data")
            return None

        with open(out_path, "wb") as f:
            f.write(img_bytes)
        print(f"✅ catalog icon → {os.path.basename(out_path)}")
        return out_path

    except Exception as e:
        print(f"⚠️  catalog_icon gpt-image-1 failed: {e}")
        return None
    finally:
        try:
            os.unlink(png_path)
        except Exception:
            pass


def extract_catalog_icon(image_url: str, slot: str | None = None) -> str | None:
    """
    Public entry point.  Returns the local path to a transparent-bg PNG of the
    isolated garment, or None if generation fails.

    Cache priority:
      1. Disk  (instant — file already exists from a previous run)
      2. DB    (survives server restarts, path re-used if file still present)
      3. GPT   (gpt-image-1 edit — ~5-10 s first time, cached forever after)
    """
    out_path = _icon_path(image_url, slot)
    if os.path.exists(out_path):
        return out_path

    cached = _db_lookup(image_url, slot)
    if cached:
        return cached

    tmp = _download(image_url)
    if not tmp:
        return None

    try:
        result = _call_gpt(tmp, slot, out_path)
        if result:
            _db_save(image_url, slot, result)
        return result
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass
