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


def _rows(meta, vecs, start, end, seen):
    """Build upsert rows, dropping keys already emitted.

    The metadata holds 206,945 entries but only 191,839 distinct
    (source, product_id, image) tuples - alo products repeat an image across
    colour variants. Postgres rejects a whole batch with "ON CONFLICT DO UPDATE
    command cannot affect row a second time" if one appears twice, so the
    duplicates have to go before the request, not after.
    """
    out = []
    for i in range(start, end):
        m = meta[i]
        image = m.get("image") or ""
        pid = m.get("id")
        if pid is None or not image:
            continue                      # cannot key it; skip
        key = (m.get("source") or "", str(pid), image)
        if key in seen:
            continue
        seen.add(key)
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

    # Fail fast and say what to do. Without this the run grinds through every
    # batch, retrying each three times, before reporting the same thing 400x.
    try:
        supa.table("product_vectors").select("id").limit(1).execute()
    except Exception as e:
        if "PGRST205" in str(e) or "product_vectors" in str(e):
            print("product_vectors does not exist yet.")
            print("")
            print("Run this first, in the Supabase SQL editor:")
            print("    server/migrations/008_pgvector_search.sql")
            print("")
            print("  Supabase dashboard -> SQL Editor -> New query -> paste the file -> Run.")
            print("  It creates the table, the HNSW index and match_products().")
            return 2
        raise

    # mmap keeps the 404 MB file on disk instead of in RAM
    vecs = np.load(EMBED_FILE, mmap_mode="r")
    with open(META_FILE, "rb") as f:
        meta = pickle.load(f)
    assert len(meta) == vecs.shape[0], f"meta {len(meta)} != vecs {vecs.shape[0]}"

    total = args.limit or len(meta)
    start = 0

    # Rows already loaded, keyed the same way as the unique constraint. Counting
    # rows is not enough to resume from: duplicates mean the row count stops
    # tracking the index into meta, so seed from the real keys instead.
    seen: set = set()
    if args.resume:
        page, got = 1000, 0
        try:
            while True:
                r = (supa.table("product_vectors")
                     .select("source, product_id, image")
                     .range(got, got + page - 1).execute().data or [])
                if not r:
                    break
                for x in r:
                    seen.add((x.get("source") or "", str(x.get("product_id")), x.get("image") or ""))
                got += len(r)
                if len(r) < page:
                    break
                if got % 20000 == 0:
                    print(f"  read {got} existing keys...")
            print(f"resuming: {len(seen)} rows already loaded, will skip those")
        except Exception as e:
            print(f"could not read existing keys ({str(e)[:70]}); loading everything")
            seen = set()

    print(f"backfilling {total - start} of {len(meta)} vectors, batches of {BATCH}")
    sent = failed = skipped = 0
    t0 = time.time()
    for lo in range(start, total, BATCH):
        hi = min(lo + BATCH, total)
        rows = _rows(meta, vecs, lo, hi, seen)
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
