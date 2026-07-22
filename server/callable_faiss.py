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
TOP_K                 = 40
REBUILD_COOLDOWN_SECS = 15 * 60   # 15 minutes
STORAGE_BUCKET        = "faiss-cache"

_HERE      = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR  = os.environ.get("FAISS_CACHE_DIR") or os.path.join(_HERE, "faiss_cache")
os.makedirs(CACHE_DIR, exist_ok=True)
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
# Maps every reasonable user-facing brand string → canonical name.
# Canonical name must match what _table_to_brand returns for that brand's table.
BRAND_ALIASES: dict[str, str] = {
    # Alo
    "alo": "alo", "alo yoga": "alo",
    # Hollister
    "hollister": "hollister", "hollister co": "hollister",
    # Gymshark
    "gymshark": "gymshark",
    # Essentials / Fear of God
    "essentials": "essentials", "fear of god": "essentials", "fog essentials": "essentials",
    # H&M
    "h&m": "h&m", "hm": "h&m", "h and m": "h&m",
    # Cotton On
    "cotton on": "cotton on", "cottonon": "cotton on",
    # Abercrombie
    "abercrombie": "abercrombie", "a&f": "abercrombie", "abercrombie and fitch": "abercrombie",
    # Zara
    "zara": "zara",
    # Urban Outfitters
    "urban outfitters": "urban_outfitters", "uo": "urban_outfitters",
    # Nike
    "nike": "nike",
    # Forever 21
    "forever 21": "forever21", "forever21": "forever21", "f21": "forever21",
    # Uniqlo
    "uniqlo": "uniqlo",
    # American Eagle
    "american eagle": "americaneagle", "americaneagle": "americaneagle", "ae outfitters": "americaneagle",
    # Aritzia
    "aritzia": "aritzia",
    # Romwe
    "romwe": "romwe",
    # Madewell
    "madewell": "madewell",
    # J.Crew
    "j crew": "jcrew", "j.crew": "jcrew", "jcrew": "jcrew",
    # Gap
    "gap": "gap",
    # Banana Republic
    "banana republic": "bananarepublic", "bananarepublic": "bananarepublic",
    # Calvin Klein
    "calvin klein": "calvinklein", "ck": "calvinklein",
    # Tommy Hilfiger
    "tommy hilfiger": "tommyhilfiger", "tommy": "tommyhilfiger",
    # Puma
    "puma": "puma",
    # Under Armour
    "under armour": "underarmour", "underarmour": "underarmour",
    # Vans
    "vans": "vans",
    # Carhartt
    "carhartt": "carhartt",
    # Champion
    "champion": "champion",
    # Stussy
    "stussy": "stussy",
    # Supreme
    "supreme": "supreme",
    # North Face
    "north face": "northface", "the north face": "northface",
    # Shein
    "shein": "shein",
    # Express
    "express": "express",
    # Reformation
    "reformation": "reformation",
    # Revolve
    "revolve": "revolve",
    # Princess Polly
    "princess polly": "princesspolly", "princesspolly": "princesspolly",
    # Pretty Little Thing
    "pretty little thing": "prettylittlething", "plt": "prettylittlething",
    # Nasty Gal
    "nasty gal": "nastygal", "nastygal": "nastygal",
    # Brandy Melville
    "brandy melville": "brandy_melville", "brandy": "brandy_melville",
    # Club Monaco
    "club monaco": "clubmonaco",
    # Tory Burch
    "tory burch": "toryburch",
    # Michael Kors
    "michael kors": "michaelkors",
    # Kate Spade
    "kate spade": "katespade",
    # Bape
    "bape": "bape", "a bathing ape": "bape",
    # Vuori
    "vuori": "vuori",
    # Outdoor Voices
    "outdoor voices": "outdoorvoices",
    # BooHooMAN
    "boohooman": "boohooman", "boohoo man": "boohooman",
    # Kith
    "kith": "kith",
    # ASSC
    "assc": "assc", "anti social social club": "assc",
    # Madhappy
    "madhappy": "madhappy",
    # Corteiz
    "corteiz": "corteiz",
    # Noah
    "noah": "noah",
    # Brain Dead
    "brain dead": "braindead", "braindead": "braindead",
    # Dickies
    "dickies": "dickies",
    # Good American
    "good american": "goodamerican",
    # Lounge
    "lounge": "lounge",
    # Meshki
    "meshki": "meshki",
    # Edikted
    "edikted": "edikted",
    # Dolls Kill
    "dolls kill": "dollskill",
    # Primark
    "primark": "primark",
    # Young LA
    "young la": "youngla", "youngla": "youngla",
    # Coofandy
    "coofandy": "coofandy",
    # With Jean
    "with jean": "withjean",
    # IAM GIA
    "iam gia": "iamgia", "iamgia": "iamgia",
    # Revice
    "revice": "revice",
    # Awakeny
    "awakeny": "awakeny",
    # Eric Emanuel
    "eric emanuel": "ericemanuel",
    # Good American
    "goodamerican": "goodamerican",
}

