# outfit_2d.py
# 2.5D outfit compositor:
# - MediaPipe Pose layout (optional)
# - Background removal (rembg preferred, OpenCV fallback)
# - Tight crop to alpha
# - Uses original uploads for masking (better than icons)
# - Debug endpoint and rich response for verification

from flask import Blueprint, request, jsonify, send_from_directory
from PIL import Image, ImageFilter
import os, jwt, uuid, json
import numpy as np
from urllib.parse import quote

# ---------- Optional deps ----------
try:
    import mediapipe as mp
    _HAS_MP = True
except Exception:
    _HAS_MP = False

try:
    from rembg import remove as rembg_remove
    _HAS_REMBG = True
except Exception:
    _HAS_REMBG = False

try:
    import cv2
    _HAS_CV2 = True
except Exception:
    _HAS_CV2 = False

# ---------- Blueprint / Config ----------
outfit2d_bp = Blueprint("outfit2d", __name__, url_prefix="/outfit")

from config import JWT_SECRET
SECRET_KEY = JWT_SECRET  # unified with the rest of the app (was JWT_SECRET_KEY/"supersecretkey")
PUBLIC_BASE = os.getenv("PUBLIC_BASE_URL", "http://localhost:5000")

# Output dirs resolved centrally (env-driven → persistent volume in prod)
from paths import ICON_OUTPUTS_DIR, GENERATED_OUTFITS_DIR as GENERATED_DIR
os.makedirs(GENERATED_DIR, exist_ok=True)

# Canvas (4:5)
CANVAS_W = int(os.getenv("OUTFIT_CANVAS_W", "1080"))
CANVAS_H = int(os.getenv("OUTFIT_CANVAS_H", "1350"))
CANVAS_BG = os.getenv("OUTFIT_CANVAS_BG", "#161932")

# Path to a mannequin image for MediaPipe pose (front-facing silhouette/photo)
MANNEQUIN_IMG = os.getenv("MANNEQUIN_IMG", os.path.abspath("./assets/mannequin.png"))

# Where original uploads live (mirror of your main.py logic)
ORIGINAL_UPLOADS_DIR = os.environ.get("CONVERTED_IMAGES_DIR")
if not ORIGINAL_UPLOADS_DIR:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    ORIGINAL_UPLOADS_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "converted_images"))
if not os.path.isdir(ORIGINAL_UPLOADS_DIR):
    alt = os.path.join(os.path.dirname(os.path.abspath(__file__)), "converted_images")
    if os.path.isdir(alt):
        ORIGINAL_UPLOADS_DIR = alt

# Prefer original upload (higher quality) for masking vs square icons
USE_ORIGINAL_FOR_MASK = True

# ---------- Fallback slot layout (if MediaPipe not available) ----------
FALLBACK_SLOT_SPEC = {
    "accessories":      {"x": 540, "y": 210, "maxW": 520, "maxH": 240, "z": 90, "anchor": "center"},
    "outer_top":        {"x": 540, "y": 420, "maxW": 640, "maxH": 520, "z": 80, "anchor": "top_anchor"},
    "inner_top":        {"x": 540, "y": 435, "maxW": 600, "maxH": 500, "z": 70, "anchor": "top_anchor"},
    "inner_bottom":     {"x": 540, "y": 820, "maxW": 560, "maxH": 520, "z": 60, "anchor": "top_center"},
    "outer_bottom":     {"x": 540, "y": 800, "maxW": 600, "maxH": 540, "z": 65, "anchor": "top_center"},
    "inner_left_foot":  {"x": 460, "y": 1150, "maxW": 260, "maxH": 220, "z": 40, "anchor": "left_shoe_anchor"},
    "inner_right_foot": {"x": 620, "y": 1150, "maxW": 260, "maxH": 220, "z": 40, "anchor": "right_shoe_anchor"},
    "outer_left_foot":  {"x": 450, "y": 1140, "maxW": 280, "maxH": 240, "z": 50, "anchor": "left_shoe_anchor"},
    "outer_right_foot": {"x": 630, "y": 1140, "maxW": 280, "maxH": 240, "z": 50, "anchor": "right_shoe_anchor"},
}

SLOT_SPEC = None  # set in _init_slot_spec()


