from flask import Flask, send_from_directory, abort
from flask_cors import CORS
from auth import auth_bp
from closet import closet_bp
from friends import social_bp
from builder import builder_bp
from generate_dressed_mannequin_bp import bp as dressed_bp
from product_match_bp import product_match_bp
from outfit_2d import outfit2d_bp
from outfits import outfits_bp
from circles import circles_bp
from feed import feed_bp
import mimetypes
import os
import threading

app = Flask(__name__)
CORS(app)

# ── Resolved image directories ───────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONVERTED_IMAGES_DIR = os.environ.get("CONVERTED_IMAGES_DIR") or os.path.abspath(
    os.path.join(BASE_DIR, "..", "converted_images")
)
if not os.path.isdir(CONVERTED_IMAGES_DIR):
    alt = os.path.join(BASE_DIR, "converted_images")
    if os.path.isdir(alt):
        CONVERTED_IMAGES_DIR = alt

print("🗂️  Using converted images dir:", CONVERTED_IMAGES_DIR)
app.config["UPLOAD_FOLDER"] = CONVERTED_IMAGES_DIR

# ── Static file routes ────────────────────────────────────────────────────────
@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    full_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    if not os.path.exists(full_path):
        return abort(404)
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


@app.route("/icons/<path:filename>")
def serve_icon(filename):
    icon_dir = os.path.join(os.getcwd(), "icon_outputs")
    mimetype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return send_from_directory(icon_dir, filename, mimetype=mimetype)


@app.route("/emojis/<path:filename>")
def serve_emoji(filename):
    emoji_dir = os.path.join(os.getcwd(), "emoji_outputs")
    mimetype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return send_from_directory(emoji_dir, filename, mimetype=mimetype)


@app.route("/dressed/<path:filename>")
def serve_dressed_mannequin(filename):
    out_dir = os.path.join(os.getcwd(), "mannequin_outputs")
    if not os.path.exists(os.path.join(out_dir, filename)):
        return abort(404)
    return send_from_directory(out_dir, filename)


@app.route("/processed/<path:filename>")
def processed_files(filename):
    return send_from_directory("processed", filename)


# ── Register blueprints ───────────────────────────────────────────────────────
app.register_blueprint(auth_bp)
app.register_blueprint(closet_bp)
app.register_blueprint(social_bp)
app.register_blueprint(builder_bp, url_prefix="/builder")
app.register_blueprint(dressed_bp, url_prefix="/vton")
app.register_blueprint(outfit2d_bp)
app.register_blueprint(product_match_bp)
app.register_blueprint(outfits_bp)     # /outfits
app.register_blueprint(circles_bp)     # /circles
app.register_blueprint(feed_bp)        # /feed

def _warmup_faiss():
    try:
        from callable_faiss import _ensure_index, start_background_worker
        print("🔄 FAISS warmup starting in background…")
        start_background_worker()
        _ensure_index()
    except Exception as e:
        print(f"⚠️  FAISS warmup failed: {e}")

threading.Thread(target=_warmup_faiss, daemon=True, name="faiss-warmup").start()


# ── Admin endpoints ───────────────────────────────────────────────────────────
from flask import jsonify as _jsonify, request as _request

@app.route("/admin/faiss/status", methods=["GET"])
def faiss_status():
    from callable_faiss import get_status
    return _jsonify(get_status()), 200

@app.route("/admin/faiss/rebuild", methods=["POST"])
def faiss_rebuild():
    from callable_faiss import notify_rebuild_needed, force_rebuild
    if (_request.get_json(silent=True) or {}).get("force"):
        threading.Thread(target=force_rebuild, daemon=True, name="faiss-force").start()
        return _jsonify({"message": "Force rebuild started"}), 202
    notify_rebuild_needed()
    return _jsonify({"message": "Rebuild queued (cooldown applies)"}), 202


if __name__ == "__main__":
    app.run(port=5000, debug=True)
