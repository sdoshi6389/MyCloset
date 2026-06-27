import os
from flask import Blueprint, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
from services.auth_service import get_user_id_from_request
from services.feed_service import (
    create_post, attach_image_to_post, get_feed,
    toggle_like, delete_post, POST_IMAGES_DIR,
)

feed_bp = Blueprint("feed", __name__, url_prefix="/feed")

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp"}


def _allowed(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@feed_bp.route("", methods=["GET"])
def list_feed():
    user_id = get_user_id_from_request(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401
    limit = int(request.args.get("limit", 30))
    offset = int(request.args.get("offset", 0))
    posts = get_feed(user_id, limit=limit, offset=offset)
    return jsonify(posts), 200


@feed_bp.route("", methods=["POST"])
def create():
    user_id = get_user_id_from_request(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401

    caption = request.form.get("caption", "").strip()
    visibility = request.form.get("visibility", "friends")
    outfit_id = request.form.get("outfit_id") or None
    circle_id = request.form.get("circle_id") or None

    if outfit_id:
        outfit_id = int(outfit_id)
    if circle_id:
        circle_id = int(circle_id)

    post_id = create_post(user_id, caption, visibility, outfit_id, circle_id)

    files = request.files.getlist("images")
    for f in files:
        if f and _allowed(f.filename):
            fname = secure_filename(f.filename)
            dest = os.path.join(POST_IMAGES_DIR, f"{post_id}_{fname}")
            f.save(dest)
            attach_image_to_post(post_id, dest)

    return jsonify({"id": post_id, "message": "Post created"}), 201


@feed_bp.route("/<int:post_id>", methods=["DELETE"])
def remove(post_id):
    user_id = get_user_id_from_request(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401
    ok = delete_post(post_id, user_id)
    if not ok:
        return jsonify({"message": "Not found"}), 404
    return jsonify({"message": "Deleted"}), 200


@feed_bp.route("/<int:post_id>/like", methods=["POST"])
def like(post_id):
    user_id = get_user_id_from_request(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401
    liked = toggle_like(post_id, user_id)
    return jsonify({"liked": liked}), 200


@feed_bp.route("/images/<path:filename>")
def serve_post_image(filename):
    return send_from_directory(POST_IMAGES_DIR, filename)
