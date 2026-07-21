"""
Generate CLIP embeddings for every Alo product image and store them in
product_image_embeddings.  Background is removed from each product image
before CLIP so embeddings capture garment shape/color rather than the model
or studio backdrop.  Run this after re-scraping alo products.

Usage:
    python server/generate_alo_embeddings.py

After this finishes, rebuild the FAISS index so it picks up the new vectors:
    python server/callable_faiss.py --rebuild
  or hit the admin endpoint:
    POST /admin/force-rebuild
"""
import os, sys, tempfile, time, io
import requests as _requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import get_supa
from callable_embedding import generate_clip_embedding

ALO_TABLES = ["products_alo_womens", "products_alo_mens"]
PAGE = 200


def p(*args):
    try:
        print(*args, flush=True)
    except UnicodeEncodeError:
        print(*(str(a).encode("ascii", "replace").decode() for a in args), flush=True)


def _get_existing_urls(supa, source_table: str) -> set:
    """Return the set of image_urls already in product_image_embeddings for this table."""
    existing = set()
    offset = 0
    while True:
        res = (supa.table("product_image_embeddings")
               .select("image_url")
               .eq("source_table", source_table)
               .range(offset, offset + 999)
               .execute())
        for r in (res.data or []):
            existing.add(r["image_url"])
        if len(res.data or []) < 1000:
            break
        offset += 1000
    return existing


def _download_bytes(url: str) -> bytes | None:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        )
    }
    try:
        r = _requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        return r.content
    except Exception as e:
        p(f"    download failed ({url[:60]}...): {e}")
        return None


def _remove_bg(raw: bytes) -> bytes:
    """
    Strip background via rembg.  Returns bg-removed PNG bytes, or the
    original bytes if removal fails or produces an empty result.
    """
    try:
        from bg_remove import _remove_background
        from PIL import Image
        result = _remove_background(raw)
        # Sanity-check: if the result is mostly transparent, fall back.
        img = Image.open(io.BytesIO(result)).convert("RGBA")
        alpha_sum = sum(p[3] for p in img.getdata())
        if alpha_sum > 0:
            return result
        p("    bg removal returned blank — using original")
    except Exception as e:
        p(f"    bg removal failed ({e}) — using original")
    return raw


def _write_tmp(data: bytes, suffix: str = ".png") -> str:
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(data)
    tmp.close()
    return tmp.name


def process_table(supa, table: str):
    p(f"\n=== {table} ===")

    p("  fetching already-embedded URLs...")
    existing = _get_existing_urls(supa, table)
    p(f"  {len(existing)} already done")

    offset = 0
    n_processed = n_skipped = n_errors = 0
    start = time.time()

    while True:
        res = (supa.table(table)
               .select("id, images")
               .range(offset, offset + PAGE - 1)
               .execute())
        rows = res.data or []
        if not rows:
            break

        for row in rows:
            product_id = row["id"]
            images     = row.get("images") or []

            for img_url in images:
                if not img_url:
                    continue
                if img_url in existing:
                    n_skipped += 1
                    continue

                raw = _download_bytes(img_url)
                if not raw:
                    n_errors += 1
                    continue

                tmp_path = None
                try:
                    # Remove background so CLIP focuses on garment shape/color,
                    # not the model or studio backdrop.
                    processed = _remove_bg(raw)
                    tmp_path = _write_tmp(processed, ".png")
                    emb = generate_clip_embedding(tmp_path)
                    supa.table("product_image_embeddings").upsert(
                        {
                            "source_table": table,
                            "product_id":   product_id,
                            "image_url":    img_url,
                            "embedding":    emb,
                        },
                        on_conflict="source_table,image_url",
                    ).execute()
                    existing.add(img_url)
                    n_processed += 1
                except Exception as e:
                    p(f"    embed/save error: {e}")
                    n_errors += 1
                finally:
                    if tmp_path:
                        try:
                            os.unlink(tmp_path)
                        except Exception:
                            pass

        elapsed = time.time() - start
        p(f"  offset {offset}: +{n_processed} embedded, {n_skipped} skipped, {n_errors} errors  ({elapsed:.0f}s)")

        if len(rows) < PAGE:
            break
        offset += PAGE

    p(f"  DONE: {n_processed} new embeddings, {n_skipped} skipped, {n_errors} errors")


def main():
    p("Alo multi-image CLIP embedding generator")
    p("Loading CLIP model (this takes a moment)...")
    # CLIP model is loaded at callable_embedding import time — done by now.

    supa = get_supa()
    for table in ALO_TABLES:
        process_table(supa, table)

    p("\nAll tables done.")
    p("Next step: rebuild FAISS index so new embeddings are searchable.")
    p("  python server/callable_faiss.py --rebuild")
    p("  or POST /admin/force-rebuild")


if __name__ == "__main__":
    main()
