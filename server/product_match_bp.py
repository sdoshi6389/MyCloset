import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

import tempfile
import threading
import urllib.request
import json

from flask import Blueprint, request, jsonify
import numpy as np

from callable_embedding import generate_clip_embedding
from callable_faiss import search_similar_products

product_match_bp = Blueprint("product_match", __name__)

NEXT_APP_URL = os.environ.get("NEXT_APP_URL", "http://localhost:3000")
WORKER_WEBHOOK_SECRET = os.environ.get("WORKER_WEBHOOK_SECRET", "")


def _post_callback(job_id: str, payload: dict):
    url = f"{NEXT_APP_URL}/api/ai/jobs/{job_id}"
    data = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if WORKER_WEBHOOK_SECRET:
        headers["x-worker-secret"] = WORKER_WEBHOOK_SECRET
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10):
            pass
    except Exception as e:
        print(f"Callback POST failed for job {job_id}: {e}")


def _run_job(job_id: str, image_url: str, brand: str | None):
    tmp_path = None
    try:
        # Download image from Supabase storage to a temp file
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp_path = tmp.name

        req = urllib.request.Request(image_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            with open(tmp_path, "wb") as f:
                f.write(resp.read())

        print(f"Generating CLIP embedding for job {job_id}...")
        embedding = generate_clip_embedding(tmp_path)

        print(f"Running FAISS search (brand={brand})...")
        raw = search_similar_products(np.array(embedding, dtype=np.float32), brand)

        matches = []
        for rank, m in enumerate(raw, 1):
            matches.append({
                "brand_table":       m.get("source", ""),
                "product_title":     m.get("title", ""),
                "product_url":       m.get("url") or None,
                "product_image_url": m.get("image") or None,
                "price":             m.get("price") or None,
                "color":             m.get("color") or None,
                "score":             round(1.0 / (1.0 + float(m.get("distance", 0))), 6),
                "rank":              rank,
            })

        print(f"Job {job_id} done: {len(matches)} matches")
        _post_callback(job_id, {"status": "completed", "result": {"matches": matches}})

    except Exception as e:
        print(f"Job {job_id} failed: {e}")
        _post_callback(job_id, {"status": "failed", "error": str(e)})

    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


@product_match_bp.route("/product-match", methods=["POST"])
def product_match():
    data = request.get_json(force=True) or {}
    job_id = data.get("job_id")
    image_url = data.get("image_url")
    brand = data.get("brand") or None

    if not job_id or not image_url:
        return jsonify({"error": "job_id and image_url are required"}), 400

    t = threading.Thread(target=_run_job, args=(job_id, image_url, brand), daemon=True)
    t.start()

    return jsonify({"status": "accepted", "job_id": job_id}), 202
