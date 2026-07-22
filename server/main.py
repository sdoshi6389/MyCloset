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
from recommend import recommend_bp
import mimetypes
import os
import threading

from paths import ICON_OUTPUTS_DIR, EMOJI_OUTPUTS_DIR, MANNEQUIN_OUTPUTS_DIR

app = Flask(__name__)
CORS(app)


@app.route("/health", methods=["GET"])
def health():
    # Cheap liveness probe for Railway health checks — no DB, no model loads.
    return {"status": "ok"}, 200

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
    icon_dir = ICON_OUTPUTS_DIR
    if not os.path.isfile(os.path.join(icon_dir, filename)):
        # Not on local disk (deployed instance) → redirect to Supabase Storage CDN.
        from flask import redirect
        from storage_utils import public_url
        return redirect(public_url(f"icons/{filename}"))
    mimetype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return send_from_directory(icon_dir, filename, mimetype=mimetype)


@app.route("/emojis/<path:filename>")
def serve_emoji(filename):
    emoji_dir = EMOJI_OUTPUTS_DIR
    mimetype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return send_from_directory(emoji_dir, filename, mimetype=mimetype)


@app.route("/dressed/<path:filename>")
def serve_dressed_mannequin(filename):
    out_dir = MANNEQUIN_OUTPUTS_DIR
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
app.register_blueprint(recommend_bp)   # /recommend

def _start_faiss_worker():
    # Lazy load: do NOT build/load the ~1GB+ FAISS index here. The watcher
    # thread itself is cheap (just sleeps on an Event); the actual index
    # only loads on the first call to search_similar_products(), which
    # already guards itself with _ensure_index().
    #
    # Disabled by default in production: its 15-min wake cycle makes outbound
    # Supabase calls that would keep Railway from sleeping. Rebuild manually via
    # POST /admin/faiss/rebuild instead. Set ENABLE_FAISS_WORKER=true to run it
    # (e.g. on a scraper box).
    if os.environ.get("ENABLE_FAISS_WORKER", "").strip().lower() not in ("1", "true", "yes"):
        print("⏸️  FAISS background worker disabled (ENABLE_FAISS_WORKER not set)")
        return
    try:
        from callable_faiss import start_background_worker
        start_background_worker()
    except Exception as e:
        print(f"⚠️  FAISS background worker failed to start: {e}")

_start_faiss_worker()


# ── Admin endpoints ───────────────────────────────────────────────────────────
from flask import jsonify as _jsonify, request as _request
import hmac

_ADMIN_SECRET = os.environ.get("ADMIN_DEPLOY_SECRET", "")


def _admin_authorized() -> bool:
    """Fail-closed bearer check for /admin/* routes (deny if secret unset)."""
    if not _ADMIN_SECRET:
        return False
    auth = _request.headers.get("Authorization", "")
    return auth.startswith("Bearer ") and hmac.compare_digest(auth[7:], _ADMIN_SECRET)

@app.route("/admin/faiss/status", methods=["GET"])
def faiss_status():
    if not _admin_authorized():
        return _jsonify({"error": "unauthorized"}), 401
    from callable_faiss import get_status
    return _jsonify(get_status()), 200

@app.route("/admin/faiss/rebuild", methods=["POST"])
def faiss_rebuild():
    if not _admin_authorized():
        return _jsonify({"error": "unauthorized"}), 401
    from callable_faiss import notify_rebuild_needed, force_rebuild
    if (_request.get_json(silent=True) or {}).get("force"):
        threading.Thread(target=force_rebuild, daemon=True, name="faiss-force").start()
        return _jsonify({"message": "Force rebuild started"}), 202
    notify_rebuild_needed()
    return _jsonify({"message": "Rebuild queued (cooldown applies)"}), 202


if __name__ == "__main__":
    # use_reloader=False: the reloader runs two full processes and reloads
    # the entire ML stack (torch/easyocr/CLIP/FAISS) on every file save —
    # disabled to cut both baseline and restart-churn RAM. Debug error pages
    # still work; you just need to restart manually after backend edits.
    app.run(port=5000, debug=True, use_reloader=False)
