from flask import Blueprint, request, jsonify, send_from_directory
import os
import re
import jwt
import hashlib
import threading
from werkzeug.utils import secure_filename
from db import get_supa
from config import JWT_SECRET
from ocr_utils import extract_tag_text
from callable_embedding import (generate_clip_embedding, save_embedding_to_db,
                                is_loaded as clip_is_loaded)
import warmup
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

# A phone photo arrives at about 4300x5700 and 6-28 MB. Nothing downstream wants
# that: the card shows it a few hundred pixels wide, CLIP sees 224, and GPT
# downsamples it anyway. Carrying the full file only buys a slow card, a slow
# Storage push and a slow upload to GPT -- re-encoding a 28 MB PNG at 2560px
# takes 0.8 s and leaves 1.5 MB, which then pushes to Storage in 1.4 s instead
# of 8.6 s.
MAX_PHOTO_PX = 2560
REENCODE_OVER_BYTES = 3 * 1024 * 1024


def _normalise_photo(filepath: str, filename: str) -> tuple[str, str]:
    """Convert HEIC and shrink oversized photos. Returns the path and name to use.

    Hands back the original untouched if anything fails: a photo that is merely
    large is still a usable photo, and losing the upload over it would be worse
    than the lag this avoids.
    """
    ext = os.path.splitext(filename)[1].lower()
    heic = ext in (".heic", ".heif")
    try:
        with _PILImage.open(filepath) as src:
            too_big = max(src.size) > MAX_PHOTO_PX
            heavy = os.path.getsize(filepath) > REENCODE_OVER_BYTES
            if not (heic or too_big or heavy):
                return filepath, filename
            # Alpha is worth keeping where it exists; everything else becomes a
            # JPEG, which is where most of the saving comes from.
            keep_alpha = src.mode in ("RGBA", "LA") and not heic
            im = src.convert("RGBA" if keep_alpha else "RGB")
            if too_big:
                im.thumbnail((MAX_PHOTO_PX, MAX_PHOTO_PX), _PILImage.LANCZOS)
    except Exception as e:
        print(f"Photo normalise failed for {filename}: {e}")
        return filepath, filename

    stem = os.path.splitext(filename)[0]
    if keep_alpha:
        new_name, fmt, kw = stem + ".png", "PNG", {"optimize": True}
    else:
        new_name, fmt, kw = stem + ".jpg", "JPEG", {"quality": 90, "optimize": True}
    new_path = os.path.join(os.path.dirname(filepath), new_name)
    try:
        im.save(new_path, fmt, **kw)
    except Exception as e:
        print(f"Photo re-encode failed for {filename}: {e}")
        return filepath, filename

    if os.path.normcase(new_path) != os.path.normcase(filepath):
        try:
            os.remove(filepath)
        except OSError:
            pass
    return new_path, new_name


_ITEM_SELECT = (
    "id, filename, filepath, tag_text, brand, size, category, tags, "
    "matched_brand, matched_title, icon_path, caption, type, color, style, season, "
    "fabric, vibe, keywords, emoticon_path, vector_embedding, "
    "subcategory, layering_role, occasion, formality_score, "
    # wear tracking (migration 010)
    "wear_count, in_laundry, last_worn"
)

# The upsert returns every column; the response carries the same set the
# listing endpoint sends, so a freshly uploaded card and a reloaded one match.
_ITEM_COLUMNS = tuple(c.strip() for c in _ITEM_SELECT.split(",") if c.strip())


# How alike two photos have to be before the upload stops to ask.
#
# Calibrated against this closet rather than guessed. Re-embedding a photo that
# is already in the closet scores 1.0000, but two genuinely different pairs of
# grey cargo joggers score 0.9972 -- CLIP cannot separate "the same garment
# again" from "a garment that looks almost the same", and no threshold can. So
# this asks rather than decides, and sits high enough that only one existing
# pair in a closet of 47 would raise the question.
DUPLICATE_SIM = 0.985


