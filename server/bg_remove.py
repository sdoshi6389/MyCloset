"""
Background removal + garment-region crop for catalog product images.
Uses rembg (U2Net ONNX, fully local — no API calls).

Model strategy:
  1. u2net_cloth_seg  — purpose-built cloth segmentation; removes model body
                        AND background, leaving only the garment. Best result.
  2. u2net (fallback) — general background removal; keeps the person but at
                        least removes the studio backdrop.

Cache key includes the slot so the same product URL can be cropped differently
for a "top" vs "bottom" recommendation.
"""
import os
import hashlib
import io
from urllib.parse import urlparse

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "catalog_extracted")
os.makedirs(CACHE_DIR, exist_ok=True)

# In-memory set of (url, slot) pairs that failed this session — avoids
# hammering the same blocked URL on every re-render.
_FAIL_CACHE: set = set()

# Lazy-loaded rembg sessions (downloaded once to ~/.u2net/ on first use)
_cloth_session = None
_general_session = None


def _get_cloth_session():
    global _cloth_session
    if _cloth_session is None:
        try:
            from rembg import new_session
            _cloth_session = new_session("u2net_cloth_seg")
            print("✓ Cloth segmentation model ready (u2net_cloth_seg)")
        except Exception as e:
            print(f"⚠️  Could not load cloth seg model: {e}")
            _cloth_session = False  # sentinel — don't retry
    return _cloth_session if _cloth_session else None


def _get_general_session():
    global _general_session
    if _general_session is None:
        try:
            from rembg import new_session
            _general_session = new_session("u2net")
        except Exception:
            _general_session = False
    return _general_session if _general_session else None


# Fraction of image height to keep: (top_edge, bottom_edge)
_SLOT_CROP = {
    "inner_top":    (0.00, 0.60),
    "outer_top":    (0.00, 0.65),
    "hat":          (0.00, 0.28),
    "necklace":     (0.00, 0.38),
    "bracelet":     (0.00, 0.55),
    "innerwear":    (0.00, 0.60),
    "inner_bottom": (0.32, 1.00),
    "outer_bottom": (0.32, 1.00),
    "underwear":    (0.32, 1.00),
    "left_shoe":    (0.60, 1.00),
    "right_shoe":   (0.60, 1.00),
}


def _cache_path(url: str, slot: str | None = None) -> str:
    key = url + (f"|{slot}" if slot else "")
    h = hashlib.md5(key.encode()).hexdigest()
    return os.path.join(CACHE_DIR, h + ".png")


def _build_headers(image_url: str) -> dict:
    """
    Mimic a browser loading an image.  CDNs like Scene7 (Express, etc.) check
    that the Referer comes from the *main site*, not the image CDN subdomain.
    e.g. images.express.com images need Referer: https://www.express.com/
    """
    parsed = urlparse(image_url)
    parts = parsed.netloc.split(".")
    if len(parts) >= 3 and parts[0] in ("images", "img", "cdn", "static", "media", "assets"):
        main_domain = ".".join(parts[1:])
    else:
        main_domain = parsed.netloc
    referer = f"{parsed.scheme}://www.{main_domain}/"

    return {
        "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Referer":         referer,
        "Accept":          "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "sec-fetch-dest":  "image",
        "sec-fetch-mode":  "no-cors",
        "sec-fetch-site":  "cross-site",
    }


def _fetch_image(image_url: str) -> bytes:
    """Download, re-attaching headers through redirects (requests strips Referer by default)."""
    import requests as _requests
    headers = _build_headers(image_url)
    session = _requests.Session()
    session.headers.update(headers)

    def _reattach(resp, *args, **kwargs):
        if resp.is_redirect:
            resp.request.headers.update(headers)

    session.hooks["response"].append(_reattach)
    resp = session.get(image_url, timeout=15)
    resp.raise_for_status()
    return resp.content


def _remove_background(raw: bytes) -> bytes:
    """
    Attempt cloth segmentation first (isolates garment, removes model+background).
    Falls back to general U2Net if the cloth model is unavailable.
    """
    from rembg import remove

    cloth = _get_cloth_session()
    if cloth:
        try:
            result = remove(raw, session=cloth)
            # u2net_cloth_seg can return a fully-transparent image on some shots
            # (e.g. very complex backgrounds).  Detect that and fall back.
            from PIL import Image
            img = Image.open(io.BytesIO(result)).convert("RGBA")
            alpha_sum = sum(p[3] for p in img.getdata())
            if alpha_sum > 0:
                return result
            print("⚠️  cloth seg returned blank — falling back to u2net")
        except Exception as e:
            print(f"⚠️  cloth seg error: {e} — falling back to u2net")

    general = _get_general_session()
    if general:
        return remove(raw, session=general)
    return remove(raw)


def extract_clothing(image_url: str, slot: str | None = None) -> str | None:
    """
    Download image_url → remove background (cloth-seg model) → crop to garment region.
    Returns the absolute path of the cached transparent PNG, or None on failure.
    Repeat calls for the same (url, slot) pair are instant (disk cache).
    """
    out_path = _cache_path(image_url, slot)
    if os.path.exists(out_path):
        return out_path

    fail_key = (image_url, slot)
    if fail_key in _FAIL_CACHE:
        return None

    try:
        from PIL import Image

        raw = _fetch_image(image_url)
        result_bytes = _remove_background(raw)

        # Crop to the relevant garment region of the frame
        if slot and slot in _SLOT_CROP:
            img = Image.open(io.BytesIO(result_bytes)).convert("RGBA")
            w, h = img.size
            t, b = _SLOT_CROP[slot]
            img = img.crop((0, int(h * t), w, int(h * b)))

            # Auto-trim transparent padding so the garment fills the tile
            bbox = img.getbbox()
            if bbox:
                pad = 8
                x0 = max(0, bbox[0] - pad)
                y0 = max(0, bbox[1] - pad)
                x1 = min(w, bbox[2] + pad)
                y1 = min(img.height, bbox[3] + pad)
                img = img.crop((x0, y0, x1, y1))

            buf = io.BytesIO()
            img.save(buf, "PNG")
            result_bytes = buf.getvalue()

        with open(out_path, "wb") as f:
            f.write(result_bytes)

        print(f"✂️  extracted [{slot or '—'}] → {os.path.basename(out_path)}")
        return out_path

    except ImportError:
        print("⚠️  rembg not installed — run: pip install rembg onnxruntime Pillow")
        _FAIL_CACHE.add(fail_key)
        return None
    except Exception as e:
        short = str(e).split("\n")[0][:120]
        print(f"⛔ bg_remove skipped ({image_url[:60]}…): {short}")
        _FAIL_CACHE.add(fail_key)
        return None
