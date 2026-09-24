"""Recommendations-for-you surface — /suggestions

Two reads:
  /suggestions/outfits  — complete looks assembled from the user's own closet
  /suggestions/discover — their looks plus one or two catalog pieces

Both take optional lat/lon. Weather steers ranking when it is supplied and is
simply absent when it is not, so the page works before anyone grants location.
"""
import jwt
from flask import Blueprint, request, jsonify

from config import JWT_SECRET
from weather import get_weather

suggestions_bp = Blueprint("suggestions", __name__)


def _get_user_id(req) -> int | None:
    auth = req.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    try:
        return jwt.decode(auth.split(" ")[1], JWT_SECRET, algorithms=["HS256"])["user_id"]
    except Exception:
        return None


def _weather_from(req) -> dict | None:
    lat, lon = req.args.get("lat"), req.args.get("lon")
    if lat is None or lon is None:
        return None
    try:
        return get_weather(float(lat), float(lon))
    except (TypeError, ValueError):
        return None


@suggestions_bp.route("/weather", methods=["GET"])
def weather_now():
    w = _weather_from(request)
    return jsonify({"weather": w}), 200


@suggestions_bp.route("/outfits", methods=["GET"])
def outfit_suggestions():
    user_id = _get_user_id(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401
    try:
        count = min(int(request.args.get("count", 6)), 12)
    except ValueError:
        count = 6
    w = _weather_from(request)
    try:
        from recommendation.outfit_suggest import suggest_outfits
        looks = suggest_outfits(user_id, weather=w, count=count)
        return jsonify({"weather": w, "outfits": looks}), 200
    except Exception as e:
        print(f"❌ /suggestions/outfits: {type(e).__name__}: {e}")
        return jsonify({"weather": w, "outfits": [], "error": "unavailable"}), 200


@suggestions_bp.route("/discover", methods=["GET"])
def discover():
    user_id = _get_user_id(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401
    try:
        count = min(int(request.args.get("count", 5)), 10)
    except ValueError:
        count = 5
    try:
        max_new = max(1, min(int(request.args.get("max_new", 2)), 2))
    except ValueError:
        max_new = 2
    gender = request.args.get("gender") or None
    w = _weather_from(request)
    try:
        from recommendation.outfit_suggest import discover_additions
        found = discover_additions(user_id, weather=w, count=count,
                                   max_new=max_new, gender=gender)
        return jsonify({"weather": w, "discover": found}), 200
    except Exception as e:
        print(f"❌ /suggestions/discover: {type(e).__name__}: {e}")
        return jsonify({"weather": w, "discover": [], "error": "unavailable"}), 200
