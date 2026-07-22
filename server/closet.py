from flask import Blueprint, request, jsonify, send_from_directory
import os
import re
import jwt
import threading
from werkzeug.utils import secure_filename
from db import get_supa
from config import JWT_SECRET
from ocr_utils import extract_tag_text
from callable_embedding import generate_clip_embedding, save_embedding_to_db
from callable_faiss import search_similar_products
import numpy as np
from PIL import Image as _PILImage
from replicate_icon_clothing import generate_icon_from_image, retag_metadata_only

try:
    from pillow_heif import register_heif_opener as _reg_heif
    _reg_heif()
except Exception:
    pass


def _blend_text_query(image_emb: np.ndarray, name: str | None, row: dict,
                      text_weight: float = 0.35) -> np.ndarray:
    """
    Blend a CLIP image embedding with a CLIP text embedding built from the
    item's metadata.  This steers the search toward the right color/category
    without needing to regenerate any stored embeddings.

    text_weight=0.35 means 65% visual + 35% text signal.
    Falls back to pure image embedding if no useful text is available.
    """
    from callable_embedding import encode_text

    # Build description from best available metadata, most specific first.
    parts = []
    item_name = (name or row.get("matched_title") or "").strip()
    if item_name:
        parts.append(item_name)

    for field in ("color", "sub_category", "subcategory", "category"):
        val = (row.get(field) or "").strip()
        if val and val.lower() not in " ".join(parts).lower():
            parts.append(val)

    if not parts:
        return image_emb

    desc = " ".join(parts[:4])
    print(f"Text-guided FAISS query: '{desc}'")

    try:
        text_emb = np.array(encode_text(desc), dtype=np.float32)
        img_norm  = image_emb / (np.linalg.norm(image_emb) + 1e-9)
        txt_norm  = text_emb  / (np.linalg.norm(text_emb)  + 1e-9)
        blended   = (1 - text_weight) * img_norm + text_weight * txt_norm
        return blended / (np.linalg.norm(blended) + 1e-9)
    except Exception as e:
        print(f"Text blend failed ({e}) — using image only")
        return image_emb


def _detect_gender(text: str) -> str | None:
    """Return 'womens' or 'mens' if detected in text, else None.
    Check womens first because 'men' is a substring of 'women'."""
    t = text.lower()
    if re.search(r"\b(women|womens|womenswear|women's|female|girls?|ladies)\b", t):
        return "womens"
    if re.search(r"\b(men|mens|menswear|men's|male|boys?)\b", t):
        return "mens"
    return None


closet_bp = Blueprint("closet", __name__)

UPLOAD_FOLDER = "uploaded_closets"
SECRET_KEY = JWT_SECRET
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def get_user_id_from_token(request):
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return None
    try:
        token = auth_header.split(" ")[1]
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return payload["user_id"]
    except Exception as e:
        print(f"Token error: {e}")
        return None

def _serialize_item(item, user_id):
    """Convert a closet_items DB row into a frontend-safe dict.
    Replaces the raw vector_embedding (512 floats) with a bool so the
    frontend can gate 'Find Match' without downloading KB of floats per card."""
    item["url"] = f"/static/{user_id}/{item['filename']}"
    item["tag"] = item.get("tag_text")
    item["has_embedding"] = bool(item.pop("vector_embedding", None))
    return item


