"""
FAISS similarity search — all Supabase products_* tables.

Index lifecycle
  1. Startup warmup (background thread):
       a. Local disk fingerprint matches live row count  → load from disk (fast).
       b. Supabase Storage has a matching build          → download + load.
       c. Otherwise                                      → rebuild, save, upload.
  2. Background rebuild worker:
       Wakes every REBUILD_COOLDOWN_SECS or when notify_rebuild_needed() is
       called. Rebuilds only if row count changed AND cooldown expired.
  3. After any rebuild: update faiss_meta in Supabase DB and upload the three
     index files to Supabase Storage.

Supabase setup (one-time):
  • Run SQL:
      CREATE TABLE IF NOT EXISTS faiss_meta (
        id INTEGER PRIMARY KEY DEFAULT 1,
        row_count INTEGER, last_built_at TIMESTAMPTZ, status TEXT DEFAULT 'pending',
        CONSTRAINT faiss_meta_singleton CHECK (id = 1)
      );
      INSERT INTO faiss_meta (id) VALUES (1) ON CONFLICT DO NOTHING;
  • Create Storage bucket 'faiss-cache' (private).
  • In Storage → Settings raise Max Upload Size to ≥ 200 MB.
"""
import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

import json
import pickle
import threading
import requests as _requests
from datetime import datetime, timezone

import numpy as np
import faiss

from db import get_supa
from config import SUPABASE_URL, SUPABASE_SERVICE_KEY

# ── Config ─────────────────────────────────────────────────────────────────────
TOP_K                 = 5
REBUILD_COOLDOWN_SECS = 15 * 60   # 15 minutes
STORAGE_BUCKET        = "faiss-cache"

_HERE      = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR  = os.path.join(_HERE, "faiss_cache")
INDEX_FILE = os.path.join(CACHE_DIR, "all_products.index")
META_FILE  = os.path.join(CACHE_DIR, "all_products_meta.pkl")
EMBED_FILE = os.path.join(CACHE_DIR, "all_products_embeddings.npy")
FP_FILE    = os.path.join(CACHE_DIR, "fingerprint.json")

os.makedirs(CACHE_DIR, exist_ok=True)

# ── In-process state ───────────────────────────────────────────────────────────
_MEM:            dict            = {"index": None, "meta": None, "embeddings": None}
_LOCK:           threading.Lock  = threading.Lock()
_REBUILD_NEEDED: threading.Event = threading.Event()

# ── Brand normalisation ────────────────────────────────────────────────────────
BRAND_ALIASES = {
    "gymshark": "gymshark", "hollister": "hollister",
    "essentials": "essentials", "fear of god": "essentials",
    "h&m": "h&m", "hm": "h&m",
    "cotton on": "cotton on", "cottonon": "cotton on",
    "abercrombie": "abercrombie", "a&f": "abercrombie",
    "alo": "alo", "alo yoga": "alo",
    "romwe": "romwe", "aritzia": "aritzia", "zara": "zara",
    "urban outfitters": "urban_outfitters",
}

def _resolve_brand(brand: str | None) -> str | None:
    if not brand:
        return None
    key = brand.lower().strip()
    for alias, canonical in BRAND_ALIASES.items():
        if alias in key or key in alias:
            return canonical
    return None

def _table_to_brand(table: str) -> str:
    return table.removeprefix("products_")


# ── Table discovery ────────────────────────────────────────────────────────────
def _discover_product_tables() -> list[str]:
    try:
        headers = {
            "apikey": SUPABASE_SERVICE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        }
        res = _requests.get(f"{SUPABASE_URL}/rest/v1/", headers=headers, timeout=10)
        if not res.ok:
            print(f"⚠️  Schema fetch failed: {res.status_code}")
            return []
        paths  = res.json().get("paths", {})
        tables = sorted(p.strip("/") for p in paths if p.strip("/").startswith("products_"))
        print(f"  discovered {len(tables)} product tables")
        return tables
    except Exception as e:
        print(f"⚠️  Table discovery failed: {e}")
        return []


# ── Row count ──────────────────────────────────────────────────────────────────
def _count_products(tables: list[str]) -> int:
    supa  = get_supa()
    total = 0
    for table in tables:
        try:
            res    = supa.table(table).select("*", count="exact").limit(0).execute()
            total += res.count or 0
        except Exception:
            pass
    return total


