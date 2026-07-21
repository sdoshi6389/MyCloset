"""Outfit recommendation blueprint — /recommend"""
from flask import Blueprint, request, jsonify, send_from_directory
import jwt
import os
from db import get_supa
from config import JWT_SECRET

recommend_bp = Blueprint("recommend", __name__)


def _get_user_id(req) -> int | None:
    auth = req.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    try:
        payload = jwt.decode(auth.split(" ")[1], JWT_SECRET, algorithms=["HS256"])
        return payload["user_id"]
    except Exception:
        return None


@recommend_bp.route("/recommend", methods=["POST"])
def recommend():
    """
    Body:
      outfit      { slot: { id, color, vibe, style, formality_score, ... } | null }
      fill_slots  list[str] | null   — null = all empty slots with known categories
      mode        "closet" | "catalog"
      top_k       int (default 5, max 10)
    Response:
      { recommendations: { slot: [ { id, title, brand, color, icon_url, image_url,
                                     price, shop_url, source, score } ] } }
    """
    user_id = _get_user_id(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401

    data       = request.get_json(silent=True) or {}
    outfit     = data.get("outfit") or {}
    fill_slots = data.get("fill_slots")         # None = infer from empty slots
    mode       = data.get("mode", "closet")     # "closet" | "catalog"
    top_k      = min(int(data.get("top_k", 5)), 10)
    gender     = data.get("gender") or None     # "male" | "female" | None

    if mode not in ("closet", "catalog"):
        return jsonify({"message": "mode must be 'closet' or 'catalog'"}), 400
    if gender and gender not in ("male", "female"):
        gender = None

    try:
        from recommendation.engine import get_recommendations
        result = get_recommendations(
            user_id=user_id,
            outfit=outfit,
            fill_slots=fill_slots,
            mode=mode,
            top_k=top_k,
            gender=gender,
        )
        return jsonify(result), 200
    except Exception as e:
        print(f"❌ /recommend error: {e}")
        import traceback; traceback.print_exc()
        return jsonify({"message": "Recommendation error", "detail": str(e)}), 500


@recommend_bp.route("/recommend/feedback", methods=["POST"])
def feedback():
    """
    Record a user signal on a recommendation.
    Body:
      item_id   int | null   (closet item id, or null for catalog results)
      slot      str
      signal    "accept" | "reject" | "ignore"
      outfit_ctx  { slot: { id, ... } }   — snapshot of the outfit at the time
    """
    user_id = _get_user_id(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401

    data      = request.get_json(silent=True) or {}
    item_id   = data.get("item_id")
    slot      = data.get("slot")
    signal    = data.get("signal")
    outfit_ctx = data.get("outfit_ctx", {})

    if signal not in ("accept", "reject", "ignore"):
        return jsonify({"message": "signal must be accept | reject | ignore"}), 400

    supa = get_supa()
    try:
        supa.table("recommendation_feedback").insert({
            "user_id":    user_id,
            "item_id":    item_id,
            "slot":       slot,
            "signal":     signal,
            "outfit_ctx": outfit_ctx,
        }).execute()
    except Exception as e:
        print(f"⚠️  feedback insert failed: {e}")

    # Also emit to the new unified event log
    event_map = {"accept": "recommendation_added", "reject": "recommendation_disliked", "ignore": "recommendation_skipped"}
    try:
        from recommendation.rec_logging import log_event as _log_event
        _log_event(
            user_id=user_id,
            event_type=event_map.get(signal, "recommendation_skipped"),
            item_id=item_id,
            context={"slot": slot, "outfit_ctx": outfit_ctx},
        )
    except Exception:
        pass

    # For closet items: nudge the pref_vector toward or away from this item
    if item_id and signal in ("accept", "reject"):
        try:
            from recommendation.profile import update_pref_vector
            direction = 1 if signal == "accept" else -1
            update_pref_vector(user_id, item_id, direction)
        except Exception as e:
            print(f"⚠️  pref_vector update failed: {e}")

    return jsonify({"message": "Feedback recorded"}), 200


@recommend_bp.route("/recommend/extract_bg", methods=["POST"])
def extract_bg():
    """
    Strip background from a catalog product image using rembg (local, no API calls).
    Body: { url: str }
    Response: { extracted_url: "/catalog_extracted/<hash>.png" | null }
    Results are cached on disk — repeat calls for the same URL are instant.
    """
    data = request.get_json(silent=True) or {}
    image_url    = (data.get("url")           or "").strip()
    slot         = (data.get("slot")          or "").strip() or None
    product_url  = (data.get("product_url")   or "").strip() or None
    source_brand = (data.get("source_brand")  or "").strip() or None
    product_name = (data.get("product_name")  or "").strip() or None
    force        = bool(data.get("force", False))
    force_step   = int(data.get("force_step", 0))
    if not image_url:
        return jsonify({"extracted_url": None}), 400

    if force or force_step > 0:
        # Delete disk + DB cache so the item is reprocessed from the requested step
        try:
            from catalog_icon import _icon_path
            from db import get_supa
            p = _icon_path(image_url, slot)
            if os.path.exists(p):
                os.remove(p)
                print(f"🗑  force-cleared disk cache: {os.path.basename(p)}")
            cache_key = f"v3:{image_url}|{slot or ''}"
            get_supa().table("catalog_icon_cache").delete().eq("cache_key", cache_key).execute()
        except Exception as fe:
            print(f"⚠️  force-clear error: {fe}")

    try:
        from catalog_icon import extract_catalog_icon
        path, step_used = extract_catalog_icon(image_url, slot,
                                               product_url=product_url,
                                               source_brand=source_brand,
                                               product_name=product_name,
                                               force_step=force_step)
        if path:
            fname = os.path.basename(path)
            # Cache-bust forced re-extractions so the browser doesn't serve the old file
            import time as _time
            qs = f"?v={int(_time.time())}" if (force or force_step > 0) else ""
            return jsonify({
                "extracted_url": f"/catalog_extracted/{fname}{qs}",
                "from_cache": step_used == -1,
                "step_used": step_used,
            }), 200
        return jsonify({"extracted_url": None, "from_cache": False, "step_used": -1}), 200
    except Exception as e:
        print(f"❌ extract_bg error: {e}")
        return jsonify({"extracted_url": None}), 200


@recommend_bp.route("/catalog_extracted/<path:filename>")
def serve_catalog_extracted(filename):
    from bg_remove import CACHE_DIR
    return send_from_directory(CACHE_DIR, filename)


@recommend_bp.route("/recommend/events", methods=["POST"])
def log_event():
    """
    Log a user interaction with a recommendation.
    Body:
      event_type        str   — recommendation_added | recommendation_removed |
                                recommendation_disliked | recommendation_skipped |
                                outfit_saved | item_liked
      item_id           str | int | null
      outfit_id         int | null
      recommendation_id str | null
      context           dict  — arbitrary extra data (slot, score, etc.)
    """
    user_id = _get_user_id(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401

    data   = request.get_json(silent=True) or {}
    event  = data.get("event_type", "")

    VALID_EVENTS = {
        "recommendation_viewed", "recommendation_clicked",
        "recommendation_added",  "recommendation_removed",
        "recommendation_disliked", "recommendation_skipped",
        "outfit_saved", "outfit_posted", "item_liked", "item_skipped",
    }
    if event not in VALID_EVENTS:
        return jsonify({"message": f"Unknown event_type: {event}"}), 400

    try:
        from recommendation.rec_logging import log_event as _log_event
        _log_event(
            user_id=user_id,
            event_type=event,
            item_id=data.get("item_id"),
            outfit_id=data.get("outfit_id"),
            recommendation_id=data.get("recommendation_id"),
            context=data.get("context") or {},
        )
    except Exception as e:
        print(f"⚠️  /recommend/events failed: {e}")

    # Also update recommendation_logs was_* flags
    rec_id = data.get("recommendation_id")
    if rec_id:
        flag_map = {
            "recommendation_added":    "was_added",
            "recommendation_clicked":  "was_clicked",
            "outfit_saved":            "was_saved",
            "recommendation_disliked": "was_rejected",
        }
        flag = flag_map.get(event)
        if flag:
            try:
                from recommendation.rec_logging import mark_recommendation
                mark_recommendation(rec_id, flag)
            except Exception:
                pass

    # For strong negative signal, nudge pref_vector away from this item
    if event == "recommendation_disliked":
        item_id = data.get("item_id")
        if item_id:
            try:
                from recommendation.profile import update_pref_vector
                update_pref_vector(user_id, int(item_id), direction=-1)
            except Exception:
                pass

    return jsonify({"message": "Event logged"}), 200


@recommend_bp.route("/recommend/refresh_profile", methods=["POST"])
def refresh_profile():
    """Force-recompute the user style profile from their current closet."""
    user_id = _get_user_id(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401

    try:
        from recommendation.profile import compute_user_profile
        profile = compute_user_profile(user_id)
        return jsonify({
            "message": "Profile refreshed",
            "formality_center": profile.get("formality_center"),
            "top_vibes": sorted(
                (profile.get("vibe_weights") or {}).items(),
                key=lambda x: -x[1]
            )[:5],
        }), 200
    except Exception as e:
        print(f"❌ /recommend/refresh_profile error: {e}")
        return jsonify({"message": "Error", "detail": str(e)}), 500
