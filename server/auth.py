from flask import Blueprint, request, jsonify
import jwt
import datetime
import warnings
from werkzeug.security import generate_password_hash, check_password_hash
from db import get_supa
from config import JWT_SECRET
import warmup

auth_bp = Blueprint("auth", __name__)
SECRET_KEY = JWT_SECRET

if len(SECRET_KEY.encode()) < 32:
    warnings.warn(
        f"JWT_SECRET is only {len(SECRET_KEY.encode())} bytes — recommended minimum is 32 bytes. "
        "Set a longer random value in your environment.",
        stacklevel=1,
    )


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
        warmup.kick()  # start loading FAISS/CLIP now so the builder is instant
        return jsonify({"token": token, "email": email, "user_id": user["id"]})

    return jsonify({"message": "Invalid credentials"}), 401


@auth_bp.route("/refresh", methods=["POST"])
def refresh():
    """
    Issue a new access token using a still-valid or recently-expired token.
    Accepts the old Bearer token; allows up to 7 days past expiry as grace window.
    The user record is re-verified so deleted/suspended accounts can't refresh.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return jsonify({"message": "Unauthorized"}), 401

    old_token = auth_header.split(" ")[1]
    try:
        # Decode without verifying expiry so we can inspect recently-expired tokens
        payload = jwt.decode(
            old_token, SECRET_KEY, algorithms=["HS256"],
            options={"verify_exp": False},
        )
    except Exception:
        return jsonify({"message": "Invalid token"}), 401

    user_id = payload.get("user_id")
    old_exp  = payload.get("exp", 0)
    now_ts   = datetime.datetime.utcnow().timestamp()

    # Refuse tokens that expired more than 7 days ago
    GRACE_SECONDS = 7 * 24 * 3600
    if now_ts - old_exp > GRACE_SECONDS:
        return jsonify({"message": "Token too old — please log in again"}), 401

    # Verify the user still exists
    supa = get_supa()
    result = supa.table("users").select("id, email").eq("id", user_id).execute()
    user = result.data[0] if result.data else None
    if not user:
        return jsonify({"message": "User not found"}), 401

    new_token = jwt.encode({
        "user_id": user["id"],
        "exp": datetime.datetime.utcnow() + datetime.timedelta(days=1),
    }, SECRET_KEY, algorithm="HS256")

    warmup.kick()
    return jsonify({"token": new_token, "email": user["email"], "user_id": user["id"]})


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
