"""Copy the prebuilt FAISS vectors into product_vectors so Postgres can search them.

The catalog's 207k embeddings live in faiss_cache/all_products_embeddings.npy with
their metadata in all_products_meta.pkl. This streams them into the table created
by migrations/008_pgvector_search.sql.

Resumable: rows are upserted on (source, product_id, image), so re-running skips
nothing but overwrites identically. Pass --resume to skip batches already counted.

Usage (from server/):
    python backfill_pgvector.py                # full run
    python backfill_pgvector.py --limit 2000   # smoke test
    python backfill_pgvector.py --resume
"""
import argparse
import pickle
import sys
import time

import numpy as np

from callable_faiss import EMBED_FILE, META_FILE, _item_gender
from db import get_supa

BATCH = 500          # ~500 * 512 floats of JSON per request


def _rows(meta, vecs, start, end):
    out = []
    for i in range(start, end):
        m = meta[i]
        image = m.get("image") or ""
        pid = m.get("id")
        if pid is None or not image:
            continue                      # cannot key it; skip
        out.append({
            "source":          m.get("source") or "",
            "product_id":      str(pid),
            "title":           m.get("title"),
            "color":           m.get("color"),
            "price":           m.get("price"),
            "image":           image,
            "url":             m.get("url"),
            # Precomputed so SQL filters exactly as the Python heuristic did.
            "resolved_gender": _item_gender(m),
            "embedding":       np.asarray(vecs[i], dtype=np.float32).tolist(),
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="only this many vectors")
    ap.add_argument("--resume", action="store_true",
                    help="skip the first N already in the table")
    args = ap.parse_args()

    supa = get_supa()
    # mmap keeps the 404 MB file on disk instead of in RAM
    vecs = np.load(EMBED_FILE, mmap_mode="r")
    with open(META_FILE, "rb") as f:
        meta = pickle.load(f)
    assert len(meta) == vecs.shape[0], f"meta {len(meta)} != vecs {vecs.shape[0]}"

    total = args.limit or len(meta)
    start = 0
    if args.resume:
        try:
            have = supa.table("product_vectors").select("id", count="exact").limit(1).execute().count or 0
            start = min(have, total)
            print(f"resuming: {have} rows already present")
        except Exception as e:
            print(f"could not count existing rows ({e}); starting from 0")

    print(f"backfilling {total - start} of {len(meta)} vectors, batches of {BATCH}")
    sent = failed = skipped = 0
    t0 = time.time()
    for lo in range(start, total, BATCH):
        hi = min(lo + BATCH, total)
        rows = _rows(meta, vecs, lo, hi)
        skipped += (hi - lo) - len(rows)
        if not rows:
            continue
        for attempt in range(3):
            try:
                supa.table("product_vectors").upsert(
                    rows, on_conflict="source,product_id,image").execute()
                sent += len(rows)
                break
            except Exception as e:
                if attempt == 2:
                    failed += len(rows)
                    print(f"  batch {lo}-{hi} failed: {str(e)[:110]}")
                else:
                    time.sleep(1.5 * (attempt + 1))
        if (lo // BATCH) % 20 == 0 and lo > start:
            el = time.time() - t0
            rate = sent / max(el, 1e-6)
            eta = (total - lo) / max(rate, 1e-6)
            print(f"  {lo}/{total}  sent={sent} failed={failed}  "
                  f"{rate:.0f} rows/s  eta {eta/60:.1f} min")

    el = time.time() - t0
    print(f"\ndone in {el/60:.1f} min — sent={sent} failed={failed} skipped={skipped}")
    try:
        n = supa.table("product_vectors").select("id", count="exact").limit(1).execute().count
        print(f"product_vectors now holds {n} rows")
    except Exception:
        pass
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