# ---------- Helpers ----------
def _get_user_id_from_request(req):
    auth_header = req.headers.get("Authorization")
    if auth_header:
        try:
            token = auth_header.split(" ")[1]
            payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
            return payload["user_id"]
        except Exception:
            pass
    # Debug override
    try:
        return int(req.headers.get("X-Debug-User"))
    except Exception:
        return None

def _hex_to_rgb(hx: str):
    hx = hx.lstrip("#")
    return tuple(int(hx[i:i+2], 16) for i in (0, 2, 4))

def _safe_open_rgba(path_or_bytes):
    img = Image.open(path_or_bytes)
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    return img

def _scale_to_fit(img: Image.Image, maxW: int, maxH: int) -> Image.Image:
    w, h = img.size
    if w == 0 or h == 0:
        return img
    s = min(maxW / w, maxH / h)
    new_size = (max(1, int(round(w * s))), max(1, int(round(h * s))))
    return img.resize(new_size, Image.LANCZOS)

def _tight_crop_rgba(img: Image.Image) -> Image.Image:
    alpha = img.split()[-1]
    bbox = alpha.getbbox()
    return img.crop(bbox) if bbox else img

def _make_shadow_from_alpha(rgba_img: Image.Image, radius=12, offset=(0, 8), opacity=96):
    alpha = rgba_img.split()[-1]
    shadow = Image.new("RGBA", rgba_img.size, (0, 0, 0, 0))
    black = Image.new("RGBA", rgba_img.size, (0, 0, 0, opacity))
    shadow.paste(black, mask=alpha)
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius))
    return shadow, offset

def _anchor_point_scaled(img: Image.Image, anchor_key: str):
    w, h = img.size
    if anchor_key == "top_anchor":
        return w / 2.0, h * 0.08
    if anchor_key == "top_center":
        return w / 2.0, h * 0.02
    if anchor_key == "left_shoe_anchor":
        return w * 0.45, h * 0.15
    if anchor_key == "right_shoe_anchor":
        return w * 0.55, h * 0.15
    return w / 2.0, h / 2.0

def _fetch_item_rows(user_id, id_list):
    if not id_list:
        return {}
    from db import get_supa
    rows = get_supa().table("closet_items").select("id, filename, icon_path").eq("user_id", user_id).in_("id", id_list).execute().data
    return {r["id"]: r for r in rows}

def _resolve_source_for_mask(meta):
    """
    Prefer high-res original upload for masking, else DB icon_path, else icon_outputs/<basename>.(png|webp)
    Returns (path, used_original)
    """
    if USE_ORIGINAL_FOR_MASK:
        fname = meta.get("filename")
        if fname:
            orig_path = os.path.join(ORIGINAL_UPLOADS_DIR, fname)
            if os.path.isfile(orig_path):
                return orig_path, True

    icon_path = meta.get("icon_path")
    if icon_path and os.path.isfile(icon_path):
        return icon_path, False

    base = os.path.basename(icon_path) if icon_path else None
    if not base and meta.get("filename"):
        base = os.path.splitext(os.path.basename(meta["filename"]))[0] + ".png"
    if base:
        guess = os.path.join(ICON_OUTPUTS_DIR, base)
        if os.path.isfile(guess):
            return guess, False
        root, _ = os.path.splitext(base)
        guess_webp = os.path.join(ICON_OUTPUTS_DIR, root + ".webp")
        if os.path.isfile(guess_webp):
            return guess_webp, False

    return None, False