def _closest_existing(user_id: int, embedding, skip_filename: str) -> dict | None:
    """The closet item this photo most resembles, if it resembles one enough."""
    import numpy as np
    from recommendation.scorer import _parse_vector
    from storage_utils import icon_urls

    vec = np.asarray(embedding, dtype=np.float32)
    norm = np.linalg.norm(vec)
    if not norm:
        return None
    vec = vec / norm

    rows = (get_supa().table("closet_items")
            .select("id, filename, matched_title, caption, type, brand, "
                    "icon_path, vector_embedding")
            .eq("user_id", user_id).execute().data) or []

    best, best_sim = None, 0.0
    for r in rows:
        if r["filename"] == skip_filename:
            continue
        other = _parse_vector(r.get("vector_embedding"))
        if other is None or not len(other):
            continue
        other = np.asarray(other, dtype=np.float32)
        n = np.linalg.norm(other)
        if not n:
            continue
        sim = float(vec @ (other / n))
        if sim > best_sim:
            best, best_sim = r, sim

    if not best or best_sim < DUPLICATE_SIM:
        return None
    full, thumb = icon_urls(best.get("icon_path"))
    return {
        "id":         best["id"],
        "filename":   best["filename"],
        "title":      (best.get("matched_title") or best.get("caption")
                       or best.get("type") or "Untitled"),
        "brand":      best.get("brand"),
        "icon_url":   full,
        "thumb_url":  thumb,
        "url":        f"/static/{user_id}/{best['filename']}",
        "similarity": round(best_sim, 4),
    }


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
    duplicates = {}

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

        filepath, filename = _normalise_photo(filepath, filename)
        if not os.path.exists(filepath):
            continue  # can't proceed without a readable file

        # Everything else -- the Storage push, the tag OCR, the icon and the
        # embedding -- runs after the response. /static serves the file just
        # written to local disk, so the card renders without waiting on any of
        # it, and the upsert hands back the stored row, so neither the select
        # before it nor the one after it is needed.
        row = (supa.table("closet_items").upsert({
            "user_id": user_id,
            "filename": filename,
            "filepath": filepath,
        }, on_conflict="user_id,filename").execute().data or [None])[0]
        if not row:
            print(f"Upsert returned no row for {filename}")
            continue

        uploaded_items.append(
            _serialize_item({k: row.get(k) for k in _ITEM_COLUMNS}, user_id))

        # The embedding is needed either way, and having it here is what makes
        # the duplicate check possible before any of the paid work starts.
        #
        # Only when the model is already resident, though. Loading it takes
        # about a minute, and an upload that hangs for a minute is a worse
        # outcome than one that does not notice a duplicate -- those uploads go
        # through the normal path, which embeds behind the response as before.
        match, embedding = None, None
        if clip_is_loaded():
            try:
                embedding = generate_clip_embedding(filepath)
                save_embedding_to_db(user_id, filename, embedding)
                match = _closest_existing(user_id, embedding, filename)
            except Exception as e:
                print(f"Duplicate check skipped for {filename}: {type(e).__name__}: {e}")
                embedding = None
        else:
            print(f"CLIP not resident — {filename} skips the duplicate check")
            warmup.kick()

        if match:
            # Hold everything -- Storage, OCR, GPT -- until the person says this
            # really is a new piece. The card still renders from local disk.
            duplicates[filename] = match
            print(f"Possible duplicate: {filename} ~ {match['filename']} "
                  f"({match['similarity']})")
        else:
            queued.append((filepath, filename, user_id, bool(row.get("icon_path")),
                           embedding is not None))

    for args in queued:
        t = threading.Thread(target=_finish_upload, args=args, daemon=True)
        t.start()

    return jsonify({
        "message": f"Uploaded {len(uploaded_items)} file(s). AI tagging running in background.",
        "items": uploaded_items,
        "duplicates": duplicates,
    }), 200


