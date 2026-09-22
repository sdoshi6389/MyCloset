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


# Grid tiles, the builder rail and recommendation cards all display icons at
# 60–180 CSS px, so a 320 px thumb covers 2x DPR while being ~10x smaller than
# the 1024 px full icon. Canvas zones and the detail modal keep the full icon.
THUMB_PX = 320


def thumb_key(icon_name: str) -> str:
    return f"icons/thumb/{icon_name}"


def thumb_url(icon_name: str) -> str:
    return public_url(thumb_key(icon_name))


def _open_image(src):
    """src: local path or raw bytes → PIL image in RGB/RGBA."""
    from PIL import Image
    img = Image.open(io.BytesIO(src) if isinstance(src, (bytes, bytearray)) else src)
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA")  # preserve transparency for icons
    return img


def _encode_webp(img, quality: int) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=quality, method=6)
    return buf.getvalue()


def _to_webp(local_path: str, quality: int = 90) -> bytes:
    """Re-encode an image to WebP at full resolution (visually lossless at q90)."""
    return _encode_webp(_open_image(local_path), quality)


def _to_thumb_webp(src, px: int = THUMB_PX, quality: int = 85) -> bytes:
    from PIL import Image
    img = _open_image(src)
    img.thumbnail((px, px), Image.LANCZOS)
    return _encode_webp(img, quality)


def _put(dest_path: str, data: bytes, content_type: str):
    get_supa().storage.from_(BUCKET).upload(
        dest_path, data,
        {"content-type": content_type, "cache-control": _CACHE_SECONDS, "upsert": "true"},
    )


def upload_thumb(src, icon_name: str) -> str | None:
    """Generate + upload the THUMB_PX WebP for an icon. src: local path or bytes."""
    ensure_bucket()
    try:
        _put(thumb_key(icon_name), _to_thumb_webp(src), "image/webp")
        return thumb_url(icon_name)
    except Exception as e:
        print(f"⚠️  Storage thumb upload failed for {icon_name}: {e}")
        return None


def upload_icon(local_path: str, icon_name: str, quality: int = 90) -> tuple[str | None, str | None]:
    """Upload a generated icon as full-res WebP plus its thumb. Returns (icon_url, thumb_url)."""
    full = upload_file(local_path, f"icons/{icon_name}", webp=True, quality=quality)
    thumb = upload_thumb(local_path, icon_name)
    return full, thumb


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
