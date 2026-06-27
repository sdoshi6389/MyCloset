from flask import Blueprint, request, jsonify
import jwt
import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from db import get_supa
from config import JWT_SECRET

auth_bp = Blueprint("auth", __name__)
SECRET_KEY = JWT_SECRET


@auth_bp.route("/signup", methods=["POST"])
def signup():
    data = request.get_json()
    email = data.get("email")
    raw_password = data.get("password")

    if not email or not raw_password:
        return jsonify({"message": "Missing email or password"}), 400

    password = generate_password_hash(raw_password)
    supa = get_supa()

    try:
        supa.table("users").insert({"email": email, "password": password}).execute()
        return jsonify({"message": "User created!"}), 201
    except Exception as e:
        err = str(e)
        if "23505" in err or "unique" in err.lower():
            return jsonify({"message": "User already exists"}), 400
        print(f"Signup error: {e}")
        return jsonify({"message": "Internal server error"}), 500


@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    email = data.get("email")
    raw_password = data.get("password")

    if not email or not raw_password:
        return jsonify({"message": "Missing email or password"}), 400

    supa = get_supa()
    result = supa.table("users").select("id, password").eq("email", email).execute()
    user = result.data[0] if result.data else None

    if user and check_password_hash(user["password"], raw_password):
        token = jwt.encode({
            "user_id": user["id"],
            "exp": datetime.datetime.utcnow() + datetime.timedelta(days=1)
        }, SECRET_KEY, algorithm="HS256")
        return jsonify({"token": token, "email": email})

    return jsonify({"message": "Invalid credentials"}), 401


@auth_bp.route("/me", methods=["GET"])
def me():
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return jsonify({"message": "Unauthorized"}), 401
    try:
        token = auth_header.split(" ")[1]
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        user_id = payload["user_id"]
    except Exception:
        return jsonify({"message": "Invalid token"}), 401

    supa = get_supa()
    result = supa.table("users").select("id, email, status_caption").eq("id", user_id).execute()
    user = result.data[0] if result.data else None
    if not user:
        return jsonify({"message": "User not found"}), 404
    return jsonify({"id": user["id"], "email": user["email"], "status_caption": user["status_caption"]}), 200
