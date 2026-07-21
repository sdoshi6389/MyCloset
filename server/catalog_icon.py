"""
Catalog item icon extraction — tiered cost cascade:

  1. PIL white-bg removal (~0¢)   — clean product-on-white shots, no API call
  2. rembg cloth-seg     (~0¢)    — model photos, local garment segmentation
  3. Gemini Flash        (~1¢)    — complex shots, AI flat-lay generation
  4. gpt-image-1         (~7¢)    — last resort, highest quality

Image selection: if the product has multiple scraped images (images[]), the
cleanest one (fewest skin tones, most uniform background) is chosen before
any extraction step.

Results are cached on disk + Supabase so each unique (image_url, slot) is
processed at most once ever.
"""
import os
import hashlib
import tempfile
import base64

from bg_remove import CACHE_DIR, _build_headers, _remove_background

try:
    from replicate_icon_clothing import OPENAI_API_KEY
except Exception:
    try:
        from config import OPENAI_API_KEY
    except Exception:
        OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# Slot → plain-English description for isolation prompts
_SLOT_GARMENT = {
    "inner_top":    "the top, shirt, blouse, or t-shirt being worn",
    "outer_top":    "the jacket, coat, blazer, or outerwear being worn",
    "inner_bottom": "the pants, trousers, or jeans being worn",
    "outer_bottom": "the shorts, skirt, or bottom garment being worn",
    "left_shoe":    "the shoes or footwear shown",
    "right_shoe":   "the shoes or footwear shown",
    "hat":          "the hat, cap, or headwear shown",
    "necklace":     "the necklace, chain, choker, or neck accessory shown",
    "bracelet":     "the bracelet, bangle, cuff, or wristwatch shown",
    "bag":          "the bag, purse, handbag, or tote shown",
    "innerwear":    "the bra, bralette, camisole, or innerwear shown",
    "underwear":    "the underwear or undergarment shown",
    "left_sock":    "the socks or stockings shown",
}

_CLOTHING_SLOTS = {
    "inner_top", "outer_top", "inner_bottom", "outer_bottom", "innerwear", "underwear",
}

_BOTTOM_SLOTS = {"inner_bottom", "outer_bottom"}

# Category suffixes used by all brand scrapers — checked when looking up images[]
_TABLE_SUFFIXES = [
    "tops", "bottoms", "outerwear", "shoes", "accessories", "dresses",
    "jeans", "pants", "shirts", "jackets", "sweaters", "hoodies", "shorts",
    "skirts", "bags", "jewelry", "swimwear", "activewear", "coats", "sets",
]


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _icon_path(image_url: str, slot: str | None = None) -> str:
    key = f"gpt_v3|{image_url}|{slot or ''}"
    h = hashlib.md5(key.encode()).hexdigest()
    return os.path.join(CACHE_DIR, f"gptv3_{h}.png")


def _db_lookup(image_url: str, slot: str | None) -> str | None:
    cache_key = f"v3:{image_url}|{slot or ''}"
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
    cache_key = f"v3:{image_url}|{slot or ''}"
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


# ── Download ──────────────────────────────────────────────────────────────────

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


# ── Image cleanliness scorer ──────────────────────────────────────────────────

