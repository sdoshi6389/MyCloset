"""
Clothing AI pipeline:
  Step 1 — GPT-4o Vision analysis (rich metadata + emoji_prompt)
  Step 2 — gpt-image-1 icon generation (transparent background PNG)
  Step 3 — Write metadata + icon_path to DB
  Step 4 — gpt-image-1 emoji sticker (emoticon_path, optional bonus)

All steps are independent. Failure in one does not block the others.
"""
import openai
import os
import requests
import json
import base64
from PIL import Image
from io import BytesIO

try:
    from config import OPENAI_API_KEY as _CFG_OAK
    OPENAI_API_KEY = _CFG_OAK or "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"
except ImportError:
    OPENAI_API_KEY = "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"

SYSTEM_PROMPT = """\
You are an expert fashion stylist, apparel merchandiser, and clothing cataloging system.

Analyze the clothing item shown in the image and return ONLY a valid raw JSON object.

Do not return markdown.
Do not return explanations.
Do not wrap the JSON in code fences.

If a field cannot be confidently determined, return null.

Your goal is not only to describe the clothing item but to generate rich metadata that can later be used for:

* Outfit recommendations
* Similar-item search
* Closet organization
* Fashion analytics
* AI outfit generation
* Vector embeddings
* Clothing emoji generation

Return the following JSON schema:

{
  "caption": string,
  "back_tag_text": string | null,
  "brand": string | null,

  "category": string,
  "subcategory": string,
  "type": string,

  "primary_color": string,
  "secondary_colors": [string],

  "pattern": string | null,

  "fabric": string | null,
  "material_composition": [string],

  "fit": string,
  "silhouette": string,

  "sleeve_length": string | null,
  "neckline": string | null,

  "style": [string],
  "aesthetic": [string],

  "occasion": [string],

  "season": [string],

  "gender": string,

  "formality_score": integer,

  "visual_weight": string,

  "layering_role": string,

  "body_zone": string,

  "dominant_features": [string],

  "recommended_pairings": [string],

  "compatible_styles": [string],

  "vibe": [string],

  "keywords": [string],

  "search_tags": [string],

  "emoji_prompt": string
}

Field Guidelines:

category: top | bottom | outerwear | footwear | accessory

subcategory examples: hoodie, crewneck, polo, jeans, cargo_pants, shorts, sneakers, necklace

fit: slim | regular | relaxed | oversized | boxy | athletic

silhouette: fitted | straight | tapered | boxy | cropped | oversized

formality_score: Integer 1-10. 1=gymwear, 3=casual, 5=smart casual, 7=business casual, 10=formalwear

visual_weight: very_light | light | medium | heavy | very_heavy

layering_role: base_layer | mid_layer | outer_layer | standalone

body_zone: head | neck | torso | legs | feet | accessory

occasion examples: casual, campus, office, date, formal, gym, lounge, travel

season: Can contain multiple values, e.g. ["spring","summer"] or ["fall","winter"]

recommended_pairings: Generic clothing pairings that work well with this item.
Example: ["light_wash_jeans", "white_sneakers", "silver_chain"]

brand: Extract the brand name from any visible tag, label, logo, or text on the garment. Use back_tag_text to identify it. Return null if no brand is visible.

compatible_styles: e.g. ["streetwear", "minimalist", "casual"]

emoji_prompt: Generate a concise image-generation prompt describing ONLY this clothing item as a centered icon on a transparent background.
Requirements: clothing item only, transparent background, no mannequin, no human, no text, no hanger, no shadows, front-facing, clean sticker style, high detail, isolated object.
Example: "minimalist sticker icon of a navy blue oversized hoodie, front facing, transparent background, isolated clothing item, no mannequin, no human, clean vector style"

Return ONLY raw JSON.\
"""

