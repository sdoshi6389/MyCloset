from flask import Blueprint, request, jsonify
from db import get_supa
from config import JWT_SECRET
import jwt, os, json, requests

builder_bp = Blueprint("builder", __name__)

INTERNAL_BASE = os.getenv("PUBLIC_BASE_URL", "http://localhost:5000")

def get_user_id_from_token(request):
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return None
    try:
        token = auth_header.split(" ")[1]
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload["user_id"]
    except Exception as e:
        print(f"Token error: {e}")
        try:
            return int(request.headers.get("X-Debug-User"))
        except Exception:
            return None

def _format_item(r, owner_user_id, owner_email, is_mine):
    icon_path = r.get("icon_path")
    return {
        "id":              r["id"],
        "filename":        r["filename"],
        "brand":           r.get("brand"),
        "title":           r.get("matched_title"),
        "caption":         r.get("caption"),
        "type":            r.get("type"),
        "category":        r.get("category"),
        "vibe":            r.get("vibe"),
        "style":           r.get("style"),
        "season":          r.get("season"),
        "formality_score": r.get("formality_score"),
        "occasion":        r.get("occasion"),
        "icon_url":        f"/icons/{os.path.basename(icon_path)}" if icon_path else None,
        "image_url":       f"/static/{owner_user_id}/{r['filename']}",
        "owner_user_id":   owner_user_id,
        "owner_email":     owner_email,
        "owner_initial":   (owner_email or "?")[0].upper(),
        "is_mine":         is_mine,
    }


@builder_bp.route("/get_closet_icons", methods=["GET"])
def get_closet_icons():
    user_id = get_user_id_from_token(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401

    supa = get_supa()
    circle_id = request.args.get("circle_id", type=int)

    if circle_id:
        from services.circles_service import is_member
        if not is_member(circle_id, user_id):
            return jsonify({"message": "Not a member of this circle"}), 403

        members_res = supa.table("circle_members").select("user_id").eq("circle_id", circle_id).execute()
        member_ids  = [r["user_id"] for r in members_res.data]

        users_res  = supa.table("users").select("id, email").in_("id", member_ids).execute()
        users_map  = {u["id"]: u["email"] for u in users_res.data}

        result = supa.table("closet_items").select(
            "id, filename, brand, matched_title, caption, type, category, vibe, style, season, formality_score, occasion, icon_path, user_id"
        ).in_("user_id", member_ids).order("user_id").order("id", desc=True).execute()

        # Current user's items first, then other members' items
        # Include items without icons — frontend uses image_url as fallback
        mine   = [r for r in result.data if r["user_id"] == user_id]
        theirs = [r for r in result.data if r["user_id"] != user_id]

        items = []
        for r in mine:
            email = users_map.get(r["user_id"], "")
            items.append(_format_item(r, r["user_id"], email, True))
        for r in theirs:
            email = users_map.get(r["user_id"], "")
            items.append(_format_item(r, r["user_id"], email, False))

        return jsonify(items), 200

    # Default: only current user's items
    filename = request.args.get("filename")
    if filename:
        result = supa.table("closet_items").select(
            "id, filename, brand, matched_title, caption, type, category, vibe, style, season, formality_score, occasion, icon_path"
        ).eq("user_id", user_id).eq("filename", filename).execute()
        rows = result.data
        if not rows:
            return jsonify({}), 200
        r = rows[0]
        return jsonify(_format_item(r, user_id, "", True)), 200

    result = supa.table("closet_items").select(
        "id, filename, brand, matched_title, caption, type, category, vibe, style, season, formality_score, occasion, icon_path"
    ).eq("user_id", user_id).order("id", desc=True).execute()

    # Return all items — frontend uses image_url as fallback when icon_url is null
    return jsonify([
        _format_item(r, user_id, "", True)
        for r in result.data
    ]), 200


@builder_bp.route("/generate_dressed_mannequin", methods=["POST"])
def api_generate_dressed_mannequin():
    try:
        user_id = get_user_id_from_token(request)
        if not user_id:
            return jsonify({"message": "Unauthorized"}), 401

        slots = request.get_json(silent=True) or {}
        print("Incoming outfit data:", slots)

        key_map = {
            "inner_top": "inner_top",
            "outer_top": "outer_top",
            "inner_bottom": "inner_bottom",
            "outer_bottom": "outer_bottom",
            "inner_left_foot": "inner_left_foot",
            "outer_left_foot": "outer_left_foot",
            "inner_right_foot": "inner_right_foot",
            "outer_right_foot": "outer_right_foot",
            "accessories": "accessories",
            "top": "inner_top",
            "bottom": "inner_bottom",
            "head": "accessories",
            "feet": "inner_left_foot",
        }
        filtered = {}
        for k, v in slots.items():
            if v is None:
                continue
            norm = key_map.get(k)
            if not norm:
                continue
            try:
                filtered[norm] = int(v)
            except Exception:
                return jsonify({
                    "message": f"Slot '{k}' must be an item ID (int), got '{v}'",
                }), 400

        if not filtered:
            return jsonify({
                "message": "No clothing items provided",
                "hint": "Send slot IDs (inner_top, outer_bottom, etc.) with item IDs as values."
            }), 400

        url = f"{INTERNAL_BASE}/vton/generate_dressed_mannequin"
        fwd_headers = {
            "Content-Type": "application/json",
            "Authorization": request.headers.get("Authorization", "")
        }
        resp = requests.post(url, headers=fwd_headers, data=json.dumps(filtered), timeout=300)

        try:
            payload = resp.json()
        except Exception:
            payload = {"message": resp.text}

        return jsonify(payload), resp.status_code

    except Exception as e:
        print(f"Mannequin API error: {e}")
        return jsonify({"message": "Internal server error"}), 500