def _score_image_cleanliness(image_path: str) -> float:
    """
    Score 0.0–1.0: how likely this is a clean product shot with no model.
    Higher = whiter/more uniform background, fewer skin tones.
    Pure Pillow — no AI, costs nothing.
    """
    try:
        from PIL import Image
        import numpy as np

        with Image.open(image_path) as img:
            img = img.convert("RGB").resize((200, 200), Image.LANCZOS)

        arr = np.array(img, dtype=np.float32)  # (200, 200, 3)

        # ── Corner lightness: white/cream backgrounds score high ──────────
        patch = 25
        corners = [
            arr[:patch, :patch],
            arr[:patch, -patch:],
            arr[-patch:, :patch],
            arr[-patch:, -patch:],
        ]
        corner_brightness = np.mean([np.mean(c) for c in corners])
        corner_score = min(1.0, corner_brightness / 220.0)

        # ── Border uniformity: product shots have very uniform borders ────
        border = np.concatenate([
            arr[0, :].reshape(-1, 3),
            arr[-1, :].reshape(-1, 3),
            arr[:, 0].reshape(-1, 3),
            arr[:, -1].reshape(-1, 3),
        ])
        uniformity_score = max(0.0, 1.0 - float(np.std(border)) / 60.0)

        # ── Skin tone penalty ─────────────────────────────────────────────
        # Convert RGB → rough HSV via numpy to avoid extra imports
        r, g, b = arr[:, :, 0] / 255.0, arr[:, :, 1] / 255.0, arr[:, :, 2] / 255.0
        cmax = np.maximum(np.maximum(r, g), b)
        cmin = np.minimum(np.minimum(r, g), b)
        delta = cmax - cmin
        # Hue (0-360)
        h = np.zeros_like(r)
        mask_r = (cmax == r) & (delta > 0)
        mask_g = (cmax == g) & (delta > 0)
        mask_b = (cmax == b) & (delta > 0)
        h[mask_r] = (60 * ((g[mask_r] - b[mask_r]) / delta[mask_r])) % 360
        h[mask_g] = 60 * ((b[mask_g] - r[mask_g]) / delta[mask_g]) + 120
        h[mask_b] = 60 * ((r[mask_b] - g[mask_b]) / delta[mask_b]) + 240
        # Saturation
        s = np.where(cmax > 0, delta / cmax, 0.0)
        # Skin: hue 0–25 or 340–360, moderate saturation and brightness
        skin_mask = (
            ((h <= 25) | (h >= 340)) &
            (s > 0.15) & (s < 0.85) &
            (cmax > 0.30) & (cmax < 0.95)
        )
        skin_fraction = float(np.mean(skin_mask))
        skin_penalty = min(1.0, skin_fraction * 5.0)

        score = (corner_score * 0.50 + uniformity_score * 0.30) * (1.0 - skin_penalty * 0.65)
        return float(np.clip(score, 0.0, 1.0))

    except Exception as e:
        print(f"⚠️  cleanliness score failed: {e}")
        return 0.5  # neutral — don't block the pipeline


# ── Product images lookup ─────────────────────────────────────────────────────

def _get_product_images(product_url: str, source_brand: str | None) -> list[str] | None:
    """
    Look up the images[] array for a product URL by trying known brand table names.
    Returns list of image URLs or None.
    """
    if not source_brand or not product_url:
        return None
    try:
        from db import get_supa
        supa = get_supa()
        for suffix in _TABLE_SUFFIXES:
            table = f"products_{source_brand}_{suffix}"
            try:
                r = supa.table(table).select("images").eq("url", product_url).limit(1).execute()
                if r.data and r.data[0].get("images"):
                    imgs = r.data[0]["images"]
                    if isinstance(imgs, list) and len(imgs) > 1:
                        return imgs
            except Exception:
                continue
    except Exception as e:
        print(f"⚠️  _get_product_images: {e}")
    return None


# ── Smart image selection ─────────────────────────────────────────────────────

def _select_best_image(main_image_url: str,
                       product_url: str | None = None,
                       source_brand: str | None = None) -> tuple[str, str | None]:
    """
    Find the cleanest image from the product's images[] array.
    Returns (best_url, temp_file_path_or_None).
    temp file is already downloaded — caller must delete it.
    Falls back to (main_image_url, None) if nothing better found.
    """
    candidates = _get_product_images(product_url or "", source_brand)
    if not candidates:
        return main_image_url, None

    # Limit to first 6 to avoid too many downloads
    candidates = candidates[:6]
    print(f"🔎 Scoring {len(candidates)} product images for cleanliness…")

    best_url   = main_image_url
    best_score = -1.0
    best_tmp   = None
    all_tmps   = []

    for url in candidates:
        tmp = _download(url)
        if not tmp:
            continue
        all_tmps.append(tmp)
        score = _score_image_cleanliness(tmp)
        print(f"   score={score:.2f}  {url[:70]}")
        if score > best_score:
            best_score = score
            best_url   = url
            best_tmp   = tmp

    # Clean up all temp files except the winner
    for t in all_tmps:
        if t != best_tmp:
            try:
                os.unlink(t)
            except Exception:
                pass

    print(f"✅ Best image (score={best_score:.2f}): {best_url[:70]}")
    return best_url, best_tmp