# === Type → Category mapping =====================================================
TYPE_TO_CATEGORY = {
    "t-shirt": "Tops", "tshirt": "Tops", "shirt": "Tops", "blouse": "Tops",
    "top": "Tops", "hoodie": "Tops", "sweatshirt": "Tops", "polo": "Tops",
    "tank top": "Tops", "tank": "Tops", "turtleneck": "Tops", "sweater": "Tops",
    "cardigan": "Tops", "pullover": "Tops", "crop top": "Tops", "long sleeve": "Tops",
    "flannel": "Tops", "henley": "Tops", "jersey": "Tops", "graphic tee": "Tops",
    "button-up": "Tops", "button up": "Tops", "dress shirt": "Tops",
    "pants": "Bottoms", "jeans": "Bottoms", "shorts": "Bottoms", "trousers": "Bottoms",
    "skirt": "Bottoms", "joggers": "Bottoms", "leggings": "Bottoms",
    "sweatpants": "Bottoms", "chinos": "Bottoms", "cargo pants": "Bottoms",
    "slacks": "Bottoms", "cargo shorts": "Bottoms", "midi skirt": "Bottoms",
    "romper": "Bottoms", "jumpsuit": "Bottoms",
    "jacket": "Outerwear", "coat": "Outerwear", "blazer": "Outerwear",
    "puffer": "Outerwear", "puffer jacket": "Outerwear", "windbreaker": "Outerwear",
    "vest": "Outerwear", "parka": "Outerwear", "trench coat": "Outerwear",
    "bomber": "Outerwear", "bomber jacket": "Outerwear", "raincoat": "Outerwear",
    "denim jacket": "Outerwear", "leather jacket": "Outerwear",
    "shoes": "Shoes", "sneakers": "Shoes", "boots": "Shoes", "sandals": "Shoes",
    "heels": "Shoes", "loafers": "Shoes", "flats": "Shoes", "slides": "Shoes",
    "oxfords": "Shoes", "trainers": "Shoes", "running shoes": "Shoes",
    "hat": "Accessories", "cap": "Accessories", "scarf": "Accessories",
    "belt": "Accessories", "bag": "Accessories", "sunglasses": "Accessories",
    "watch": "Accessories", "jewelry": "Accessories", "gloves": "Accessories",
    "beanie": "Accessories", "backpack": "Accessories", "tote": "Accessories",
    "handbag": "Accessories", "purse": "Accessories",
    "underwear": "Innerwear", "bra": "Innerwear", "boxers": "Innerwear",
    "briefs": "Innerwear", "sports bra": "Innerwear", "undershirt": "Innerwear",
    "dress": "Tops", "midi dress": "Tops", "maxi dress": "Tops", "mini dress": "Tops",
    "athletic leggings": "Bottoms", "trackpant": "Bottoms", "track pants": "Bottoms",
}

def infer_category(type_str):
    if not type_str:
        return None
    tl = type_str.lower().strip()
    if tl in TYPE_TO_CATEGORY:
        return TYPE_TO_CATEGORY[tl]
    for key, cat in TYPE_TO_CATEGORY.items():
        if key in tl:
            return cat
    return None


def encode_image_to_base64(image_path):
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


# === Step 1: GPT-4o Vision analysis =============================================
def analyze_image_with_gpt(image_path, tag_text=None):
    """Returns a rich dict of clothing attributes. Raises on API error."""
    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    base64_img = encode_image_to_base64(image_path)

    if tag_text:
        print(f"🏷️  GPT mode: OCR-assisted  (tag_text='{tag_text}')")
        user_text = (
            f"Analyze this clothing item. OCR detected the following tag text: \"{tag_text}\". "
            "Use it to help identify the brand and fill in back_tag_text and brand fields."
        )
    else:
        print("🔍 GPT mode: visual tag scan (OCR found nothing — asking GPT to read tag from image)")
        user_text = (
            "Analyze this clothing item. "
            "No tag text was detected by OCR. "
            "Please carefully inspect the ENTIRE image — look for any clothing tags, care labels, "
            "neck labels, woven logos, embroidered text, or printed brand names anywhere on the garment. "
            "Read whatever you can find and fill in back_tag_text with the raw tag text and brand with "
            "the brand name. If you genuinely cannot find any brand or tag text, return null for both."
        )

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"}},
                ],
            },
        ],
        temperature=0.4,
        max_tokens=1500,
    )

    text = response.choices[0].message.content.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    return json.loads(text)