def _resolve_brand(brand: str | None) -> str | None:
    if not brand:
        return None
    key = brand.lower().strip()
    for alias, canonical in BRAND_ALIASES.items():
        if alias in key or key in alias:
            return canonical
    return None

# Gendered and otherwise split tables that share one canonical brand name.
# Canonical must match the value returned for single-table brands (table suffix).
_TABLE_BRAND_OVERRIDES = {
    "alo_womens":              "alo",
    "alo_mens":                "alo",
    "abercrombie_mens":        "abercrombie",
    "abercrombie_womens":      "abercrombie",
    "cottonon_mens":           "cotton on",
    "cottonon_womens":         "cotton on",
    "essentials_mens":         "essentials",
    "essentials_womens":       "essentials",
    "forever21_mens":          "forever21",
    "forever21_womens":        "forever21",
    "gymshark_mens":           "gymshark",
    "gymshark_womens":         "gymshark",
    "hm_mens":                 "h&m",
    "hm_womens":               "h&m",
    "hollister_mens":          "hollister",
    "hollister_womens":        "hollister",
    "nike_mens":               "nike",
    "nike_womens":             "nike",
    "uniqlo_mens":             "uniqlo",
    "uniqlo_womens":           "uniqlo",
    "urban_outfitters_womens": "urban_outfitters",
    "zara_mens":               "zara",
    "zara_womens":             "zara",
}

def _table_to_brand(table: str) -> str:
    suffix = table.removeprefix("products_")
    return _TABLE_BRAND_OVERRIDES.get(suffix, suffix)


import re as _re

# Keywords that appear IN TITLES and signal one gender.
# Checked in order: womens first (so "women" in "womenswear" doesn't get hit by "men").
_FEMALE_TITLE_RE = _re.compile(
    r"\b(women|womens|woman|womenswear|women's|female|ladies|girl|girls|"
    r"dress|skirt|midi\s+skirt|maxi\s+skirt|blouse|"
    r"bralette|sports\s*bra|\bbra\b|"
    r"heel|pump|mule|wedge|stiletto|"
    r"cami|camisole|romper|jumpsuit|bodycon|"
    r"crop\s+top|tube\s+top|off.?shoulder)\b",
    _re.IGNORECASE
)
_MALE_TITLE_RE = _re.compile(
    r"\b(men|mens|menswear|men's|male|boys?|"
    r"boxer|briefs|boxer.brief)\b",
    _re.IGNORECASE
)


def _gender_from_name(name: str) -> str | None:
    """
    Infer gender from a table name, brand name, or product title.
    Checks anywhere in the string (not just suffix), womens wins if both match.
    """
    n = name.lower()
    if _re.search(r"women|womans|womens|womenswear|woman", n):
        return "womens"
    if _re.search(r"\bmen\b|mens|menswear|male", n):
        return "mens"
    if n.endswith(("_womens", "_women")):
        return "womens"
    if n.endswith(("_mens", "_men")):
        return "mens"
    return None


def _gender_from_title(title: str) -> str | None:
    """Infer gender from product title keywords."""
    if not title:
        return None
    if _FEMALE_TITLE_RE.search(title):
        return "womens"
    if _MALE_TITLE_RE.search(title):
        return "mens"
    return None