def _ensure_rgba_masked(path) -> Image.Image:
    """
    Ensure a REAL alpha garment mask, then tight crop.
    - Uses rembg when present or a simple OpenCV HSV mask fallback.
    """
    img = Image.open(path).convert("RGBA")
    w, h = img.size
    rgba = np.array(img)
    alpha = rgba[:, :, 3]
    rgb = rgba[:, :, :3]

    near_white = (rgb[..., 0] > 245) & (rgb[..., 1] > 245) & (rgb[..., 2] > 245)
    white_ratio = float(near_white.sum()) / float(max(1, w * h))
    has_alpha_variation = (alpha.min() < 255 and alpha.max() > 0)

    # Prefer rembg for boxed/white backgrounds or no alpha variation
    if _HAS_REMBG:
        try:
            if (white_ratio > 0.2) or (not has_alpha_variation):
                out = rembg_remove(img)  # RGBA PIL
                return _tight_crop_rgba(out)
            return _tight_crop_rgba(img)
        except Exception:
            pass

    # OpenCV fallback
    if _HAS_CV2:
        try:
            bgr = cv2.imread(path, cv2.IMREAD_COLOR)
            if bgr is None:
                return _tight_crop_rgba(img)
            hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
            # Mask "not white"; tune if needed
            lower = np.array([0, 0, 0])
            upper = np.array([179, 60, 255])
            mask = cv2.inRange(hsv, lower, upper)
            mask = cv2.medianBlur(mask, 5)
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if contours:
                c = max(contours, key=cv2.contourArea)
                mask2 = np.zeros_like(mask)
                cv2.drawContours(mask2, [c], -1, 255, thickness=-1)
            else:
                mask2 = mask
            alpha_img = Image.fromarray(mask2).resize((w, h), Image.LANCZOS)
            rgba_img = img.copy()
            rgba_img.putalpha(alpha_img)
            return _tight_crop_rgba(rgba_img)
        except Exception:
            return _tight_crop_rgba(img)

    return _tight_crop_rgba(img)

