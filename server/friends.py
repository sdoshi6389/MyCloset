from flask import Blueprint, request, jsonify
from db import get_supa
from config import JWT_SECRET
import jwt
import datetime

social_bp = Blueprint("social", __name__)

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


@social_bp.route("/search_users", methods=["GET"])
def search_users():
    query = request.args.get("q", "").strip().lower()
    user_id = get_user_id_from_token(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401

    supa = get_supa()

    friends_res = supa.table("friends").select("friend_id").eq("user_id", user_id).execute()
    friends_ids = {r["friend_id"] for r in friends_res.data}

    users_res = supa.table("users").select("id, email").ilike("email", f"%{query}%").neq("id", user_id).execute()
    filtered = [{"id": r["id"], "email": r["email"]} for r in users_res.data if r["id"] not in friends_ids]

    sent_res = supa.table("friend_requests").select("receiver_id").eq("sender_id", user_id).eq("status", "pending").execute()
    pending_sent = [r["receiver_id"] for r in sent_res.data]

    recv_res = supa.table("friend_requests").select("sender_id").eq("receiver_id", user_id).eq("status", "pending").execute()
    pending_received = [r["sender_id"] for r in recv_res.data]

    return jsonify({
        "results": filtered,
        "pending_sent": pending_sent,
        "pending_received": pending_received
    })


@social_bp.route("/send_friend_request", methods=["POST"])
def send_friend_request():
    user_id = get_user_id_from_token(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401

    data = request.get_json()
    target_id = data.get("target_id")

    supa = get_supa()
    existing = supa.table("friend_requests").select("status").eq("sender_id", user_id).eq("receiver_id", target_id).execute()
    row = existing.data[0] if existing.data else None

    if row:
        status = row["status"]
        if status == "pending":
            return jsonify({"message": "Request already sent and pending"}), 400
        elif status == "accepted":
            return jsonify({"message": "You are already friends"}), 400
        elif status == "rejected":
            supa.table("friend_requests").update({
                "status": "pending",
                "timestamp": datetime.datetime.utcnow().isoformat(),
            }).eq("sender_id", user_id).eq("receiver_id", target_id).execute()
            return jsonify({"message": "Friend request re-sent"}), 200
    else:
        supa.table("friend_requests").insert({
            "sender_id": user_id,
            "receiver_id": target_id,
            "status": "pending",
        }).execute()
        return jsonify({"message": "Friend request sent"}), 200


@social_bp.route("/respond_to_request", methods=["POST"])
def respond_to_request():
    user_id = get_user_id_from_token(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401

    data = request.get_json()
    sender_id = data.get("sender_id")
    accepted = data.get("accepted")

    supa = get_supa()
    if accepted:
        supa.table("friend_requests").update({"status": "accepted"}).eq("sender_id", sender_id).eq("receiver_id", user_id).eq("status", "pending").execute()
        supa.table("friends").insert([
            {"user_id": user_id, "friend_id": sender_id},
            {"user_id": sender_id, "friend_id": user_id},
        ]).execute()
    else:
        supa.table("friend_requests").update({"status": "rejected"}).eq("sender_id", sender_id).eq("receiver_id", user_id).eq("status", "pending").execute()

    return jsonify({"message": "Response recorded"})


@social_bp.route("/get_friends", methods=["GET"])
def get_friends():
    user_id = get_user_id_from_token(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401

    supa = get_supa()
    friends_res = supa.table("friends").select("friend_id").eq("user_id", user_id).execute()
    friend_ids = [r["friend_id"] for r in friends_res.data]

    if not friend_ids:
        return jsonify([]), 200

    users_res = supa.table("users").select("id, email, status_caption, last_seen").in_("id", friend_ids).execute()

    def format_time(ts_str):
        if not ts_str:
            return "Unknown"
        try:
            ts = datetime.datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            now = datetime.datetime.now(datetime.timezone.utc)
            delta = now - ts
            if delta.total_seconds() < 300:
                return "Online"
            elif delta.total_seconds() < 3600:
                return f"Last seen {int(delta.total_seconds() // 60)} min ago"
            else:
                hours = int(delta.total_seconds() // 3600)
                return f"Last seen {hours} hour{'s' if hours != 1 else ''} ago"
        except Exception:
            return "Unknown"

    return jsonify([
        {
            "id": u["id"],
            "email": u["email"],
            "status_caption": u["status_caption"] or "",
            "last_seen": format_time(u["last_seen"]),
        }
        for u in users_res.data
    ])


@social_bp.route("/pending_friend_requests", methods=["GET"])
def get_pending_friend_requests():
    user_id = get_user_id_from_token(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401

    supa = get_supa()
    reqs = supa.table("friend_requests").select("id, sender_id").eq("receiver_id", user_id).eq("status", "pending").execute()
    if not reqs.data:
        return jsonify([]), 200

    sender_ids = [r["sender_id"] for r in reqs.data]
    users_res = supa.table("users").select("id, email").in_("id", sender_ids).execute()
    email_map = {u["id"]: u["email"] for u in users_res.data}

    return jsonify([
        {"id": r["id"], "from_email": email_map.get(r["sender_id"], "")}
        for r in reqs.data
    ])


@social_bp.route("/respond_to_friend_request", methods=["POST"])
def respond_to_friend_request():
    user_id = get_user_id_from_token(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401

    data = request.get_json()
    request_id = data.get("request_id")
    action = data.get("action")

    if action not in ["accept", "decline"]:
        return jsonify({"message": "Invalid action"}), 400

    supa = get_supa()
    req_res = supa.table("friend_requests").select("sender_id, receiver_id").eq("id", request_id).execute()
    req = req_res.data[0] if req_res.data else None

    if not req or req["receiver_id"] != user_id:
        return jsonify({"message": "Request not found or unauthorized"}), 404

    from_user_id = req["sender_id"]

    if action == "accept":
        supa.table("friend_requests").update({"status": "accepted"}).eq("id", request_id).execute()
        supa.table("friends").insert([
            {"user_id": user_id, "friend_id": from_user_id},
            {"user_id": from_user_id, "friend_id": user_id},
        ]).execute()
    else:
        supa.table("friend_requests").update({"status": "rejected"}).eq("id", request_id).execute()

    return jsonify({"message": f"Request {action}ed!"})


@social_bp.route("/remove_friend", methods=["DELETE"])
def remove_friend():
    user_id = get_user_id_from_token(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401

    friend_id = request.args.get("friend_id", type=int)
    if not friend_id:
        return jsonify({"message": "friend_id required"}), 400

    supa = get_supa()
    supa.table("friends").delete().eq("user_id", user_id).eq("friend_id", friend_id).execute()
    supa.table("friends").delete().eq("user_id", friend_id).eq("friend_id", user_id).execute()
    return jsonify({"message": "Friend removed"}), 200


@social_bp.route("/friends/<int:friend_id>/closet", methods=["GET"])
def friend_closet(friend_id):
    user_id = get_user_id_from_token(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401

    supa = get_supa()
    check = supa.table("friends").select("friend_id").eq("user_id", user_id).eq("friend_id", friend_id).execute()
    if not check.data:
        return jsonify({"message": "Not friends"}), 403

    result = supa.table("closet_items").select(
        "id, filename, brand, category, type, color, icon_path"
    ).eq("user_id", friend_id).order("id").execute()

    items = []
    for r in result.data:
        items.append({
            "id":        r["id"],
            "filename":  r["filename"],
            "brand":     r["brand"] or "",
            "category":  r["category"] or "Uncategorized",
            "type":      r["type"] or "",
            "color":     r["color"] or "",
            "icon_path": r["icon_path"] or "",
            "url":       f"/static/{friend_id}/{r['filename']}",
        })

    return jsonify(items), 200


@social_bp.route("/update_status", methods=["POST"])
def update_status():
    user_id = get_user_id_from_token(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401

    data = request.get_json()
    caption = (data.get("status_caption") or "").strip()[:160]

    get_supa().table("users").update({
        "status_caption": caption,
        "last_seen": datetime.datetime.utcnow().isoformat(),
    }).eq("id", user_id).execute()
    return jsonify({"message": "Status updated"}), 200