# === Step 2: GPT icon generation (transparent background) =======================
def generate_icon_via_gpt(icon_prompt, output_dir="icon_outputs"):
    """
    Generate a clean transparent-background PNG icon for a clothing item.
    Uses gpt-image-1 with background=transparent, falls back to dall-e-3.
    Returns local file path or None.
    """
    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    os.makedirs(output_dir, exist_ok=True)
    safe = icon_prompt[:60].replace(" ", "_").replace("/", "_").replace(":", "")
    out_path = os.path.join(output_dir, f"icon_{safe}.png")

    # ── Try gpt-image-1 with transparent background ──────────────────────────
    try:
        response = client.images.generate(
            model="gpt-image-1",
            prompt=icon_prompt,
            size="1024x1024",
            background="transparent",
            n=1,
        )
        item = response.data[0]
        b64 = getattr(item, "b64_json", None)
        if b64:
            img_bytes = base64.b64decode(b64)
        elif getattr(item, "url", None):
            img_bytes = requests.get(item.url, timeout=60).content
        else:
            raise ValueError("No image data in gpt-image-1 response")

        img = Image.open(BytesIO(img_bytes))
        img.save(out_path, "PNG")
        print(f"✅ gpt-image-1 icon saved: {out_path}")
        return out_path
    except Exception as e:
        print(f"⚠️  gpt-image-1 failed ({type(e).__name__}): {e} — trying dall-e-3")

    # ── Fallback: dall-e-3 (opaque, but clean illustration) ──────────────────
    try:
        response = client.images.generate(
            model="dall-e-3",
            prompt=icon_prompt,
            size="1024x1024",
            quality="standard",
            n=1,
        )
        item = response.data[0]
        img_bytes = requests.get(item.url, timeout=60).content
        img = Image.open(BytesIO(img_bytes))
        img.save(out_path, "PNG")
        print(f"✅ DALL-E 3 icon saved (opaque fallback): {out_path}")
        return out_path
    except Exception as e:
        print(f"⚠️  DALL-E 3 fallback failed ({type(e).__name__}): {e}")
        return None


# === Helpers ====================================================================
def _serialize(val):
    if val is None:
        return None
    if isinstance(val, (list, tuple)):
        return ", ".join(str(v) for v in val) if val else None
    return str(val) if val else None


# === Step 3: DB write ===========================================================
def _save_to_db(user_id, filename, icon_path, gpt_tags, category):
    caption   = gpt_tags.get("caption") or ""
    back_tag  = gpt_tags.get("back_tag_text") or ""
    brand     = gpt_tags.get("brand") or back_tag or "Unknown"
    item_type = gpt_tags.get("type")
    color     = gpt_tags.get("primary_color") or gpt_tags.get("color")
    style     = _serialize(gpt_tags.get("style"))
    season    = _serialize(gpt_tags.get("season"))
    fabric    = gpt_tags.get("fabric")
    vibe      = _serialize(gpt_tags.get("vibe"))
    gender    = gpt_tags.get("gender")
    keywords  = _serialize(gpt_tags.get("keywords"))

    from db import get_supa
    supa = get_supa()

    # Use GPT caption as the initial item name (overwritten later by FAISS match or user edit)
    item_name = caption if caption else None

    # Fetch current row so we can COALESCE in Python (don't overwrite existing values)
    existing_res = supa.table("closet_items").select(
        "icon_path, caption, brand, type, color, style, season, fabric, vibe, gender, keywords, category, matched_title"
    ).eq("user_id", user_id).eq("filename", filename).execute()
    ex = existing_res.data[0] if existing_res.data else {}

    def _coalesce(new_val, old_val):
        return new_val if new_val else old_val

    supa.table("closet_items").update({
        "icon_path":     _coalesce(icon_path,  ex.get("icon_path")),
        "caption":       _coalesce(caption,    ex.get("caption")),
        "brand":         _coalesce(brand,      ex.get("brand")),
        "type":          _coalesce(item_type,  ex.get("type")),
        "matched_title": _coalesce(item_name,  ex.get("matched_title")),
        "color":         _coalesce(color,      ex.get("color")),
        "style":         _coalesce(style,      ex.get("style")),
        "season":        _coalesce(season,     ex.get("season")),
        "fabric":        _coalesce(fabric,     ex.get("fabric")),
        "vibe":          _coalesce(vibe,       ex.get("vibe")),
        "gender":        _coalesce(gender,     ex.get("gender")),
        "keywords":      _coalesce(keywords,   ex.get("keywords")),
        "category":      _coalesce(category,   ex.get("category")),
    }).eq("user_id", user_id).eq("filename", filename).execute()


# === Step 4: Emoji sticker (bonus, separate emoticon_path) ======================
def generate_emoji_via_dalle(emoji_prompt, output_dir="emoji_outputs"):
    """
    Generate an emoji sticker via gpt-image-1 → dall-e-3 → dall-e-2 fallback chain.
    Returns local file path or None.
    """
    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    os.makedirs(output_dir, exist_ok=True)
    safe = emoji_prompt[:50].replace(" ", "_").replace("/", "_").replace(":", "")
    out_path = os.path.join(output_dir, f"emoji_{safe}.png")

    models = [
        ("gpt-image-1", {"size": "1024x1024", "background": "transparent"}),
        ("dall-e-3",    {"size": "1024x1024", "quality": "standard", "n": 1}),
        ("dall-e-2",    {"size": "1024x1024", "n": 1}),
    ]

    for model, kwargs in models:
        try:
            response = client.images.generate(model=model, prompt=emoji_prompt, **kwargs)
            print(f"✅ Emoji model used: {model}")
            item = response.data[0]
            b64 = getattr(item, "b64_json", None)
            if b64:
                img_bytes = base64.b64decode(b64)
            else:
                img_bytes = requests.get(item.url, timeout=60).content

            img = Image.open(BytesIO(img_bytes))
            img.save(out_path, "PNG")
            return out_path
        except Exception as e:
            print(f"⚠️  {model} failed: {e} — trying next")

    print("❌ All emoji generation models failed.")
    return None