# ---------- MediaPipe Pose → slot layout ----------
def _build_slots_from_mediapipe() -> dict | None:
    if not (_HAS_MP and os.path.isfile(MANNEQUIN_IMG)):
        return None

    # Load mannequin resized to canvas size
    mannequin = Image.open(MANNEQUIN_IMG).convert("RGB").resize((CANVAS_W, CANVAS_H), Image.LANCZOS)
    np_img = np.array(mannequin)

    mp_pose = mp.solutions.pose
    with mp_pose.Pose(static_image_mode=True, model_complexity=1, enable_segmentation=False) as pose:
        res = pose.process(np_img)

    if not res.pose_landmarks:
        return None

    lm = res.pose_landmarks.landmark
    def P(idx):
        return int(lm[idx].x * CANVAS_W), int(lm[idx].y * CANVAS_H)

    L_SH, R_SH = P(mp_pose.PoseLandmark.LEFT_SHOULDER), P(mp_pose.PoseLandmark.RIGHT_SHOULDER)
    L_HIP, R_HIP = P(mp_pose.PoseLandmark.LEFT_HIP), P(mp_pose.PoseLandmark.RIGHT_HIP)
    L_ANK, R_ANK = P(mp_pose.PoseLandmark.LEFT_ANKLE), P(mp_pose.PoseLandmark.RIGHT_ANKLE)
    NOSE = P(mp_pose.PoseLandmark.NOSE)

    shoulder_w = abs(R_SH[0] - L_SH[0])
    hip_w = abs(R_HIP[0] - L_HIP[0])
    mid_shoulder = ((L_SH[0] + R_SH[0]) // 2, (L_SH[1] + R_SH[1]) // 2)
    mid_hip = ((L_HIP[0] + R_HIP[0]) // 2, (L_HIP[1] + R_HIP[1]) // 2)
    mid_ank = ((L_ANK[0] + R_ANK[0]) // 2, (L_ANK[1] + R_ANK[1]) // 2)

    # Heuristic sizes
    top_maxW = int(shoulder_w * 1.35)
    top_maxH = int((mid_hip[1] - mid_shoulder[1]) * 1.05)
    bottom_maxW = int(hip_w * 1.25)
    bottom_maxH = int((mid_ank[1] - mid_hip[1]) * 1.05)
    shoe_maxW = int(max(shoulder_w * 0.45, 120))
    shoe_maxH = int(shoe_maxW * 0.55)

    slots = {
        "accessories":      {"x": mid_shoulder[0], "y": max(80, NOSE[1]-80), "maxW": int(shoulder_w*1.0), "maxH": 220, "z": 90, "anchor": "center"},
        "outer_top":        {"x": mid_shoulder[0], "y": mid_shoulder[1]+20, "maxW": top_maxW, "maxH": top_maxH, "z": 80, "anchor": "top_anchor"},
        "inner_top":        {"x": mid_shoulder[0], "y": mid_shoulder[1]+35, "maxW": int(top_maxW*0.95), "maxH": int(top_maxH*0.95), "z": 70, "anchor": "top_anchor"},
        "inner_bottom":     {"x": mid_hip[0],      "y": mid_hip[1]+10,      "maxW": int(bottom_maxW*0.95), "maxH": int(bottom_maxH*0.95), "z": 60, "anchor": "top_center"},
        "outer_bottom":     {"x": mid_hip[0],      "y": mid_hip[1],         "maxW": bottom_maxW, "maxH": bottom_maxH, "z": 65, "anchor": "top_center"},
        "inner_left_foot":  {"x": L_ANK[0]-40,     "y": L_ANK[1]-10,        "maxW": shoe_maxW, "maxH": shoe_maxH, "z": 40, "anchor": "left_shoe_anchor"},
        "inner_right_foot": {"x": R_ANK[0]+40,     "y": R_ANK[1]-10,        "maxW": shoe_maxW, "maxH": shoe_maxH, "z": 40, "anchor": "right_shoe_anchor"},
        "outer_left_foot":  {"x": L_ANK[0]-50,     "y": L_ANK[1]-20,        "maxW": int(shoe_maxW*1.05), "maxH": int(shoe_maxH*1.05), "z": 50, "anchor": "left_shoe_anchor"},
        "outer_right_foot": {"x": R_ANK[0]+50,     "y": R_ANK[1]-20,        "maxW": int(shoe_maxW*1.05), "maxH": int(shoe_maxH*1.05), "z": 50, "anchor": "right_shoe_anchor"},
    }
    return slots

def _print_startup_status(slots_from_mp):
    print(f"🧩 SLOT_SPEC ready (mediapipe: {bool(slots_from_mp)})")
    print(f"   MANNEQUIN_IMG: {MANNEQUIN_IMG} exists: {os.path.isfile(MANNEQUIN_IMG)}")
    print(f"   rembg available: {_HAS_REMBG} | OpenCV available: {_HAS_CV2}")
    print(f"   ORIGINAL_UPLOADS_DIR: {ORIGINAL_UPLOADS_DIR} (exists: {os.path.isdir(ORIGINAL_UPLOADS_DIR)})")

def _init_slot_spec():
    global SLOT_SPEC
    slots = None
    if _HAS_MP and os.path.isfile(MANNEQUIN_IMG):
        try:
            slots = _build_slots_from_mediapipe()
        except Exception as e:
            print("⚠️ MediaPipe layout failed, falling back. Error:", e)
            slots = None
    SLOT_SPEC = slots if slots else FALLBACK_SLOT_SPEC
    _print_startup_status(slots)

_init_slot_spec()


# ---------- Routes ----------
@outfit2d_bp.route("/generated/<path:fname>", methods=["GET"])
def serve_generated(fname):
    return send_from_directory(GENERATED_DIR, fname, as_attachment=False)

@outfit2d_bp.route("/debug", methods=["GET"])
def debug_info():
    info = {
        "mediapipe_available": _HAS_MP,
        "rembg_available": _HAS_REMBG,
        "cv2_available": _HAS_CV2,
        "mannequin_path": MANNEQUIN_IMG,
        "mannequin_exists": os.path.isfile(MANNEQUIN_IMG),
        "layout": "mediapipe" if SLOT_SPEC is not FALLBACK_SLOT_SPEC else "fallback",
        "canvas": {"w": CANVAS_W, "h": CANVAS_H},
        "original_uploads_dir": ORIGINAL_UPLOADS_DIR,
        "icon_outputs_dir": ICON_OUTPUTS_DIR,
    }
    return jsonify(info), 200

@outfit2d_bp.route("/compose", methods=["POST"])
def compose_outfit():
    try:
        user_id = _get_user_id_from_request(request)
        if not user_id:
            return jsonify({"message": "Unauthorized"}), 401

        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            return jsonify({"message": "Invalid JSON body"}), 400

        wanted = {}
        for slot_key, val in body.items():
            if slot_key not in SLOT_SPEC or val in (None, "", 0):
                continue
            try:
                wanted[slot_key] = int(val)
            except Exception:
                return jsonify({"message": f"Slot '{slot_key}' must be an integer item ID"}), 400

        if not wanted:
            return jsonify({"message": "No valid slots provided"}), 400

        item_ids = list(set(wanted.values()))
        item_map = _fetch_item_rows(user_id, item_ids)

        # Create canvas
        bg_rgb = _hex_to_rgb(CANVAS_BG)
        canvas = Image.new("RGBA", (CANVAS_W, CANVAS_H), bg_rgb + (255,))

        # Compose in z-order
        ordered = sorted(wanted.items(), key=lambda kv: SLOT_SPEC[kv[0]]["z"])
        used_slots, debug_sources = [], {}

        for slot_key, item_id in ordered:
            spec = SLOT_SPEC[slot_key]
            meta = item_map.get(item_id)
            if not meta:
                continue

            src_path, used_orig = _resolve_source_for_mask(meta)
            if not src_path:
                continue

            try:
                img = _ensure_rgba_masked(src_path)
            except Exception:
                img = _safe_open_rgba(src_path)
                img = _tight_crop_rgba(img)

            img = _scale_to_fit(img, spec["maxW"], spec["maxH"])
            ax, ay = _anchor_point_scaled(img, spec.get("anchor", "center"))
            px = int(round(spec["x"] - ax))
            py = int(round(spec["y"] - ay))

            shadow, (offx, offy) = _make_shadow_from_alpha(img, radius=12, offset=(0, 8), opacity=96)
            canvas.paste(shadow, (px + offx, py + offy), shadow)
            canvas.paste(img, (px, py), img)

            used_slots.append(slot_key)
            debug_sources[slot_key] = {
                "src_path": src_path,
                "used_original": used_orig,
                "scaled_size": [img.width, img.height]
            }

        # Save
        fname = f"outfit_{uuid.uuid4().hex}.png"
        save_path = os.path.join(GENERATED_DIR, fname)
        canvas.save(save_path, format="PNG")

        generated_url = f"{PUBLIC_BASE}/outfit/generated/{quote(fname)}"
        return jsonify({
            "generated_url": generated_url,
            "width": CANVAS_W,
            "height": CANVAS_H,
            "used_slots": used_slots,
            "layout": "mediapipe" if SLOT_SPEC is not FALLBACK_SLOT_SPEC else "fallback",
            "rembg": _HAS_REMBG,
            "cv2": _HAS_CV2,
            "sources": debug_sources
        }), 200

    except Exception as e:
        print(f"❌ compose_outfit error: {e}")
        return jsonify({"message": "Internal server error"}), 500




# # outfit_2d.py
# # Standalone 2.5D outfit compositor (no VTON, no anchor_json column required).
# # Layers garment PNGs onto a 4:5 canvas with z-order and soft shadows.

# from flask import Blueprint, request, jsonify, send_from_directory
# from PIL import Image, ImageFilter
# from db import get_db
# import os, io, jwt, uuid, json
# from urllib.parse import quote

# # ---------------------------------------------------------------------
# # Blueprint & Config
# # ---------------------------------------------------------------------
# outfit2d_bp = Blueprint("outfit2d", __name__, url_prefix="/outfit")

# # Keep default in sync with your other blueprints
# SECRET_KEY = os.getenv("JWT_SECRET_KEY", "supersecretkey")
# PUBLIC_BASE = os.getenv("PUBLIC_BASE_URL", "http://localhost:5000")

# # Where your small transparent garment PNGs are saved (served by /icons route in main.py)
# ICON_OUTPUTS_DIR = os.path.abspath(os.path.join(os.getcwd(), "icon_outputs"))

# # Where rendered outfit PNGs will be stored and served by this blueprint
# GENERATED_DIR = os.path.abspath(os.path.join(os.getcwd(), "generated_outfits"))
# os.makedirs(GENERATED_DIR, exist_ok=True)

# # Canvas configuration (Instagram 4:5 portrait)
# CANVAS_W = int(os.getenv("OUTFIT_CANVAS_W", "1080"))
# CANVAS_H = int(os.getenv("OUTFIT_CANVAS_H", "1350"))
# CANVAS_BG = os.getenv("OUTFIT_CANVAS_BG", "#161932")


# # ---------------------------------------------------------------------
# # Slot layout: positions & z-order
# # Coordinates are where the garment "anchor" will land on the canvas.
# # maxW/maxH constrain the scale of the garment image.
# # ---------------------------------------------------------------------
# SLOT_SPEC = {
#     "accessories":      {"x": 540, "y": 210, "maxW": 520, "maxH": 240, "z": 90, "anchor": "center"},
#     "outer_top":        {"x": 540, "y": 420, "maxW": 640, "maxH": 520, "z": 80, "anchor": "top_anchor"},
#     "inner_top":        {"x": 540, "y": 435, "maxW": 600, "maxH": 500, "z": 70, "anchor": "top_anchor"},
#     "inner_bottom":     {"x": 540, "y": 820, "maxW": 560, "maxH": 520, "z": 60, "anchor": "top_center"},
#     "outer_bottom":     {"x": 540, "y": 800, "maxW": 600, "maxH": 540, "z": 65, "anchor": "top_center"},
#     "inner_left_foot":  {"x": 460, "y": 1150, "maxW": 260, "maxH": 220, "z": 40, "anchor": "left_shoe_anchor"},
#     "inner_right_foot": {"x": 620, "y": 1150, "maxW": 260, "maxH": 220, "z": 40, "anchor": "right_shoe_anchor"},
#     "outer_left_foot":  {"x": 450, "y": 1140, "maxW": 280, "maxH": 240, "z": 50, "anchor": "left_shoe_anchor"},
#     "outer_right_foot": {"x": 630, "y": 1140, "maxW": 280, "maxH": 240, "z": 50, "anchor": "right_shoe_anchor"},
# }


# # ---------------------------------------------------------------------
# # Helpers
# # ---------------------------------------------------------------------
# def _get_user_id_from_request(req):
#     """Decode JWT or allow X-Debug-User fallback."""
#     auth_header = req.headers.get("Authorization")
#     if auth_header:
#         try:
#             token = auth_header.split(" ")[1]
#             payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
#             return payload["user_id"]
#         except Exception:
#             pass
#     # debug override
#     try:
#         return int(req.headers.get("X-Debug-User"))
#     except Exception:
#         return None

# def _hex_to_rgb(hx: str):
#     hx = hx.lstrip("#")
#     return tuple(int(hx[i:i+2], 16) for i in (0,2,4))

# def _safe_open_rgba(path_or_bytes):
#     img = Image.open(path_or_bytes)
#     if img.mode != "RGBA":
#         img = img.convert("RGBA")
#     return img

# def _scale_to_fit(img: Image.Image, maxW: int, maxH: int) -> Image.Image:
#     w, h = img.size
#     if w == 0 or h == 0:
#         return img
#     s = min(maxW / w, maxH / h)
#     new_size = (max(1, int(round(w * s))), max(1, int(round(h * s))))
#     return img.resize(new_size, Image.LANCZOS)

# def _make_shadow_from_alpha(rgba_img: Image.Image, radius=12, offset=(0, 8), opacity=96):
#     """
#     Create a blurred drop shadow from the image alpha.
#     Returns (shadow_rgba, (offx, offy)).
#     """
#     alpha = rgba_img.split()[-1]
#     shadow = Image.new("RGBA", rgba_img.size, (0, 0, 0, 0))
#     black = Image.new("RGBA", rgba_img.size, (0, 0, 0, opacity))
#     shadow.paste(black, mask=alpha)
#     shadow = shadow.filter(ImageFilter.GaussianBlur(radius))
#     return shadow, offset

# def _anchor_point_scaled(img: Image.Image, anchor_key: str):
#     """
#     Heuristic anchor points in *scaled* image space (no DB anchors).
#     """
#     w, h = img.size
#     if anchor_key == "top_anchor":
#         return w / 2.0, h * 0.08
#     if anchor_key == "top_center":
#         return w / 2.0, h * 0.02
#     if anchor_key == "left_shoe_anchor":
#         return w * 0.45, h * 0.15
#     if anchor_key == "right_shoe_anchor":
#         return w * 0.55, h * 0.15
#     # center (default)
#     return w / 2.0, h / 2.0

# def _fetch_item_rows(db, user_id, id_list):
#     """
#     Returns {item_id: {"id", "filename", "icon_path"}}
#     No anchor_json column required.
#     """
#     if not id_list:
#         return {}
#     cur = db.cursor()
#     q = """
#       SELECT id, filename, icon_path
#       FROM closet_items
#       WHERE user_id = %s AND id = ANY(%s)
#     """
#     cur.execute(q, (user_id, id_list))
#     rows = cur.fetchall()
#     out = {}
#     for rid, fn, icon_path in rows:
#         out[rid] = {"id": rid, "filename": fn, "icon_path": icon_path}
#     return out

# def _resolve_icon_path(meta):
#     """
#     Prefer absolute path stored in DB (icon_path).
#     Fallback to ./icon_outputs/<basename>.png which matches your /icons route.
#     """
#     candidate = meta.get("icon_path")
#     if candidate and os.path.isfile(candidate):
#         return candidate

#     base = os.path.basename(candidate) if candidate else None
#     if not base:
#         # derive from original filename (png)
#         base = os.path.splitext(os.path.basename(meta.get("filename", "")))[0] + ".png"

#     guess = os.path.join(ICON_OUTPUTS_DIR, base)
#     if os.path.isfile(guess):
#         return guess

#     # final fallback: return None to skip
#     return None


# # ---------------------------------------------------------------------
# # Routes
# # ---------------------------------------------------------------------
# @outfit2d_bp.route("/generated/<path:fname>", methods=["GET"])
# def serve_generated(fname):
#     """Serve rendered outfits from GENERATED_DIR."""
#     return send_from_directory(GENERATED_DIR, fname, as_attachment=False)

# @outfit2d_bp.route("/compose", methods=["POST"])
# def compose_outfit():
#     """
#     Request JSON: {slot_id: item_id or null}
#     slot_id must be one of SLOT_SPEC keys.
#     item_id must belong to the authenticated user in closet_items.
#     """
#     try:
#         user_id = _get_user_id_from_request(request)
#         if not user_id:
#             return jsonify({"message": "Unauthorized"}), 401

#         body = request.get_json(silent=True) or {}
#         if not isinstance(body, dict):
#             return jsonify({"message": "Invalid JSON body"}), 400

#         # Keep only recognized slots and integer IDs
#         wanted = {}
#         for slot_key, val in body.items():
#             if slot_key not in SLOT_SPEC or val in (None, "", 0):
#                 continue
#             try:
#                 wanted[slot_key] = int(val)
#             except Exception:
#                 return jsonify({"message": f"Slot '{slot_key}' must be an integer item ID"}), 400

#         if not wanted:
#             return jsonify({"message": "No valid slots provided"}), 400

#         # Fetch items
#         db = get_db()
#         item_ids = list(set(wanted.values()))
#         item_map = _fetch_item_rows(db, user_id, item_ids)

#         # Create canvas
#         bg_rgb = _hex_to_rgb(CANVAS_BG)
#         canvas = Image.new("RGBA", (CANVAS_W, CANVAS_H), bg_rgb + (255,))

#         # Draw in z-order (low → high)
#         ordered = sorted(wanted.items(), key=lambda kv: SLOT_SPEC[kv[0]]["z"])
#         used_slots = []

#         for slot_key, item_id in ordered:
#             spec = SLOT_SPEC[slot_key]
#             meta = item_map.get(item_id)
#             if not meta:
#                 continue

#             src_path = _resolve_icon_path(meta)
#             if not src_path:
#                 continue

#             try:
#                 img = _safe_open_rgba(src_path)
#             except Exception:
#                 continue

#             # Scale to slot
#             img = _scale_to_fit(img, spec["maxW"], spec["maxH"])

#             # Anchor in scaled space
#             ax, ay = _anchor_point_scaled(img, spec.get("anchor", "center"))

#             # Position on canvas so anchor lands at (x, y)
#             px = int(round(spec["x"] - ax))
#             py = int(round(spec["y"] - ay))

#             # Shadow then garment
#             shadow, (offx, offy) = _make_shadow_from_alpha(img, radius=12, offset=(0, 8), opacity=96)
#             canvas.paste(shadow, (px + offx, py + offy), shadow)
#             canvas.paste(img, (px, py), img)

#             used_slots.append(slot_key)

#         # Save PNG
#         fname = f"outfit_{uuid.uuid4().hex}.png"
#         save_path = os.path.join(GENERATED_DIR, fname)
#         canvas.save(save_path, format="PNG")

#         # Public URL
#         generated_url = f"{PUBLIC_BASE}/outfit/generated/{quote(fname)}"

#         return jsonify({
#             "generated_url": generated_url,
#             "width": CANVAS_W,
#             "height": CANVAS_H,
#             "used_slots": used_slots
#         }), 200

#     except Exception as e:
#         print(f"❌ compose_outfit error: {e}")
#         return jsonify({"message": "Internal server error"}), 500