@closet_bp.route("/get_closet_images", methods=["GET"])
def get_images():
    user_id = get_user_id_from_token(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401

    supa = get_supa()
    result = supa.table("closet_items").select(_ITEM_SELECT).eq("user_id", user_id).order("id").execute()

    images = [_serialize_item(item, user_id) for item in result.data]
    return jsonify(images), 200


@closet_bp.route("/categories", methods=["GET"])
def get_categories():
    user_id = get_user_id_from_token(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401
    from services.closet_service import get_categories
    return jsonify(get_categories(user_id)), 200


@closet_bp.route("/categories", methods=["POST"])
def add_category():
    user_id = get_user_id_from_token(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401
    data = request.get_json()
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"message": "Name required"}), 400
    from services.closet_service import add_category as svc_add
    cat = svc_add(user_id, name)
    if cat:
        return jsonify(cat), 201
    return jsonify({"message": "Category already exists"}), 409


@closet_bp.route("/update_closet_item_category", methods=["POST"])
def update_item_category():
    user_id = get_user_id_from_token(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401
    data = request.get_json()
    item_id = data.get("item_id")
    category = data.get("category", "").strip()
    if not item_id:
        return jsonify({"message": "item_id required"}), 400
    from services.closet_service import update_closet_item_category
    update_closet_item_category(user_id, item_id, category)
    return jsonify({"message": "Category updated"}), 200

@closet_bp.route("/delete_closet_image", methods=["DELETE"])
def delete_image():
    user_id = get_user_id_from_token(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401

    filename = request.args.get("filename")
    if not filename:
        return jsonify({"message": "Missing filename"}), 400

    supa = get_supa()
    check = supa.table("closet_items").select("filepath").eq("user_id", user_id).eq("filename", filename).execute()
    if not check.data:
        return jsonify({"message": "Image not found"}), 404

    supa.table("closet_items").delete().eq("user_id", user_id).eq("filename", filename).execute()
    return jsonify({"message": "Image deleted"}), 200

@closet_bp.route("/static/<int:user_id>/<path:filename>")
def serve_image(user_id, filename):
    local_dir = os.path.join(UPLOAD_FOLDER, str(user_id))
    if os.path.isfile(os.path.join(local_dir, filename)):
        return send_from_directory(local_dir, filename)
    # Not on local disk (deployed instance) → redirect to Supabase Storage CDN.
    # Cache the redirect so repeat loads skip Railway entirely (straight from browser cache).
    from flask import redirect
    from storage_utils import public_url
    resp = redirect(public_url(f"{user_id}/{filename}"))
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


MAX_FILES_PER_UPLOAD = 8

_ITEM_SELECT = (
    "id, filename, filepath, tag_text, brand, size, category, tags, "
    "matched_brand, matched_title, icon_path, caption, type, color, style, season, "
    "fabric, vibe, keywords, emoticon_path, vector_embedding, "
    "subcategory, layering_role, occasion, formality_score"
)

@closet_bp.route("/upload_closet_images", methods=["POST"])
def upload_images():
    user_id = get_user_id_from_token(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401

    if "files" not in request.files:
        return jsonify({"message": "No files uploaded"}), 400

    files = request.files.getlist("files")[:MAX_FILES_PER_UPLOAD]
    if not files:
        return jsonify({"message": "Empty file list"}), 400

    supa = get_supa()
    user_folder = os.path.join(UPLOAD_FOLDER, str(user_id))
    os.makedirs(user_folder, exist_ok=True)

    queued = []
    uploaded_items = []

    for file in files:
        if not (file and file.filename):
            continue

        ext = os.path.splitext(file.filename)[1].lower()
        is_image = file.mimetype.startswith("image/") or ext in (".heic", ".heif")
        if not is_image:
            continue

        filename = secure_filename(file.filename).lower()
        filepath = os.path.join(user_folder, filename)

        try:
            file.save(filepath)
        except Exception as e:
            print(f"Save failed for {filename}: {e}")
            continue

        # Convert HEIC/HEIF → JPEG; failures are logged but never crash the pipeline
        if ext in (".heic", ".heif"):
            try:
                jpg_filename = filename.rsplit(".", 1)[0] + ".jpg"
                jpg_filepath = os.path.join(user_folder, jpg_filename)
                _PILImage.open(filepath).convert("RGB").save(jpg_filepath, "JPEG", quality=95)
                os.remove(filepath)
                filename = jpg_filename
                filepath = jpg_filepath
            except Exception as e:
                print(f"HEIC conversion failed for {filename}: {e}")
                if not os.path.exists(filepath):
                    continue  # can't proceed without a readable file

        # Push the original photo to Supabase Storage so the deployed app can
        # serve it via the /static redirect (local disk is ephemeral there).
        try:
            from storage_utils import upload_file
            upload_file(filepath, f"{user_id}/{filename}")
        except Exception as e:
            print(f"Storage upload failed for {filename}: {e}")

        try:
            tag_text = extract_tag_text(filepath)
            print(f"OCR tag for {filename}: {tag_text}")
        except Exception as e:
            print(f"OCR failed for {filename}: {e}")
            tag_text = None

        existing = supa.table("closet_items").select("id, icon_path").eq("user_id", user_id).eq("filename", filename).execute()
        has_icon = bool(existing.data and existing.data[0].get("icon_path"))

        supa.table("closet_items").upsert({
            "user_id": user_id,
            "filename": filename,
            "filepath": filepath,
            "tag_text": tag_text,
        }, on_conflict="user_id,filename").execute()

        # Return the full row so the frontend can render the card immediately
        item_res = supa.table("closet_items").select(_ITEM_SELECT).eq("user_id", user_id).eq("filename", filename).execute()
        if item_res.data:
            uploaded_items.append(_serialize_item(item_res.data[0], user_id))

        if not has_icon:
            queued.append((filepath, filename, user_id, tag_text or ""))
        else:
            print(f"Icon already exists for {filename}, skipping AI pipeline.")

    for args in queued:
        t = threading.Thread(target=_run_ai_pipeline, args=args, daemon=True)
        t.start()

    return jsonify({
        "message": f"Uploaded {len(uploaded_items)} file(s). AI tagging running in background.",
        "items": uploaded_items,
    }), 200


def _run_ai_pipeline(filepath, filename, user_id, tag_text=""):
    """Background: GPT-4o icon/tagging → CLIP embedding. FAISS runs only on user request."""
    print(f"AI pipeline starting for {filename}")
    try:
        generate_icon_from_image(filepath, user_id=user_id, filename=filename, tag_text=tag_text)
    except Exception as e:
        print(f"Icon/GPT pipeline error for {filename}: {e}")

    try:
        print(f"Generating CLIP embedding for: {filename}")
        embedding = generate_clip_embedding(filepath)
        save_embedding_to_db(user_id, filename, embedding)
        print(f"Embedding saved for {filename}")
    except Exception as e:
        print(f"Embedding failed for {filename}: {e}")


@closet_bp.route("/update_closet_metadata", methods=["POST"])
def update_metadata():
    user_id = get_user_id_from_token(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401

    data = request.json
    filename  = data.get("filename")
    name      = (data.get("name") or "").strip() or None
    brand     = data.get("brand")
    size      = data.get("size")
    save_only = data.get("save_only", False)

    if not filename:
        return jsonify({"message": "Missing filename"}), 400

    supa = get_supa()
    supa.table("closet_items").update({
        "matched_title": name,
        "brand": brand,
        "size": size,
    }).eq("user_id", user_id).eq("filename", filename).execute()

    if save_only:
        return jsonify({"message": "Saved"}), 200

    try:
        result = supa.table("closet_items").select("*").eq("user_id", user_id).eq("filename", filename).execute()
        row = result.data[0] if result.data else None
        if not row or row["vector_embedding"] is None:
            return jsonify({"message": "Metadata updated, but embedding is missing"}), 500

        image_emb = np.array(row["vector_embedding"], dtype=np.float32)
        query_emb = _blend_text_query(image_emb, name, row)

        gender_text = " ".join(filter(None, [name, row.get("subcategory"), row.get("matched_title")]))
        gender  = _detect_gender(gender_text)
        matches = search_similar_products(query_emb, brand, gender=gender)

        return jsonify({
            "message": "Metadata updated",
            "matches": matches
        }), 200

    except Exception as e:
        print(f"FAISS search error: {e}")
        return jsonify({
            "message": "Metadata updated, but FAISS search failed"
        }), 500


@closet_bp.route("/retag_metadata", methods=["POST"])
def retag_metadata():
    user_id = get_user_id_from_token(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401

    supa = get_supa()
    result = supa.table("closet_items").select("filename, filepath, tag_text").eq("user_id", user_id).execute()

    queued = 0
    for row in result.data:
        filepath = row.get("filepath")
        filename = row.get("filename")
        tag_text = row.get("tag_text") or ""
        if not filepath or not os.path.isfile(filepath):
            filepath = os.path.join(UPLOAD_FOLDER, str(user_id), filename) if filename else None
        if filepath and os.path.isfile(filepath):
            t = threading.Thread(
                target=retag_metadata_only,
                args=(filepath, user_id, filename, tag_text),
                daemon=True,
            )
            t.start()
            queued += 1

    return jsonify({"message": f"Re-tagging {queued} item(s) in background.", "count": queued}), 202


@closet_bp.route("/reprocess_icons", methods=["POST"])
def reprocess_icons():
    user_id = get_user_id_from_token(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401

    force = (request.json or {}).get("force", False)

    supa = get_supa()
    result = supa.table("closet_items").select("filename, filepath, icon_path").eq("user_id", user_id).execute()
    rows = [(r["filename"], r["filepath"]) for r in result.data if force or not r.get("icon_path")]

    if not rows:
        return jsonify({"message": "No items to reprocess.", "count": 0}), 200

    queued = 0
    for filename, filepath in rows:
        if filepath and os.path.isfile(filepath):
            t = threading.Thread(target=_run_ai_pipeline, args=(filepath, filename, user_id, ""), daemon=True)
            t.start()
            queued += 1
        else:
            guessed = os.path.join(UPLOAD_FOLDER, str(user_id), filename)
            if os.path.isfile(guessed):
                t = threading.Thread(target=_run_ai_pipeline, args=(guessed, filename, user_id, ""), daemon=True)
                t.start()
                queued += 1

    return jsonify({"message": f"Reprocessing {queued} item(s) in background.", "count": queued}), 202


@closet_bp.route("/faiss_text_search", methods=["POST"])
def faiss_text_search():
    user_id = get_user_id_from_token(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401

    data        = request.json
    filename    = data.get("filename")
    search_text = (data.get("search_text") or "").strip()
    brand       = data.get("brand") or None

    if not filename or not search_text:
        return jsonify({"message": "filename and search_text required"}), 400

    supa   = get_supa()
    result = supa.table("closet_items").select("vector_embedding").eq("user_id", user_id).eq("filename", filename).execute()
    row    = result.data[0] if result.data else None
    if not row or row.get("vector_embedding") is None:
        return jsonify({"message": "No embedding found for this item"}), 404

    image_emb = np.array(row["vector_embedding"], dtype=np.float32)
    # Use higher text weight (0.5) since the user explicitly typed this query.
    query_emb = _blend_text_query(image_emb, search_text, {}, text_weight=0.5)
    gender    = _detect_gender(search_text)
    matches   = search_similar_products(query_emb, brand, gender=gender)

    return jsonify({"matches": matches}), 200


@closet_bp.route("/save_match_selection", methods=["POST"])
def save_match_selection():
    user_id = get_user_id_from_token(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401

    data = request.json
    filename = data.get("filename")
    matched_brand = data.get("matched_brand")
    matched_title = data.get("matched_title")

    if not filename or not matched_brand or not matched_title:
        return jsonify({"message": "Missing fields"}), 400

    try:
        get_supa().table("closet_items").update({
            "matched_brand": matched_brand,
            "matched_title": matched_title,
        }).eq("user_id", user_id).eq("filename", filename).execute()
        return jsonify({"message": "Match saved successfully"}), 200
    except Exception as e:
        print(f"Error saving match: {e}")
        return jsonify({"message": "Internal server error"}), 500