# ── Supabase faiss_meta table ──────────────────────────────────────────────────
def _get_faiss_meta() -> dict | None:
    try:
        res = get_supa().table("faiss_meta").select("*").eq("id", 1).execute()
        return res.data[0] if res.data else None
    except Exception:
        return None

def _update_faiss_meta(row_count: int, status: str = "ready") -> None:
    try:
        get_supa().table("faiss_meta").upsert({
            "id":            1,
            "row_count":     row_count,
            "last_built_at": datetime.now(timezone.utc).isoformat(),
            "status":        status,
        }, on_conflict="id").execute()
    except Exception as e:
        print(f"⚠️  faiss_meta update failed: {e}")


# ── Supabase Storage ───────────────────────────────────────────────────────────
# Only upload the small files (fingerprint + metadata).  The large binary index
# (~110 MB) stays on local disk — it persists across server restarts on the same
# machine and Supabase free-tier has a 50 MB default file-size limit anyway.
# The faiss_meta table handles cooldown coordination; Storage handles recovery
# of the metadata on a fresh machine (the index itself must be rebuilt there).
_UPLOAD_FILES   = [(FP_FILE,  "fingerprint.json"),
                   (META_FILE, "all_products_meta.pkl")]
_DOWNLOAD_FILES = [(FP_FILE,  "fingerprint.json"),
                   (META_FILE, "all_products_meta.pkl")]

def _upload_to_supabase() -> None:
    supa = get_supa()
    print("📤 Uploading FAISS index to Supabase Storage…")
    for local_path, remote_name in _UPLOAD_FILES:
        if not os.path.exists(local_path):
            continue
        try:
            with open(local_path, "rb") as f:
                data = f.read()
            supa.storage.from_(STORAGE_BUCKET).upload(
                remote_name, data,
                {"content-type": "application/octet-stream", "upsert": "true"},
            )
            print(f"  ✅ {remote_name} ({len(data)/1_048_576:.1f} MB)")
        except Exception as e:
            print(f"  ⚠️  Upload {remote_name} failed: {e}")

def _download_from_supabase() -> bool:
    """Returns True if the core files (index + meta) were downloaded OK."""
    supa = get_supa()
    print("📥 Downloading FAISS index from Supabase Storage…")
    downloaded: set[str] = set()
    for local_path, remote_name in _DOWNLOAD_FILES:
        try:
            data = supa.storage.from_(STORAGE_BUCKET).download(remote_name)
            with open(local_path, "wb") as f:
                f.write(data)
            print(f"  ✅ {remote_name} ({len(data)/1_048_576:.1f} MB)")
            downloaded.add(remote_name)
        except Exception as e:
            print(f"  ⚠️  Download {remote_name} failed: {e}")
    return {"all_products.index", "all_products_meta.pkl"}.issubset(downloaded)


# ── Local disk helpers ─────────────────────────────────────────────────────────
def _local_cache_valid(live_count: int) -> bool:
    if not os.path.exists(INDEX_FILE) or not os.path.exists(META_FILE):
        return False
    try:
        with open(FP_FILE) as f:
            return json.load(f).get("row_count") == live_count
    except Exception:
        return False

def _load_from_disk() -> None:
    idx  = faiss.read_index(INDEX_FILE)
    with open(META_FILE, "rb") as f:
        meta = pickle.load(f)
    # Load embeddings numpy if present (used for fast brand sub-indexing).
    # If absent we reconstruct from the FAISS index on demand.
    vecs = np.load(EMBED_FILE) if os.path.exists(EMBED_FILE) else None
    _MEM["index"]      = idx
    _MEM["meta"]       = meta
    _MEM["embeddings"] = vecs
    src = "disk+embeddings" if vecs is not None else "disk (no embeddings file)"
    print(f"✅ FAISS loaded from {src} — {len(meta)} vectors")


# ── Embedding column detection ─────────────────────────────────────────────────
_EMB_CANDIDATES = [
    "combined_embedding", "embedding", "vector_embedding",
    "image_embedding", "text_embedding",
]

def _detect_embedding_col(row: dict) -> str | None:
    for col in _EMB_CANDIDATES:
        if col in row and row[col] is not None:
            return col
    for key, val in row.items():
        if isinstance(val, list) and len(val) > 10 and isinstance(val[0], (int, float)):
            return key
    return None