# ── PIL white-background removal (for Gemini output) ─────────────────────────

def _try_pil_extract(source_path: str, out_path: str) -> bool:
    """
    Free, instant white-background removal using PIL only.
    Only succeeds when the source image has near-white corners (clean product shot).
    Returns False for model photos with complex backgrounds so they escalate to GPT.
    """
    try:
        from PIL import Image
        import numpy as np

        img = Image.open(source_path).convert("RGBA")
        arr = np.array(img, dtype=np.float32)
        rgb = arr[:, :, :3]
        h, w = arr.shape[:2]

        # Gate: corners must be near-white (≥215 avg brightness).
        # Dark/colored corners = model photo with complex background → skip PIL.
        patch = max(20, min(40, h // 10, w // 10))
        corners = np.concatenate([
            rgb[:patch, :patch].reshape(-1, 3),
            rgb[:patch, -patch:].reshape(-1, 3),
            rgb[-patch:, :patch].reshape(-1, 3),
            rgb[-patch:, -patch:].reshape(-1, 3),
        ])
        corner_brightness = float(np.mean(corners))
        if corner_brightness < 215:
            print(f"   PIL skip: corners too dark ({corner_brightness:.0f}/255) — not a white-bg shot")
            return False

        # Remove background: pixels with all channels ≥ 238 become transparent
        bg = np.all(rgb >= 238, axis=2)
        alpha = np.where(bg, 0, 255).astype(np.uint8)
        arr[:, :, 3] = alpha

        # Garment should occupy a reasonable slice of the canvas
        fg_ratio = float(np.mean(alpha > 128))
        if fg_ratio < 0.03 or fg_ratio > 0.92:
            print(f"   PIL skip: bad fg coverage ({fg_ratio:.0%})")
            return False

        result = Image.fromarray(arr.astype(np.uint8))
        bbox = result.getbbox()
        if bbox:
            pad = 20
            result = result.crop((
                max(0, bbox[0] - pad), max(0, bbox[1] - pad),
                min(w, bbox[2] + pad), min(h, bbox[3] + pad),
            ))

        result.save(out_path, "PNG")
        print(f"✅ catalog icon (PIL) → {os.path.basename(out_path)}  "
              f"corners={corner_brightness:.0f} fg={fg_ratio:.0%}")
        return True
    except Exception as e:
        print(f"⚠️  _try_pil_extract failed: {e}")
        return False


def _rembg_extract(source_path: str, out_path: str) -> bool:
    """
    Run rembg cloth-seg → quality check → save.
    Returns True only if result looks like a clean single-garment extraction
    with no visible skin (person removed).
    """
    try:
        import io as _io
        from PIL import Image as _Img
        import numpy as _np

        with open(source_path, "rb") as f:
            raw = f.read()

        result_bytes = _remove_background(raw)
        img = _Img.open(_io.BytesIO(result_bytes)).convert("RGBA")
        arr = _np.array(img)
        alpha = arr[:, :, 3]
        h, w = alpha.shape

        # Corners of a good extraction should be transparent
        patch = min(30, h // 8, w // 8)
        corner_alpha = _np.concatenate([
            alpha[:patch, :patch].ravel(), alpha[:patch, -patch:].ravel(),
            alpha[-patch:, :patch].ravel(), alpha[-patch:, -patch:].ravel(),
        ])
        corner_transparency = float(_np.mean(corner_alpha < 10))
        foreground_coverage  = float(_np.mean(alpha > 128))

        # Skin-tone check: u2net (fallback) keeps the person; cloth_seg doesn't.
        # If skin ratio is high, the person wasn't removed — escalate.
        visible_mask  = alpha > 128
        visible_count = int(visible_mask.sum())
        skin_ratio = 0.0
        if visible_count > 0:
            rgb = arr[:, :, :3].astype(_np.float32) / 255.0
            r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
            skin_px = (
                (r > 0.35) & (r > g * 1.05) & (r > b * 1.10) &
                (g > 0.15) & (b > 0.05) & (r - b > 0.10) & visible_mask
            )
            skin_ratio = float(skin_px.sum()) / visible_count

        passes = (
            corner_transparency > 0.72 and
            0.03 < foreground_coverage < 0.93 and
            skin_ratio < 0.12
        )

        if passes:
            bbox = img.getbbox()
            if bbox:
                pad = 20
                img = img.crop((
                    max(0, bbox[0] - pad), max(0, bbox[1] - pad),
                    min(w, bbox[2] + pad), min(h, bbox[3] + pad),
                ))
            buf = _io.BytesIO()
            img.save(buf, "PNG")
            with open(out_path, "wb") as f:
                f.write(buf.getvalue())
            print(f"✅ catalog icon (rembg) → {os.path.basename(out_path)}  "
                  f"corners={corner_transparency:.0%} fg={foreground_coverage:.0%} skin={skin_ratio:.0%}")
        else:
            print(f"⚠️  rembg quality check failed  "
                  f"corners={corner_transparency:.0%} fg={foreground_coverage:.0%} "
                  f"skin={skin_ratio:.0%} — escalating to Gemini")

        return passes

    except Exception as e:
        print(f"⚠️  _rembg_extract failed: {e}")
        return False


# ── Gemini ───────────────────────────────────────────────────────────────────
# Two modes:
#   A. Image generation  — send photo + prompt, receive flat-lay PNG  (~1¢)
#   B. Vision locator    — ask for bbox, crop, run PIL/rembg on crop  (~0.05¢)
#
# Both use gemini-2.5-flash exclusively.

_GEMINI_MODEL = "gemini-2.5-flash-image"
_GEMINI_API_VER = "v1beta"


def _build_prompt(slot: str | None, product_name: str | None = None) -> str:
    item_desc = _SLOT_GARMENT.get(slot, "the main item") if slot else "the main item"
    name_clause = f" (the product is called '{product_name}')" if product_name else ""

    if slot in _BOTTOM_SLOTS:
        return (
            f"Extract ONLY {item_desc}{name_clause} from this photo. "
            "This is a BOTTOM garment (pants, jeans, trousers, shorts, skirt). "
            "CRITICAL RULES — you must follow ALL of these exactly: "
            "(1) Show ONLY the bottom garment — absolutely nothing else. "
            "(2) NO shirt, blouse, top, jacket, or any upper-body garment may appear anywhere in the output — not even partially at the top edge. The output must be pants/skirt only. "
            "(3) The TOP edge of the output image must be the waistband of the pants — nothing above the waistband. "
            "(4) The BOTTOM edge must be the hem of the pants/skirt — do NOT include feet, shoes, or legs below the hem. "
            "(5) No skin, no body parts — only the fabric of the garment. "
            "(6) Re-present the garment as a flat-lay (lying flat) or ghost-mannequin view — front-facing, legs straight and symmetrical. "
            "(7) The garment must fill at least 80% of the image height. "
            "Keep exact color, fabric, pockets, stitching, and details unchanged. "
            "Output as a PNG with a fully transparent background."
        )

    if slot in _CLOTHING_SLOTS:
        return (
            f"Extract ONLY {item_desc}{name_clause} from this photo. "
            "CRITICAL: If the photo shows multiple garments worn together (e.g. a jacket + jeans + shoes, or a shirt + pants), "
            f"you must extract ONLY {item_desc}{name_clause} — do NOT include any other clothing items, "
            "pants, shirts, shoes, accessories, or body parts in the output. One garment only. "
            "Keep its exact color, pattern, print, logo, and fabric texture completely unchanged. "
            "Remove the person, model, mannequin, all other garments, background, and shadows. "
            "Re-pose the single garment into a flat-lay or ghost-mannequin product-catalog view — "
            "front-facing, symmetrical, sleeves and hems straightened. "
            "Center it large so it fills at least 80% of the image height. "
            "Output as a PNG with a fully transparent background — no white, no color fill, no shadow behind the garment."
        )

    return (
        f"Extract ONLY {item_desc}{name_clause} from this photo — nothing else. "
        "If other items appear in the photo, ignore them completely. "
        "Keep its exact color, design, logo, and material unchanged. "
        "Remove the person, background, shadows, and any other objects. "
        "Present the single item centered large, filling at least 75% of the image, as in an e-commerce product catalog. "
        "Output as a PNG with a fully transparent background — no white, no color fill, no shadow behind the item."
    )


def _call_gemini_vision(source_path: str, slot: str | None, out_path: str,
                        product_name: str | None = None) -> str | None:
    """
    Uses Gemini text/vision to locate the target garment's bounding box, crops
    the image to just that garment, then runs PIL white-bg removal + rembg on
    the tight crop.  Cost: ~$0.0005/call.
    """
    if not GEMINI_API_KEY:
        print("⚠️  GEMINI_API_KEY not set — skipping Gemini step")
        return None

    import requests as _req
    import json
    import re
    import tempfile
    from PIL import Image as _Img

    item_desc = _SLOT_GARMENT.get(slot, "the main item") if slot else "the main item"
    name_clause = f" (product: '{product_name}')" if product_name else ""

    # Convert to JPEG (smaller payload)
    jpeg_path = source_path + "_gvision.jpg"
    try:
        with _Img.open(source_path) as img:
            img.convert("RGB").save(jpeg_path, "JPEG", quality=85)
    except Exception as e:
        print(f"⚠️  Gemini vision JPEG: {e}")
        return None

    with open(jpeg_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode()

    is_bottom = slot in _BOTTOM_SLOTS
    bottom_extra = (
        " IMPORTANT: this is a BOTTOM garment (pants/jeans/skirt). "
        "Set 'top' to the waistband — do NOT include the upper body, torso, or any shirt. "
        "Set 'bottom' to the hem of the pants/skirt. Exclude feet and shoes."
    ) if is_bottom else ""

    locate_prompt = (
        f"This is a clothing product image. Find the bounding box of ONLY {item_desc}{name_clause}.{bottom_extra} "
        "RULES: "
        "(1) Return a box for ONE garment only. "
        "(2) If the photo shows multiple garments (e.g. jacket + jeans + shoes), "
        f"include ONLY {item_desc}{name_clause} — exclude all other clothing, body parts, and background. "
        "(3) Use a 0–1000 coordinate scale: top-left=(0,0), bottom-right=(1000,1000). "
        "(4) Add 25 units of padding on each side so you don't clip the garment edges. "
        "Reply with ONLY a JSON object — no explanation, no markdown. "
        'Format: {"top": N, "left": N, "bottom": N, "right": N}'
    )

    payload = {
        "contents": [{"parts": [
            {"text": locate_prompt},
            {"inline_data": {"mime_type": "image/jpeg", "data": image_b64}},
        ]}],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 80},
    }

    gv_url = (f"https://generativelanguage.googleapis.com/{_GEMINI_API_VER}/models/"
              f"{_GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}")
    resp = None
    try:
        r = _req.post(gv_url, json=payload, timeout=20)
        if r.ok:
            resp = r
        else:
            print(f"⚠️  Gemini vision {_GEMINI_MODEL}: {r.status_code} {r.text[:150]}")
    except Exception as e:
        print(f"⚠️  Gemini vision {_GEMINI_MODEL}: {e}")

    try:
        if resp is None:
            print("⚠️  Gemini vision: request failed — escalating to gpt-image-1")
            return None

        raw_text = ""
        for cand in resp.json().get("candidates", []):
            for part in cand.get("content", {}).get("parts", []):
                raw_text += part.get("text", "")

        json_match = re.search(r'\{[^}]+\}', raw_text)
        if not json_match:
            print(f"⚠️  Gemini vision: no JSON returned: {raw_text[:200]}")
            return None

        bbox = json.loads(json_match.group())
        top    = max(0,    int(bbox.get("top",    bbox.get("y1", 0))))
        left   = max(0,    int(bbox.get("left",   bbox.get("x1", 0))))
        bottom = min(1000, int(bbox.get("bottom", bbox.get("y2", 1000))))
        right  = min(1000, int(bbox.get("right",  bbox.get("x2", 1000))))

        if bottom - top < 50 or right - left < 50:
            print(f"⚠️  Gemini vision: bbox too small ({right-left}×{bottom-top})")
            return None

        print(f"   Gemini ({_GEMINI_MODEL}) bbox → "
              f"top={top} left={left} bottom={bottom} right={right}")

        # Crop to the detected garment region
        img = _Img.open(source_path).convert("RGBA")
        iw, ih = img.size
        cx1 = max(0,  int(left   / 1000.0 * iw))
        cy1 = max(0,  int(top    / 1000.0 * ih))
        cx2 = min(iw, int(right  / 1000.0 * iw))
        cy2 = min(ih, int(bottom / 1000.0 * ih))

        if cx2 - cx1 < 20 or cy2 - cy1 < 20:
            print(f"⚠️  Gemini vision: pixel crop too small ({cx2-cx1}×{cy2-cy1})")
            return None

        cropped = img.crop((cx1, cy1, cx2, cy2))
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        cropped.save(tmp.name, "PNG")
        tmp.close()

        try:
            method = None
            if _try_pil_extract(tmp.name, out_path):
                method = "PIL"
            elif _rembg_extract(tmp.name, out_path):
                method = "rembg"

            if method:
                from cost_log import log_image_cost
                log_image_cost("gemini-2.0-flash", size="vision", fidelity=None,
                               call_type="catalog_icon_gemini_vision",
                               context=os.path.basename(out_path))
                print(f"✅ catalog icon (Gemini Vision + {method}) → {os.path.basename(out_path)}")
                return out_path

            print("⚠️  Gemini vision: crop extraction failed — escalating to gpt-image-1")
            return None
        finally:
            try:
                os.unlink(tmp.name)
            except Exception:
                pass

    except Exception as e:
        print(f"⚠️  _call_gemini_vision failed ({type(e).__name__}): {e}")
        return None
    finally:
        try:
            os.unlink(jpeg_path)
        except Exception:
            pass


def _call_gemini_image(source_path: str, slot: str | None, out_path: str,
                       product_name: str | None = None) -> str | None:
    """
    Send the image + prompt to gemini-2.5-flash-image for image-output generation.
    Receives a flat-lay PNG, strips white background.  ~1¢/call on paid plans.
    Returns None if the model returns no image (e.g. image-output not enabled).
    """
    import requests as _req

    jpeg_path = source_path + "_gimg.jpg"
    try:
        from PIL import Image as _Img
        with _Img.open(source_path) as img:
            img.convert("RGB").save(jpeg_path, "JPEG", quality=90)
    except Exception as e:
        print(f"⚠️  Gemini image JPEG: {e}")
        return None

    with open(jpeg_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode()

    prompt = _build_prompt(slot, product_name)
    payload = {
        "contents": [{"parts": [
            {"text": prompt},
            {"inline_data": {"mime_type": "image/jpeg", "data": image_b64}},
        ]}],
        "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]},
    }

    try:
        url = (f"https://generativelanguage.googleapis.com/{_GEMINI_API_VER}/models/"
               f"{_GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}")
        try:
            resp = _req.post(url, json=payload, timeout=60)
        except Exception as re:
            print(f"⚠️  Gemini image request error: {re}")
            return None

        if not resp.ok:
            print(f"⚠️  Gemini image {_GEMINI_MODEL}: {resp.status_code} — {resp.text[:200]}")
            return None

        data = resp.json()
        img_bytes = None
        for cand in data.get("candidates", []):
            for part in cand.get("content", {}).get("parts", []):
                if "inlineData" in part:
                    img_bytes = base64.b64decode(part["inlineData"].get("data", ""))
                    break
            if img_bytes:
                break

        if not img_bytes:
            print(f"⚠️  Gemini image ({_GEMINI_MODEL}): no image in response — falling through to vision locator")
            return None

        import io as _io
        import numpy as _np
        from PIL import Image as _Img

        gemini_out = _Img.open(_io.BytesIO(img_bytes)).convert("RGBA")

        # Flood-fill background removal — two passes.
        #
        # Pass 1 (exterior): remove near-white pixels (≥200) connected to any corner.
        #   Preserves white/light garment fabric that sits in the centre of the frame.
        #
        # Pass 2 (interior holes): any remaining near-white region with NO pixel
        #   adjacent to the transparent exterior is a sealed interior hole (e.g. the
        #   inside of a ring/loop necklace or bracelet) — remove it too.
        #   White garment fabric always borders the transparent exterior at its
        #   silhouette edge so it is never mistaken for a hole.
        arr = _np.array(gemini_out, dtype=_np.uint8)
        h, w = arr.shape[:2]
        near_white = _np.all(arr[:, :, :3].astype(_np.float32) >= 200, axis=2)
        try:
            from scipy import ndimage as _ndi
            # Pass 1 — exterior bg
            labeled, _ = _ndi.label(near_white)
            corner_labels = {
                int(labeled[cy, cx])
                for cy, cx in [(0,0),(0,w-1),(h-1,0),(h-1,w-1)]
                if labeled[cy, cx] > 0
            }
            bg_mask = _np.isin(labeled, list(corner_labels)) if corner_labels else near_white
            out = arr.copy()
            out[:, :, 3] = _np.where(bg_mask, 0, 255).astype(_np.uint8)
            # Pass 2 — enclosed interior holes (ring/loop shapes)
            near_white_opaque = near_white & (out[:, :, 3] > 0)
            if near_white_opaque.any():
                transp_dilated = _ndi.binary_dilation(out[:, :, 3] == 0)
                labeled2, num2 = _ndi.label(near_white_opaque)
                for lbl in range(1, num2 + 1):
                    comp = labeled2 == lbl
                    if not (comp & transp_dilated).any():
                        out[:, :, 3][comp] = 0
        except ImportError:
            out = arr.copy()
            out[:, :, 3] = _np.where(near_white, 0, 255).astype(_np.uint8)
        result = _Img.fromarray(out)
        print(f"   flood-fill bg removal (slot={slot})")

        gw, gh = result.size
        bbox = result.getbbox()
        if bbox:
            pad = 20
            result = result.crop((max(0, bbox[0]-pad), max(0, bbox[1]-pad),
                                  min(gw, bbox[2]+pad), min(gh, bbox[3]+pad)))
        result.save(out_path, "PNG")

        from cost_log import log_image_cost
        log_image_cost(_GEMINI_MODEL, size="1024x1024", fidelity=None,
                       call_type="catalog_icon_gemini_image", context=os.path.basename(out_path))
        print(f"✅ catalog icon (Gemini/{_GEMINI_MODEL}) → {os.path.basename(out_path)}")
        return out_path

    except Exception as e:
        print(f"⚠️  _call_gemini_image failed ({type(e).__name__}): {e}")
        return None
    finally:
        try:
            os.unlink(jpeg_path)
        except Exception:
            pass


# ── gpt-image-1 (last resort — UNCHANGED) ────────────────────────────────────

def _call_gpt(source_path: str, slot: str | None, out_path: str) -> str | None:
    """Call gpt-image-1 edit to isolate and re-pose the garment."""
    import openai
    import requests as _req
    from PIL import Image
    from cost_log import log_image_cost

    prompt = _build_prompt(slot).replace("plain white background", "fully transparent background")

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

        # Trim transparent margins
        import io as _io
        try:
            _img = Image.open(_io.BytesIO(img_bytes)).convert("RGBA")
            bbox = _img.getbbox()
            if bbox:
                pad = 20
                w, h = _img.size
                _img = _img.crop((
                    max(0, bbox[0] - pad),
                    max(0, bbox[1] - pad),
                    min(w, bbox[2] + pad),
                    min(h, bbox[3] + pad),
                ))
                buf = _io.BytesIO()
                _img.save(buf, "PNG")
                img_bytes = buf.getvalue()
                print(f"   trimmed to {_img.size[0]}×{_img.size[1]}")
        except Exception as _te:
            print(f"⚠️  catalog_icon trim failed: {_te}")

        with open(out_path, "wb") as f:
            f.write(img_bytes)
        log_image_cost("gpt-image-1", size="1024x1024", fidelity="high",
                       call_type="catalog_icon_edit", context=os.path.basename(out_path))
        print(f"✅ catalog icon (gpt-image-1) → {os.path.basename(out_path)}")
        return out_path

    except Exception as e:
        print(f"⚠️  catalog_icon gpt-image-1 failed: {e}")
        return None
    finally:
        try:
            os.unlink(png_path)
        except Exception:
            pass


# ── Public entry point ────────────────────────────────────────────────────────

def extract_catalog_icon(image_url: str,
                         slot: str | None = None,
                         product_url: str | None = None,
                         source_brand: str | None = None,
                         product_name: str | None = None,
                         force_step: int = 0) -> tuple[str | None, int]:
    """
    Returns (local_path | None, step_used) where step_used is:
      -1 = served from cache (no extraction ran)
       0 = PIL white-bg removal
       1 = rembg cloth-seg
       2 = Gemini
       3 = gpt-image-1
    """
    out_path = _icon_path(image_url, slot)
    if os.path.exists(out_path):
        return out_path, -1

    cached = _db_lookup(image_url, slot)
    if cached:
        return cached, -1

    # Pick the cleanest available image for this product
    best_url, best_tmp = _select_best_image(image_url, product_url, source_brand)

    # Download best image if not already a temp file
    if best_tmp is None:
        best_tmp = _download(best_url)
    if not best_tmp:
        return None, -1

    try:
        # ── Step 0: PIL white-bg removal (free, ~0¢) ─────────────────────
        if force_step <= 0 and _try_pil_extract(best_tmp, out_path):
            _db_save(image_url, slot, out_path)
            return out_path, 0

        # ── Step 1: rembg cloth-seg (~0¢ local) ──────────────────────────
        if force_step <= 1 and _rembg_extract(best_tmp, out_path):
            _db_save(image_url, slot, out_path)
            return out_path, 1

        # ── Step 2: Gemini (~1¢) ─────────────────────────────────────────
        if force_step <= 2:
            result = _call_gemini_image(best_tmp, slot, out_path, product_name)
            if result is None:
                result = _call_gemini_vision(best_tmp, slot, out_path, product_name)
            if result:
                _db_save(image_url, slot, result)
                return result, 2

        # ── Step 3: gpt-image-1 (last resort, ~7¢) ───────────────────────
        result = _call_gpt(best_tmp, slot, out_path)
        if result:
            _db_save(image_url, slot, result)
            return result, 3

        return None, -1

    finally:
        try:
            os.unlink(best_tmp)
        except Exception:
            pass
