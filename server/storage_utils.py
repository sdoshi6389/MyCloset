"""Supabase Storage helpers for closet images (uploaded photos + generated icons).

Files go into a PUBLIC bucket so the /static and /icons routes can 302-redirect
the browser straight to the Supabase CDN. Everything is best-effort: if Storage
is unavailable, callers still fall back to local disk, so local dev is unaffected.
"""
import os
import mimetypes

from db import get_supa
from config import SUPABASE_URL

BUCKET = os.environ.get("CLOSET_IMAGE_BUCKET", "closet-images")
_SUPABASE_URL = (SUPABASE_URL or "").rstrip("/")
_bucket_checked = False


def ensure_bucket() -> None:
    """Create the public bucket once per process if it doesn't already exist."""
    global _bucket_checked
    if _bucket_checked:
        return
    _bucket_checked = True
    try:
        get_supa().storage.create_bucket(BUCKET, options={"public": True})
        print(f"🪣 Created Storage bucket '{BUCKET}'")
    except Exception:
        # Already exists (or a transient error) — assume it's usable.
        pass


def public_url(dest_path: str) -> str:
    return f"{_SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{dest_path.lstrip('/')}"


def upload_file(local_path: str, dest_path: str, content_type: str | None = None):
    """Upload a local file to BUCKET at dest_path (upsert). Returns public URL or None."""
    ensure_bucket()
    try:
        with open(local_path, "rb") as f:
            data = f.read()
        ct = content_type or mimetypes.guess_type(local_path)[0] or "application/octet-stream"
        get_supa().storage.from_(BUCKET).upload(
            dest_path, data, {"content-type": ct, "upsert": "true"},
        )
        return public_url(dest_path)
    except Exception as e:
        print(f"⚠️  Storage upload failed for {dest_path}: {e}")
        return None