@closet_bp.route("/closet/confirm_upload", methods=["POST"])
def confirm_upload():
    """Release an upload that was held back as a possible duplicate."""
    user_id = get_user_id_from_token(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401

    filename = ((request.get_json(silent=True) or {}).get("filename") or "").strip()
    if not filename:
        return jsonify({"message": "Missing filename"}), 400

    row = (get_supa().table("closet_items").select("filepath, icon_path")
           .eq("user_id", user_id).eq("filename", filename).execute().data or [None])[0]
    if not row:
        return jsonify({"message": "Item not found"}), 404

    filepath = row.get("filepath") or os.path.join(UPLOAD_FOLDER, str(user_id), filename)
    threading.Thread(target=_finish_upload,
                     args=(filepath, filename, user_id, bool(row.get("icon_path")), True),
                     daemon=True).start()
    return jsonify({"message": "Processing started"}), 200


@closet_bp.route("/closet/add_from_catalog", methods=["POST"])
def add_from_catalog():
    """Put a catalog piece into the user's closet.

    The expensive parts of a normal upload are already done for a catalog item:
    it has a title, a brand and, once extracted, a garment-only cutout. So this
    skips the GPT metadata and icon steps entirely and reuses what the
    recommendation already carried, leaving only the CLIP embedding, which runs
    behind the response like it does for an upload.
    """
    user_id = get_user_id_from_token(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    image_url = (data.get("icon_url") or data.get("image_url") or "").strip()
    if not image_url:
        return jsonify({"message": "No image to add"}), 400

    title = (data.get("title") or "").strip() or None
    brand = (data.get("brand") or "").strip() or None
    slot  = (data.get("slot") or "").strip() or None
    from recommendation.engine import SLOT_CATEGORIES
    category = (SLOT_CATEGORIES.get(slot) or [None])[0]

    # A stable name per product, so adding the same piece twice updates the one
    # row rather than filling the closet with copies of it.
    digest = hashlib.sha1(f"{image_url}|{slot or ''}".encode("utf-8")).hexdigest()[:10]
    ext = ".png" if ".png" in image_url.lower().split("?")[0][-5:] else ".jpg"
    filename = f"catalog_{digest}{ext}"

    user_folder = os.path.join(UPLOAD_FOLDER, str(user_id))
    os.makedirs(user_folder, exist_ok=True)
    filepath = os.path.join(user_folder, filename)

    try:
        import requests as _req
        r = _req.get(image_url, timeout=60)
        if r.status_code != 200 or not r.content:
            return jsonify({"message": f"Could not fetch the image ({r.status_code})"}), 502
        with open(filepath, "wb") as f:
            f.write(r.content)
    except Exception as e:
        print(f"add_from_catalog: fetch failed for {image_url[:80]}: {e}")
        return jsonify({"message": "Could not fetch the image"}), 502

    filepath, filename = _normalise_photo(filepath, filename)

    # The cutout is already published, so storing its URL is enough -- re-encoding
    # it to WebP and uploading it again under icons/ cost 14 s of the click for a
    # second copy of a file Storage was already serving. It has no 320px thumb
    # though, and a grid should not pull the full file, so publish just that.
    icon_path = image_url if image_url.startswith("http") else None
    if icon_path:
        try:
            from storage_utils import upload_thumb
            upload_thumb(filepath, icon_path.split("/")[-1])
        except Exception as e:
            print(f"add_from_catalog: thumb failed for {filename}: {e}")

    supa = get_supa()
    row = (supa.table("closet_items").upsert({
        "user_id":       user_id,
        "filename":      filename,
        "filepath":      filepath,
        "brand":         brand,
        "matched_title": title,
        "caption":       title,
        "category":      category,
        "color":         (data.get("color") or "").strip() or None,
        "icon_path":     icon_path,
    }, on_conflict="user_id,filename").execute().data or [None])[0]
    if not row:
        return jsonify({"message": "Could not save the item"}), 500

    threading.Thread(target=_finish_catalog_add,
                     args=(filepath, filename, user_id), daemon=True).start()

    return jsonify({
        "message": "Added to your closet",
        "item": _serialize_item({k: row.get(k) for k in _ITEM_COLUMNS}, user_id),
    }), 200


def _finish_catalog_add(filepath, filename, user_id):
    """Storage copy and CLIP embedding for a piece added from the catalog."""
    try:
        from storage_utils import upload_file
        upload_file(filepath, f"{user_id}/{filename}")
    except Exception as e:
        print(f"Storage upload failed for {filename}: {e}")
    try:
        embedding = generate_clip_embedding(filepath)
        save_embedding_to_db(user_id, filename, embedding)
        print(f"Embedding saved for {filename}")
    except Exception as e:
        print(f"Embedding failed for {filename}: {e}")


def _ensure_local_file(user_id: int, filename: str) -> str | None:
    """
    Return a local path for the given closet item.
    Checks the local upload folder first; if not found (Railway/deployed), downloads
    from Supabase Storage to a temp file and returns that path.
    The caller is responsible for deleting the temp file after use.
    """
    local = os.path.join(UPLOAD_FOLDER, str(user_id), filename)
    if os.path.isfile(local):
        return local
    # Try Supabase Storage download
    try:
        from storage_utils import BUCKET, _SUPABASE_URL
        import requests as _req, tempfile as _tmp
        cdn_url = f"{_SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{user_id}/{filename}"
        r = _req.get(cdn_url, timeout=60)
        if r.status_code == 200:
            suffix = os.path.splitext(filename)[1] or ".jpg"
            tmp = _tmp.NamedTemporaryFile(suffix=suffix, delete=False)
            tmp.write(r.content)
            tmp.close()
            print(f"⬇️  Downloaded {filename} from Storage to temp file")
            return tmp.name
        print(f"⚠️  Storage download {filename} returned {r.status_code}")
    except Exception as e:
        print(f"⚠️  Storage download failed for {filename}: {e}")
    return None


def _finish_upload(filepath, filename, user_id, has_icon=False, embedded=False):
    """Everything the upload response does not have to wait for.

    Pushing the photo to Storage was 4-9 s of the request on its own, and tag
    OCR another 0.5 s once its models are warm -- 23 s on the first call of a
    process, while the detector, reader and upscaler load. Neither changes what
    the new card shows, so both moved off the request.
    """
    try:
        from storage_utils import upload_file
        upload_file(filepath, f"{user_id}/{filename}")
    except Exception as e:
        print(f"Storage upload failed for {filename}: {e}")

    tag_text = ""
    try:
        tag_text = extract_tag_text(filepath) or ""
        print(f"OCR tag for {filename}: {tag_text!r}")
        if tag_text:
            get_supa().table("closet_items").update({"tag_text": tag_text}) \
                .eq("user_id", user_id).eq("filename", filename).execute()
    except Exception as e:
        print(f"OCR failed for {filename}: {e}")

    if has_icon:
        print(f"Icon already exists for {filename}, skipping AI pipeline.")
        return
    _run_ai_pipeline(filepath, filename, user_id, tag_text, embedded=embedded)


def _run_ai_pipeline(filepath, filename, user_id, tag_text="", embedded=False):
    """Background: GPT-4o icon/tagging → CLIP embedding. FAISS runs only on user request."""
    print(f"AI pipeline starting for {filename}")
    try:
        generate_icon_from_image(filepath, user_id=user_id, filename=filename, tag_text=tag_text)
    except Exception as e:
        print(f"Icon/GPT pipeline error for {filename}: {e}")

    if embedded:
        # The upload already made one for the duplicate check.
        return
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
        filename = row.get("filename")
        tag_text = row.get("tag_text") or ""
        if not filename:
            continue

        def _retag_task(fn, uid, tt):
            fp = _ensure_local_file(uid, fn)
            if not fp:
                print(f"⚠️  retag: no file found for {fn}")
                return
            is_temp = not fp.startswith(os.path.join(UPLOAD_FOLDER, str(uid)))
            try:
                retag_metadata_only(fp, uid, fn, tt)
            finally:
                if is_temp and os.path.exists(fp):
                    os.remove(fp)

        t = threading.Thread(target=_retag_task, args=(filename, user_id, tag_text), daemon=True)
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
    for filename, _stored_filepath in rows:
        if not filename:
            continue

        def _reprocess_task(fn, uid):
            fp = _ensure_local_file(uid, fn)
            if not fp:
                print(f"⚠️  reprocess: no file found for {fn}")
                return
            is_temp = not fp.startswith(os.path.join(UPLOAD_FOLDER, str(uid)))
            try:
                _run_ai_pipeline(fp, fn, uid, "")
            finally:
                if is_temp and os.path.exists(fp):
                    os.remove(fp)

        t = threading.Thread(target=_reprocess_task, args=(filename, user_id), daemon=True)
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