# ── Fetch + build ──────────────────────────────────────────────────────────────
def _fetch_all_products(tables: list[str]) -> tuple[list, list]:
    supa = get_supa()
    PAGE = 1000
    vecs: list[np.ndarray] = []
    meta: list[dict]       = []

    for table in tables:
        brand   = _table_to_brand(table)
        offset  = 0
        emb_col = None
        print(f"  loading {table}…")

        while True:
            try:
                res = supa.table(table).select("*").range(offset, offset + PAGE - 1).execute()
            except Exception as e:
                print(f"  ⚠️  error reading {table}: {e}")
                break
            rows = res.data or []
            if not rows:
                break

            if emb_col is None:
                emb_col = _detect_embedding_col(rows[0])
                if emb_col is None:
                    print(f"  ⚠️  no embedding column in {table} — skipping")
                    break
                print(f"    column: '{emb_col}'")

            for row in rows:
                emb = row.get(emb_col)
                if emb is None:
                    continue
                vecs.append(np.array(emb, dtype=np.float32))
                meta.append({
                    "id":     row.get("id"),
                    "title":  row.get("title", ""),
                    "price":  row.get("price", ""),
                    "color":  row.get("color", ""),
                    "url":    row.get("url", ""),
                    "image":  row.get("image", ""),
                    "source": brand,
                })

            if len(rows) < PAGE:
                break
            offset += PAGE

        print(f"    → {len(meta)} rows so far")
    return vecs, meta


def _build_and_persist(tables: list[str], row_count: int) -> bool:
    print(f"⚙️  Building FAISS index — {row_count} products across {len(tables)} tables…")
    vecs_list, meta = _fetch_all_products(tables)

    if not vecs_list:
        print("⚠️  No embeddings found — index not built.")
        return False

    vecs  = np.stack(vecs_list)
    dim   = vecs.shape[1]
    index = faiss.IndexFlatL2(dim)
    index.add(vecs)

    faiss.write_index(index, INDEX_FILE)
    np.save(EMBED_FILE, vecs)
    with open(META_FILE, "wb") as f:
        pickle.dump(meta, f)
    with open(FP_FILE, "w") as f:
        json.dump({
            "row_count": row_count,
            "tables":    tables,
            "built_at":  datetime.now(timezone.utc).isoformat(),
        }, f)

    _MEM["index"]      = index
    _MEM["meta"]       = meta
    _MEM["embeddings"] = vecs
    print(f"✅ FAISS index ready — {len(meta)} vectors, dim={dim}")
    return True


# ── _ensure_index ──────────────────────────────────────────────────────────────
def _ensure_index() -> bool:
    with _LOCK:
        if _MEM["index"] is not None:
            return True

        tables = _discover_product_tables()
        if not tables:
            return False

        live_count = _count_products(tables)
        if live_count == 0:
            return False

        # 1. Local disk cache valid?
        if _local_cache_valid(live_count):
            _load_from_disk()
            return True

        # 2. Supabase Storage has a matching build?
        db_meta = _get_faiss_meta()
        if (db_meta and db_meta.get("row_count") == live_count
                and db_meta.get("status") == "ready"):
            if _download_from_supabase() and _local_cache_valid(live_count):
                _load_from_disk()
                return True

        # 3. Full rebuild
        ok = _build_and_persist(tables, live_count)
        if ok:
            _update_faiss_meta(live_count, "ready")
            threading.Thread(
                target=_upload_to_supabase, daemon=True, name="faiss-upload"
            ).start()
        return ok


# ── Background rebuild worker ──────────────────────────────────────────────────
def _maybe_rebuild() -> None:
    """Check cooldown + row count and rebuild if warranted."""
    db_meta = _get_faiss_meta()

    # Cooldown: skip if rebuilt recently
    last_built_at = (db_meta or {}).get("last_built_at")
    if last_built_at:
        try:
            last = datetime.fromisoformat(last_built_at.replace("Z", "+00:00"))
            elapsed = (datetime.now(timezone.utc) - last).total_seconds()
            if elapsed < REBUILD_COOLDOWN_SECS:
                print(f"⏳ FAISS rebuild skipped — cooldown ({int(REBUILD_COOLDOWN_SECS - elapsed)}s left)")
                return
        except Exception:
            pass

    tables = _discover_product_tables()
    if not tables:
        return

    live_count   = _count_products(tables)
    stored_count = (db_meta or {}).get("row_count", -1)

    if live_count == stored_count and _local_cache_valid(live_count):
        return  # nothing changed

    print(f"🔄 FAISS background rebuild ({stored_count} → {live_count} rows)…")
    _update_faiss_meta(live_count, "building")
    with _LOCK:
        ok = _build_and_persist(tables, live_count)
    if ok:
        _update_faiss_meta(live_count, "ready")
        _upload_to_supabase()