def _gender_from_table(table: str) -> str | None:
    """Derive gender from table name — checks anywhere in the name, not just suffix."""
    return _gender_from_name(table)


def _gender_from_source(source: str) -> str | None:
    """Infer gender from the source/brand string stored in meta."""
    return _gender_from_name(source)


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
    print(f"[OK] FAISS loaded from {src} - {len(meta)} vectors")


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


def _parse_emb(val) -> list | None:
    """Parse an embedding value that may come back as a JSON string or a list."""
    if val is None:
        return None
    if isinstance(val, str):
        import json as _json
        return _json.loads(val)
    return val


# Tables that use per-image embeddings from product_image_embeddings
# instead of (or in addition to) combined_embedding per product row.
_MULTI_IMAGE_TABLES: set[str] = {"products_alo_womens", "products_alo_mens"}


# ── Fetch + build ──────────────────────────────────────────────────────────────
def _fetch_all_products(tables: list[str]) -> tuple[list, list]:
    supa = get_supa()
    PAGE = 1000
    vecs: list[np.ndarray] = []
    meta: list[dict]       = []

    for table in tables:
        brand   = _table_to_brand(table)
        gender  = _gender_from_table(table)
        print(f"  loading {table}…")

        # Detect the embedding column + which meta columns exist from ONE probe
        # row, so the paged fetch below selects ONLY the columns we need. SELECT *
        # pulled every big embedding/description column for every row and blew the
        # container's memory mid-fetch on large tables.
        try:
            probe = supa.table(table).select("*").limit(1).execute()
        except Exception as e:
            print(f"  ⚠️  error probing {table}: {e}")
            continue
        if not probe.data:
            print(f"    → {len(meta)} rows so far")
            continue
        emb_col = _detect_embedding_col(probe.data[0])
        if emb_col is None:
            print(f"  ⚠️  no embedding column in {table} — skipping")
            continue
        print(f"    column: '{emb_col}'")

        wanted      = ["id", "title", "price", "color", "url", "image", "gender"]
        cols        = [c for c in wanted if c in probe.data[0]]
        if emb_col not in cols:
            cols.append(emb_col)
        select_cols = ",".join(cols)

        offset = 0
        while True:
            try:
                res = supa.table(table).select(select_cols).range(offset, offset + PAGE - 1).execute()
            except Exception as e:
                print(f"  ⚠️  error reading {table}: {e}")
                break
            rows = res.data or []
            if not rows:
                break

            for row in rows:
                emb = _parse_emb(row.get(emb_col))
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
                    "gender": row.get("gender") or gender,  # prefer DB value over table-name inference
                })

            if len(rows) < PAGE:
                break
            offset += PAGE

        print(f"    → {len(meta)} rows so far")

    # ── Multi-image embeddings from product_image_embeddings ──────────────────
    # For alo (and any future _MULTI_IMAGE_TABLES), we also load one vector per
    # product image.  These overlap with the combined_embedding entries above;
    # _run_search deduplicates by (source, product_id) keeping the best match.
    for table in [t for t in tables if t in _MULTI_IMAGE_TABLES]:
        brand  = _table_to_brand(table)
        gender = _gender_from_table(table)
        print(f"  loading product_image_embeddings for {table}…")

        # Build product-id → metadata lookup (one query)
        prod_meta: dict[int, dict] = {}
        off = 0
        while True:
            try:
                res = (supa.table(table)
                       .select("id,title,price,color,url,image")
                       .range(off, off + PAGE - 1)
                       .execute())
            except Exception as e:
                print(f"  ⚠️  error reading {table} metadata: {e}")
                break
            for r in (res.data or []):
                prod_meta[r["id"]] = r
            if len(res.data or []) < PAGE:
                break
            off += PAGE

        if not prod_meta:
            print(f"    no products found — skipping image embeddings")
            continue

        # Load per-image embeddings
        off = 0
        n_img = 0
        while True:
            try:
                res = (supa.table("product_image_embeddings")
                       .select("product_id,image_url,embedding")
                       .eq("source_table", table)
                       .range(off, off + PAGE - 1)
                       .execute())
            except Exception as e:
                print(f"  ⚠️  error reading product_image_embeddings for {table}: {e}")
                break
            rows = res.data or []
            for row in rows:
                emb = _parse_emb(row.get("embedding"))
                if emb is None:
                    continue
                pm = prod_meta.get(row["product_id"], {})
                vecs.append(np.array(emb, dtype=np.float32))
                meta.append({
                    "id":     pm.get("id"),
                    "title":  pm.get("title", ""),
                    "price":  pm.get("price", ""),
                    "color":  pm.get("color", ""),
                    "url":    pm.get("url", ""),
                    "image":  pm.get("image", "") or row.get("image_url", ""),
                    "source": brand,
                    "gender": gender,
                })
                n_img += 1
            if len(rows) < PAGE:
                break
            off += PAGE

        print(f"    → {n_img} image-level vectors added")

    return vecs, meta


