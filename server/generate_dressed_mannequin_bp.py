import os, io, time, base64, math, random, json
from flask import Blueprint, request, jsonify
from db import get_supa
from PIL import Image
import numpy as np
import cv2
import requests
import jwt

bp = Blueprint("generate_dressed_mannequin", __name__)

# ======================================================
# CONFIG
# ======================================================
from config import REPLICATE_API_TOKEN
REPLICATE_TOKEN = REPLICATE_API_TOKEN
REPLICATE_MODEL = "cuuupid/idm-vton:0513734a452173b8173e907e3a59d19a36266e55b48528559432bd21c7d7e985"
GSAM_VERSION = "ee871c19efb1941f55f66a3d7d960428c8a5afcb77449547fe8e5a3ab9ebc21c"

PROCESSED_DIR = os.getenv("PROCESSED_DIR", "processed")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:5000")
DEFAULT_MANNEQUIN_URL = os.getenv(
    "MANNEQUIN_BASE", "http://localhost:5000/static/mannequin_base.png"
)

os.makedirs(PROCESSED_DIR, exist_ok=True)

SLOT_ORDER = {
    "inner_top": {"category": "upper", "order": 10},
    "outer_top": {"category": "upper", "order": 20},
    "inner_bottom": {"category": "lower", "order": 30},
    "outer_bottom": {"category": "lower", "order": 35},
}

SECRET_KEY = "supersecretkey"

# ======================================================
# DB Helpers
# ======================================================
def get_item_by_id(user_id: int, item_id: int):
    """Return closet item metadata"""
    result = get_supa().table("closet_items").select(
        "id, user_id, filename, filepath, caption, brand, color, icon_path"
    ).eq("id", item_id).execute()
    row = result.data[0] if result.data else None
    if not row:
        raise ValueError(f"Item id not found: {item_id}")
    if int(row["user_id"]) != int(user_id):
        raise ValueError(f"Item {item_id} not accessible to user {user_id}")
    return row


# ======================================================
# Helpers
# ======================================================
def _replicate_headers():
    return {
        "Authorization": f"Token {REPLICATE_TOKEN}",
        "Content-Type": "application/json",
    }


def _poll_until_done(status_url, timeout_s=240):
    t0 = time.time()
    while True:
        r = requests.get(status_url, headers=_replicate_headers(), timeout=60)
        r.raise_for_status()
        js = r.json()
        st = js.get("status")
        if st == "succeeded":
            return js
        if st in ("failed", "canceled"):
            raise RuntimeError(f"Replicate failed: {js.get('error') or st}")
        if time.time() - t0 > timeout_s:
            raise TimeoutError("Replicate prediction timed out")
        time.sleep(1.2)


def _replicate_predict_model(model_tag: str, inputs: dict):
    url = "https://api.replicate.com/v1/predictions"
    payload = {"version": model_tag, "input": inputs}
    r = requests.post(url, headers=_replicate_headers(), json=payload, timeout=120)
    if not r.ok:
        raise RuntimeError(f"Replicate error {r.status_code}: {r.text}")
    js = r.json()
    return _poll_until_done(js["urls"]["get"])


# ======================================================
# Image Processing
# ======================================================
def load_image_bytes(path_on_disk: str) -> bytes:
    with open(path_on_disk, "rb") as f:
        return f.read()


def save_image_and_get_url(img: Image.Image, rel_path: str) -> str:
    out_path = os.path.join(PROCESSED_DIR, rel_path)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path)
    return f"{PUBLIC_BASE_URL}/processed/{rel_path}"


def grounded_sam_mask(image_bytes: bytes, prompt: str) -> Image.Image:
    data_uri = "data:image/png;base64," + base64.b64encode(image_bytes).decode()
    payload = {
        "version": GSAM_VERSION,
        "input": {
            "image": data_uri,
            "mask_prompt": prompt,
            "prompt": prompt,
            "negative_mask_prompt": "hand,hanger,background",
        },
    }
    r = requests.post(
        "https://api.replicate.com/v1/predictions",
        json=payload,
        headers=_replicate_headers(),
        timeout=60,
    )
    r.raise_for_status()
    js = _poll_until_done(r.json()["urls"]["get"])
    out = js["output"]
    mask_bytes = (
        requests.get(out, timeout=60).content
        if isinstance(out, str)
        else requests.get(out[0], timeout=60).content
    )
    mask = Image.open(io.BytesIO(mask_bytes)).convert("L")
    arr = np.array(mask)
    _, arr = cv2.threshold(arr, 0, 255, cv2.THRESH_OTSU)
    arr = cv2.medianBlur(arr, 3)
    return Image.fromarray(arr)