def _save_emoticon_to_db(user_id, filename, emoticon_path):
    from db import get_supa
    get_supa().table("closet_items").update({
        "emoticon_path": emoticon_path,
    }).eq("user_id", user_id).eq("filename", filename).execute()


# === Main entry point ============================================================
def generate_icon_from_image(image_path, user_id, filename, tag_text=None, output_dir="icon_outputs"):
    """
    Runs all pipeline steps independently — failure in one does not block the others.
      1. GPT-4o Vision → rich metadata + emoji_prompt
      2. gpt-image-1   → transparent PNG icon (background removed)
      3. DB write       → metadata + icon_path saved
      4. gpt-image-1   → emoji sticker (emoticon_path, optional)
    """
    gpt_tags     = {}
    caption      = ""
    category     = None
    emoji_prompt = None

    # ── Step 1: GPT-4o Vision ────────────────────────────────────────────────
    try:
        gpt_tags     = analyze_image_with_gpt(image_path, tag_text=tag_text)
        caption      = gpt_tags.get("caption", "") or ""
        emoji_prompt = gpt_tags.get("emoji_prompt")
        category     = infer_category(gpt_tags.get("type"))
        print(f"✅ GPT: caption='{caption}' | type={gpt_tags.get('type')} → category={category}")
        print(f"🏷️  brand='{gpt_tags.get('brand')}' | back_tag='{gpt_tags.get('back_tag_text')}'")
        print(f"🎨 emoji_prompt='{(emoji_prompt or '')[:80]}'")
    except Exception as e:
        print(f"⚠️  GPT analysis failed ({type(e).__name__}): {e}")

    # Write text metadata to DB immediately after GPT finishes — don't wait for
    # icon generation. The card poll will pick this up within 2 seconds and show
    # the name/brand/type on the card while the icon is still generating.
    try:
        _save_to_db(user_id, filename, icon_path=None, gpt_tags=gpt_tags, category=category)
        print(f"✅ Text metadata saved — card will show name/brand now")
    except Exception as e:
        print(f"⚠️  Early DB save failed: {e}")

    # Fallback icon prompt when GPT is unavailable
    if not caption:
        caption = filename.rsplit(".", 1)[0].replace("_", " ").replace("-", " ").strip() or "clothing item"

    icon_prompt = emoji_prompt or (
        f"Minimalist icon of {caption}, front-facing, transparent background, "
        "isolated clothing item only, no mannequin, no human, no shadows, clean style"
    )

    # ── Step 2: GPT icon generation (transparent background) ────────────────
    icon_path = None
    try:
        icon_path = generate_icon_via_gpt(icon_prompt, output_dir)
        if icon_path:
            print(f"✅ Icon saved: {icon_path}")
        else:
            print("⚠️  Icon generation returned no image.")
    except Exception as e:
        print(f"⚠️  Icon generation failed ({type(e).__name__}): {e}")

    # ── Step 3: Update icon_path in DB (text already saved in Step 1) ────────
    if icon_path:
        try:
            from db import get_supa
            get_supa().table("closet_items").update({
                "icon_path": icon_path,
            }).eq("user_id", user_id).eq("filename", filename).execute()
            print(f"✅ Icon path saved to DB")
        except Exception as e:
            print(f"❌ Icon DB update failed: {e}")

    # ── Step 4: Emoji sticker (bonus) ────────────────────────────────────────
    if emoji_prompt:
        try:
            emoticon_path = generate_emoji_via_dalle(emoji_prompt, output_dir="emoji_outputs")
            if emoticon_path:
                _save_emoticon_to_db(user_id, filename, emoticon_path)
                print(f"✅ Emoji sticker saved: {emoticon_path}")
        except Exception as e:
            print(f"⚠️  Emoji sticker failed ({type(e).__name__}): {e}")

    return icon_path
