"""Supabase Storage helpers for closet images (uploaded photos + generated icons).

Files go into a PUBLIC bucket so the /static and /icons routes can redirect the
browser to the Supabase CDN. Everything is best-effort: if Storage is
unavailable, callers still fall back to local disk, so local dev is unaffected.

Uploads carry a long-lived Cache-Control header (browsers + CDN cache them, so
repeat loads are instant), and icons are re-encoded to WebP — visually lossless
at the SAME resolution — to shrink the ~1.7 MB gpt-image PNGs ~5x.
"""
import os
import io
import mimetypes

from db import get_supa
from config import SUPABASE_URL

BUCKET = os.environ.get("CLOSET_IMAGE_BUCKET", "closet-images")
_SUPABASE_URL = (SUPABASE_URL or "").rstrip("/")
_CACHE_SECONDS = "86400"  # 1 day — fast repeat loads, self-heals if an icon is regenerated
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
        pass


def public_url(dest_path: str) -> str:
    return f"{_SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{dest_path.lstrip('/')}"


def _to_webp(local_path: str, quality: int = 90) -> bytes:
    """Re-encode an image to WebP at full resolution (visually lossless at q90)."""
    from PIL import Image
    img = Image.open(local_path)
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA")  # preserve transparency for icons
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=quality, method=6)
    return buf.getvalue()


def upload_file(local_path: str, dest_path: str, content_type: str | None = None,
                webp: bool = False, quality: int = 90):
    """Upload a local file to BUCKET at dest_path (upsert) with a long cache header.

    webp=True re-encodes to WebP (visually lossless, keeps resolution) — used for
    the big transparent-PNG icons. Returns the public URL, or None on failure.
    """
    ensure_bucket()
    try:
        if webp:
            data = _to_webp(local_path, quality)
            ct = "image/webp"
        else:
            with open(local_path, "rb") as f:
                data = f.read()
            ct = content_type or mimetypes.guess_type(local_path)[0] or "application/octet-stream"
        get_supa().storage.from_(BUCKET).upload(
            dest_path, data,
            {"content-type": ct, "cache-control": _CACHE_SECONDS, "upsert": "true"},
        )
        return public_url(dest_path)
    except Exception as e:
        print(f"⚠️  Storage upload failed for {dest_path}: {e}")
        return None