# ======================================================
# IDM-VTON Wrapper
# ======================================================
def idm_vton_tryon(human_path: str, cloth_path: str, garment_desc="clothing item"):
    """Send both images as base64 data URIs to Replicate."""
    with open(human_path, "rb") as f:
        human_b64 = base64.b64encode(f.read()).decode()
    with open(cloth_path, "rb") as f:
        cloth_b64 = base64.b64encode(f.read()).decode()

    inputs = {
        "human_img": "data:image/png;base64," + human_b64,
        "garm_img": "data:image/png;base64," + cloth_b64,
        "garment_des": garment_desc,
    }

    print("🧠 Calling Replicate IDM-VTON...")
    url = "https://api.replicate.com/v1/predictions"
    payload = {"version": REPLICATE_MODEL, "input": inputs}
    r = requests.post(url, headers=_replicate_headers(), json=payload)
    if not r.ok:
        raise RuntimeError(f"Replicate error {r.status_code}: {r.text}")
    js = r.json()
    print("gets till here")
    result = _poll_until_done(js["urls"]["get"])
    out = result.get("output")
    if isinstance(out, str):
        return out
    if isinstance(out, list) and len(out) > 0:
        return out[0]
    raise RuntimeError("Unexpected IDM-VTON output format")


# ======================================================
# Auth
# ======================================================
def get_user_id_from_token(req):
    auth_header = req.headers.get("Authorization")
    if not auth_header:
        return None
    try:
        token = auth_header.split(" ")[1]
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return payload["user_id"]
    except Exception:
        try:
            return int(req.headers.get("X-Debug-User"))
        except Exception:
            return None


# ======================================================
# MAIN ENDPOINT
# ======================================================
@bp.route("/generate_dressed_mannequin", methods=["POST"])
def generate_dressed_mannequin():
    user_id = get_user_id_from_token(request)
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401

    slots = request.get_json() or {}
    stages = [
        (meta["order"], slot, item_id, meta["category"])
        for slot, item_id in slots.items()
        if item_id and slot in SLOT_ORDER
        for meta in [SLOT_ORDER[slot]]
    ]
    stages.sort(key=lambda x: x[0])

    mannequin_path = os.path.join("static", "mannequin_base.png")
    base_rgb = Image.open(mannequin_path).convert("RGB")

    garments_used = []
    for _, slot, item_id, category in stages:
        try:
            rec = get_item_by_id(user_id, item_id)
            img_bytes = load_image_bytes(rec["filepath"])
            garment_desc = rec.get("caption") or rec.get("brand") or slot

            rgba = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
            cloth_path = os.path.join(PROCESSED_DIR, f"garments/{user_id}_{rec['id']}_{slot}.png")
            os.makedirs(os.path.dirname(cloth_path), exist_ok=True)
            rgba.save(cloth_path)

            mannequin_stage_path = os.path.join(PROCESSED_DIR, f"stages/{user_id}_{slot}_base.jpg")
            os.makedirs(os.path.dirname(mannequin_stage_path), exist_ok=True)
            base_rgb.save(mannequin_stage_path)

            result_url = idm_vton_tryon(mannequin_stage_path, cloth_path, garment_desc)
            print(f"✅ Replicate result for {slot}: {result_url}")

            result_bytes = requests.get(result_url, timeout=60).content
            result_img = Image.open(io.BytesIO(result_bytes)).convert("RGB")
            base_rgb.paste(result_img, (0, 0))

            garments_used.append({"slot": slot, "result_stage": result_url})

        except Exception as e:
            return jsonify({"error": f"{slot} failed: {e}"}), 500

    final_rel = f"final/{user_id}_mannequin_dressed.jpg"
    os.makedirs(os.path.join(PROCESSED_DIR, "final"), exist_ok=True)
    final_url = save_image_and_get_url(base_rgb, final_rel)

    return jsonify({"generated_url": final_url, "garments_used": garments_used})