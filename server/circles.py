from flask import Blueprint, request, jsonify
from db import get_supa
from config import JWT_SECRET
from services.circles_service import (
    create_circle, get_user_circles, get_circle_members,
    add_member, remove_member, delete_circle, is_member,
)
import jwt

circles_bp = Blueprint("circles", __name__, url_prefix="/circles")


def get_user_id_from_token(request):
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return None
    try:
        token = auth_header.split(" ")[1]
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload["user_id"]
    except Exception:
        return None


@circles_bp.route("", methods=["GET"])
def list_circles():
    user_id = get_user_id_from_token(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401
    return jsonify(get_user_circles(user_id)), 200


@circles_bp.route("", methods=["POST"])
def create():
    user_id = get_user_id_from_token(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401
    data = request.get_json()
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"message": "Circle name required"}), 400
    circle_id = create_circle(user_id, name, data.get("description"))
    return jsonify({"id": circle_id, "message": "Circle created"}), 201


@circles_bp.route("/<int:circle_id>", methods=["DELETE"])
def remove_circle(circle_id):
    user_id = get_user_id_from_token(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401
    ok = delete_circle(circle_id, user_id)
    if not ok:
        return jsonify({"message": "Not found or not owner"}), 404
    return jsonify({"message": "Deleted"}), 200


@circles_bp.route("/<int:circle_id>/members", methods=["GET"])
def members(circle_id):
    user_id = get_user_id_from_token(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401
    if not is_member(circle_id, user_id):
        return jsonify({"message": "Not a member"}), 403
    return jsonify(get_circle_members(circle_id)), 200


@circles_bp.route("/<int:circle_id>/members", methods=["POST"])
def add(circle_id):
    user_id = get_user_id_from_token(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401

    data = request.get_json()
    email = data.get("email", "").strip()
    if not email:
        return jsonify({"message": "Email required"}), 400

    supa = get_supa()
    result = supa.table("users").select("id").eq("email", email).execute()
    row = result.data[0] if result.data else None
    if not row:
        return jsonify({"message": "User not found"}), 404

    add_member(circle_id, row["id"], user_id)
    return jsonify({"message": "Member added"}), 200


@circles_bp.route("/<int:circle_id>/members/<int:target_id>", methods=["DELETE"])
def kick(circle_id, target_id):
    user_id = get_user_id_from_token(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401
    remove_member(circle_id, target_id, user_id)
    return jsonify({"message": "Member removed"}), 200


@circles_bp.route("/<int:circle_id>/combined-closet", methods=["GET"])
def combined_closet(circle_id):
    user_id = get_user_id_from_token(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401
    if not is_member(circle_id, user_id):
        return jsonify({"message": "Not a member"}), 403

    supa = get_supa()

    members_res = supa.table("circle_members").select("user_id").eq("circle_id", circle_id).execute()
    member_ids = [r["user_id"] for r in members_res.data]
    if not member_ids:
        return jsonify([]), 200

    items_res = supa.table("closet_items").select(
        "id, filename, brand, category, icon_path, caption, type, color, style, season, user_id"
    ).in_("user_id", member_ids).order("user_id").order("id").execute()

    users_res = supa.table("users").select("id, email").in_("id", member_ids).execute()
    users_map = {u["id"]: u["email"] for u in users_res.data}

    items = []
    for item in items_res.data:
        owner_email = users_map.get(item["user_id"], "")
        items.append({
            **item,
            "url": f"/static/{item['user_id']}/{item['filename']}",
            "owner_email": owner_email,
            "owner_initial": (owner_email or "?")[0].upper(),
        })
    return jsonify(items), 200


@circles_bp.route("/<int:circle_id>/combined-outfits", methods=["GET"])
def combined_outfits(circle_id):
    user_id = get_user_id_from_token(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401
    if not is_member(circle_id, user_id):
        return jsonify({"message": "Not a member"}), 403

    supa = get_supa()

    members_res = supa.table("circle_members").select("user_id").eq("circle_id", circle_id).execute()
    member_ids = [r["user_id"] for r in members_res.data]
    if not member_ids:
        return jsonify([]), 200

    outfits_res = supa.table("outfits").select(
        "id, name, occasion, notes, rating, created_at, user_id"
    ).in_("user_id", member_ids).order("created_at", desc=True).execute()

    users_res = supa.table("users").select("id, email").in_("id", member_ids).execute()
    users_map = {u["id"]: u["email"] for u in users_res.data}

    outfit_ids = [o["id"] for o in outfits_res.data]
    all_items_res = {}
    if outfit_ids:
        oi_res = supa.table("outfit_items").select(
            "outfit_id, slot, closet_item_id, closet_items(id, filename, brand, icon_path, category, user_id)"
        ).in_("outfit_id", outfit_ids).execute()
        for r in oi_res.data:
            oid = r["outfit_id"]
            ci = r.get("closet_items") or {}
            all_items_res.setdefault(oid, []).append({
                "slot": r["slot"],
                "closet_item_id": r["closet_item_id"],
                "filename": ci.get("filename"),
                "brand": ci.get("brand"),
                "icon_path": ci.get("icon_path"),
                "category": ci.get("category"),
                "url": f"/static/{ci.get('user_id')}/{ci.get('filename')}",
            })

    outfits = []
    for outfit in outfits_res.data:
        owner_email = users_map.get(outfit["user_id"], "")
        outfits.append({
            "id": outfit["id"],
            "name": outfit["name"],
            "occasion": outfit["occasion"],
            "notes": outfit["notes"],
            "rating": outfit["rating"],
            "created_at": outfit["created_at"],
            "owner_id": outfit["user_id"],
            "owner_email": owner_email,
            "owner_initial": (owner_email or "?")[0].upper(),
            "items": all_items_res.get(outfit["id"], []),
        })
    return jsonify(outfits), 200


@circles_bp.route("/<int:circle_id>/feed", methods=["GET"])
def circle_feed(circle_id):
    user_id = get_user_id_from_token(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401
    if not is_member(circle_id, user_id):
        return jsonify({"message": "Not a member"}), 403

    limit  = min(int(request.args.get("limit", 20)), 50)
    offset = int(request.args.get("offset", 0))

    supa = get_supa()

    members_res = supa.table("circle_members").select("user_id").eq("circle_id", circle_id).execute()
    member_ids = [r["user_id"] for r in members_res.data]
    if not member_ids:
        return jsonify([]), 200

    posts_res = supa.table("posts").select(
        "id, user_id, caption, visibility, outfit_id, circle_id, created_at"
    ).in_("user_id", member_ids).order("created_at", desc=True).limit(limit).offset(offset).execute()

    author_ids = list({p["user_id"] for p in posts_res.data})
    users_map = {}
    if author_ids:
        users_res = supa.table("users").select("id, email").in_("id", author_ids).execute()
        users_map = {u["id"]: u["email"] for u in users_res.data}

    posts = []
    for post in posts_res.data:
        post_id = post["id"]

        images_res = supa.table("post_images").select("image_path").eq("post_id", post_id).order("id").execute()
        images = [
            {"url": f"/feed/images/{r['image_path'].replace(chr(92), '/').split('/')[-1]}"}
            for r in images_res.data
        ]

        likes_res = supa.table("post_likes").select("user_id", count="exact").eq("post_id", post_id).execute()
        like_count = likes_res.count or 0

        liked_res = supa.table("post_likes").select("user_id").eq("post_id", post_id).eq("user_id", user_id).execute()
        liked = len(liked_res.data) > 0

        author_email = users_map.get(post["user_id"], "")
        posts.append({
            "id":           post_id,
            "author_id":    post["user_id"],
            "author_email": author_email,
            "caption":      post["caption"],
            "visibility":   post["visibility"],
            "outfit_id":    post["outfit_id"],
            "circle_id":    post["circle_id"],
            "created_at":   post["created_at"],
            "like_count":   like_count,
            "liked":        liked,
            "images":       images,
        })
    return jsonify(posts), 200


@circles_bp.route("/<int:circle_id>/member/<int:member_id>/closet", methods=["GET"])
def member_closet(circle_id, member_id):
    user_id = get_user_id_from_token(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401
    if not is_member(circle_id, user_id):
        return jsonify({"message": "You are not in this circle"}), 403
    if not is_member(circle_id, member_id):
        return jsonify({"message": "Target user is not in this circle"}), 403

    supa = get_supa()
    result = supa.table("closet_items").select(
        "id, filename, brand, category, icon_path, caption, type, color, style, season"
    ).eq("user_id", member_id).order("id").execute()

    items = []
    for item in result.data:
        items.append({
            **item,
            "url": f"/static/{member_id}/{item['filename']}",
        })
    return jsonify(items), 200
