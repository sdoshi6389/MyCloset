from flask import Blueprint, request, jsonify
from services.auth_service import get_user_id_from_request
from services.outfit_service import (
    create_outfit, save_outfit_items, get_outfits, get_circle_outfits,
    delete_outfit, rate_outfit, add_feedback,
)
from services.recommendation_service import recommend_outfits

outfits_bp = Blueprint("outfits", __name__, url_prefix="/outfits")


@outfits_bp.route("", methods=["GET"])
def list_outfits():
    user_id = get_user_id_from_request(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401

    circle_id = request.args.get("circle_id", type=int)
    if circle_id:
        return jsonify(get_circle_outfits(user_id, circle_id)), 200

    return jsonify(get_outfits(user_id)), 200


@outfits_bp.route("", methods=["POST"])
def create():
    user_id = get_user_id_from_request(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401

    data       = request.get_json()
    name       = data.get("name", "My Outfit")
    occasion   = data.get("occasion")
    tags       = data.get("tags")
    notes      = data.get("notes")
    is_private = bool(data.get("is_private", False))
    slots      = data.get("slots", {})

    outfit_id = create_outfit(user_id, name, occasion, tags, notes, is_private)
    pairs = [(slot, item_id) for slot, item_id in slots.items() if item_id is not None]
    if pairs:
        save_outfit_items(outfit_id, pairs)

    return jsonify({"id": outfit_id, "message": "Outfit saved"}), 201


@outfits_bp.route("/<int:outfit_id>", methods=["DELETE"])
def remove(outfit_id):
    user_id = get_user_id_from_request(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401
    ok = delete_outfit(outfit_id, user_id)
    if not ok:
        return jsonify({"message": "Not found"}), 404
    return jsonify({"message": "Deleted"}), 200


@outfits_bp.route("/<int:outfit_id>/rate", methods=["POST"])
def rate(outfit_id):
    user_id = get_user_id_from_request(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401
    data   = request.get_json()
    rating = data.get("rating")
    if not rating or not (1 <= int(rating) <= 5):
        return jsonify({"message": "Rating must be 1-5"}), 400
    rate_outfit(outfit_id, user_id, int(rating))
    return jsonify({"message": "Rated"}), 200


@outfits_bp.route("/<int:outfit_id>/feedback", methods=["POST"])
def feedback(outfit_id):
    user_id = get_user_id_from_request(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401
    data = request.get_json()
    text = data.get("feedback", "").strip()
    if not text:
        return jsonify({"message": "Empty feedback"}), 400
    add_feedback(outfit_id, user_id, text)
    return jsonify({"message": "Feedback saved"}), 201


@outfits_bp.route("/recommend", methods=["GET"])
def recommend():
    user_id = get_user_id_from_request(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401
    occasion     = request.args.get("occasion")
    style_prompt = request.args.get("style")
    circle_id    = request.args.get("circle_id")
    results = recommend_outfits(user_id, occasion=occasion, style_prompt=style_prompt, circle_id=circle_id)
    return jsonify(results), 200