def _build_and_persist(tables: list[str], row_count: int) -> bool:
    print(f"⚙️  Building FAISS index — {row_count} products across {len(tables)} tables…")
    vecs_list, meta = _fetch_all_products(tables)

    if not vecs_list:
        print("⚠️  No embeddings found — index not built.")
        return False

    vecs  = np.stack(vecs_list)
    del vecs_list  # free the per-row array list (~N×dim) before the heavy writes
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

    # Accept both the canonical name (indexes built after the fix) AND every
    # table-derived suffix that maps to this canonical (indexes built before,
    # where source was stored as e.g. "hollister_mens" instead of "hollister").
    matching_sources = {canonical_brand}
    for suffix, brand in _TABLE_BRAND_OVERRIDES.items():
        if brand == canonical_brand:
            matching_sources.add(suffix)

    idxs = [i for i, m in enumerate(meta) if m["source"] in matching_sources]
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
def _run_search(qv, index, meta: list, top_k: int = TOP_K) -> list:
    qv = np.array(qv, dtype=np.float32).reshape(1, -1)
    # Fetch more candidates than needed so deduplication still yields top_k results.
    fetch_k = min(top_k * 4, len(meta))
    D, I    = index.search(qv, fetch_k)

    # Deduplicate: keep the closest (lowest L2 distance) entry per product.
    # Key is (source, product_id) — products that appear multiple times in the
    # index (once per image from product_image_embeddings) collapse to one result.
    best: dict = {}
    for d, i in zip(D[0], I[0]):
        m    = meta[i]
        key  = (m.get("source"), m.get("id") or m.get("url", ""))
        dist = float(d)
        if key not in best or dist < best[key]["distance"]:
            best[key] = {**dict(m), "distance": dist}

    return sorted(best.values(), key=lambda r: r["distance"])[:top_k]


def _item_gender(r: dict) -> str | None:
    """
    Gender of a search result.
    Priority: explicit gender field → source/brand name → product title keywords.
    """
    explicit = r.get("gender") or _gender_from_source(r.get("source", ""))
    if explicit:
        return explicit
    return _gender_from_title(r.get("title", ""))


def _filter_by_gender(results: list, gender: str | None) -> list:
    """Keep only results matching gender (or with no gender tag). No fallback — empty is correct."""
    if not gender:
        return results
    return [r for r in results if _item_gender(r) in (gender, None)]


def search_similar_products(query_vector, brand: str | None = None,
                            gender: str | None = None,
                            top_k: int = TOP_K) -> list:
    if not _ensure_index():
        return []

    canonical = _resolve_brand(brand)
    if canonical:
        sub_idx, sub_meta = _brand_sub_index(canonical)
        if sub_idx is not None:
            print(f"🔍 Brand search: '{canonical}' ({len(sub_meta)} products), gender={gender}, top_k={top_k}")
            return _filter_by_gender(_run_search(query_vector, sub_idx, sub_meta, top_k), gender)
        print(f"⚠️  No '{canonical}' products — falling back to full catalog")

    print(f"🔍 Full-catalog search ({len(_MEM['meta'])} products), gender={gender}, top_k={top_k}")
    return _filter_by_gender(_run_search(query_vector, _MEM["index"], _MEM["meta"], top_k), gender)


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