def start_background_worker() -> None:
    """Spawn the daemon thread. Call once from main.py at startup."""
    def _worker():
        while True:
            # Wake when notified by a scraper OR after the cooldown period
            _REBUILD_NEEDED.wait(timeout=REBUILD_COOLDOWN_SECS)
            _REBUILD_NEEDED.clear()
            try:
                _maybe_rebuild()
            except Exception as e:
                print(f"⚠️  Background rebuild error: {e}")

    threading.Thread(target=_worker, daemon=True, name="faiss-rebuild").start()
    print("⚙️  FAISS background rebuild worker started (cooldown: 15 min)")


# ── Public API ─────────────────────────────────────────────────────────────────
def notify_rebuild_needed() -> None:
    """Call after scraping new products. Triggers rebuild after cooldown."""
    _REBUILD_NEEDED.set()
    print("🏷️  FAISS rebuild queued")


def force_rebuild() -> None:
    """Immediate rebuild ignoring cooldown (CLI / admin use)."""
    tables     = _discover_product_tables()
    live_count = _count_products(tables)
    with _LOCK:
        ok = _build_and_persist(tables, live_count)
    if ok:
        _update_faiss_meta(live_count, "ready")
        _upload_to_supabase()


def get_status() -> dict:
    """Returns a status dict suitable for an admin endpoint."""
    db_meta = _get_faiss_meta()
    return {
        "in_memory":    _MEM["index"] is not None,
        "vector_count": len(_MEM["meta"]) if _MEM["meta"] else 0,
        "has_embeddings": _MEM["embeddings"] is not None,
        "db_meta":      db_meta,
    }


# ── Brand sub-index ────────────────────────────────────────────────────────────
def _brand_sub_index(canonical_brand: str):
    meta  = _MEM["meta"]
    index = _MEM["index"]
    vecs  = _MEM["embeddings"]

    idxs = [i for i, m in enumerate(meta) if m["source"] == canonical_brand]
    if not idxs:
        return None, None

    if vecs is not None:
        sub_vecs = vecs[idxs]
    else:
        # Reconstruct vectors from the FAISS index (no embeddings file)
        sub_vecs = np.array([index.reconstruct(i) for i in idxs], dtype=np.float32)

    sub_meta = [meta[i] for i in idxs]
    sub_idx  = faiss.IndexFlatL2(sub_vecs.shape[1])
    sub_idx.add(sub_vecs)
    return sub_idx, sub_meta


# ── Search ─────────────────────────────────────────────────────────────────────
def _run_search(qv, index, meta: list) -> list:
    qv   = np.array(qv, dtype=np.float32).reshape(1, -1)
    k    = min(TOP_K, len(meta))
    D, I = index.search(qv, k)
    return [
        {**dict(meta[i]), "distance": float(d)}
        for d, i in zip(D[0], I[0])
    ]


def search_similar_products(query_vector, brand: str | None = None) -> list:
    if not _ensure_index():
        return []

    canonical = _resolve_brand(brand)
    if canonical:
        sub_idx, sub_meta = _brand_sub_index(canonical)
        if sub_idx is not None:
            print(f"🔍 Brand search: '{canonical}' ({len(sub_meta)} products)")
            return _run_search(query_vector, sub_idx, sub_meta)
        print(f"⚠️  No '{canonical}' products — falling back to full catalog")

    print(f"🔍 Full-catalog search ({len(_MEM['meta'])} products)")
    return _run_search(query_vector, _MEM["index"], _MEM["meta"])


# ── CLI ────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    if "--rebuild" in sys.argv:
        force_rebuild()
    elif "--status" in sys.argv:
        import pprint; pprint.pprint(get_status())
    else:
        ok = _ensure_index()
        print(f"Index ready: {len(_MEM['meta'])} vectors" if ok else "No products found.")
