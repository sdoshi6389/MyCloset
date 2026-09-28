"""Pre-load the FAISS catalog index and CLIP text encoder off the request path.

Cold, the first catalog recommendation pays ~10 s to load 200k+ vectors from
disk plus a CLIP model load — ~30 s end to end. Warming happens at most once
per process, in a daemon thread, so requests never block on it.

kick() is called on login/refresh (so a deployed instance can still sleep when
nobody is signed in) and at boot unless we're on Railway — there the extra
resident RAM and the boot-time Supabase calls would defeat instance sleeping.
Override either way with WARMUP_ON_BOOT=true|false.
"""
import os
import threading
import time

# How many closets to prepare ahead of anyone asking.
PRECOMPUTE_USERS = 3

_started = False
_lock = threading.Lock()


def _run() -> None:
    t0 = time.time()
    try:
        from callable_faiss import warm_index
        ok = warm_index()
        print(f"🔥 FAISS index warm ({'ok' if ok else 'unavailable'}) in {time.time() - t0:.1f}s")
    except Exception as e:
        print(f"⚠️  FAISS warmup failed: {e}")
    t1 = time.time()
    try:
        from callable_embedding import encode_text
        encode_text("warmup")
        print(f"🔥 CLIP text encoder warm in {time.time() - t1:.1f}s")
    except Exception as e:
        print(f"⚠️  CLIP warmup failed: {e}")

    _precompute_suggestions()


def _precompute_suggestions() -> None:
    """Build the recommendations for recently active closets ahead of time.

    Warming FAISS and CLIP only means the models are loaded; the first person to
    open the page still pays for assembling looks and running a catalog search
    per look. Doing it here, while nobody is waiting, means the page is served
    from cache instead. Failures are ignored -- this is an optimisation, and the
    endpoints still work without it.
    """
    t = time.time()
    try:
        from db import get_supa
        from recommendation.outfit_suggest import suggest_outfits, discover_additions

        rows = (get_supa().table("closet_items")
                .select("user_id")
                .order("uploaded_at", desc=True)
                .limit(400).execute().data) or []
        seen, users = set(), []
        for r in rows:                       # most recently active first
            uid = r.get("user_id")
            if uid and uid not in seen:
                seen.add(uid)
                users.append(uid)
            if len(users) >= PRECOMPUTE_USERS:
                break

        # Fill the same cache the endpoints read, under the same keys, or the
        # work is done twice and the page still waits.
        from suggestions_bp import _cache_key, _cache_put, POOL_SIZE
        for uid in users:
            try:
                looks = suggest_outfits(uid, weather=None, count=POOL_SIZE)
                if looks:
                    _cache_put(_cache_key("outfits", uid, None), looks)
                found = discover_additions(uid, weather=None, count=POOL_SIZE,
                                           max_new=2, gender=None)
                if found:
                    _cache_put(_cache_key("discover", uid, None,
                                          max_new=2, gender=""), found)
            except Exception as e:
                print(f"⚠️  precompute failed for user {uid}: {type(e).__name__}: {e}")
        if users:
            print(f"🔥 suggestions precomputed for {len(users)} closet(s) "
                  f"in {time.time() - t:.1f}s")
    except Exception as e:
        print(f"⚠️  suggestion precompute skipped: {type(e).__name__}: {e}")


def kick() -> None:
    """Start the warmup thread if it hasn't run yet. Idempotent and non-blocking."""
    global _started
    if _started:
        return
    with _lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_run, daemon=True, name="warmup").start()


def _on_railway() -> bool:
    # Railway injects several RAILWAY_* vars; don't rely on any single name.
    return any(k.startswith("RAILWAY_") for k in os.environ)


def kick_on_boot_if_enabled() -> None:
    flag = os.environ.get("WARMUP_ON_BOOT", "").strip().lower()
    if flag:
        enabled = flag in ("1", "true", "yes")
    else:
        # Off by default on Railway: warming holds ~1.5 GB resident (FAISS + CLIP)
        # and the outbound calls keep the instance from sleeping. It warms on the
        # first login instead, which is early enough to hide the cost from users.
        enabled = not _on_railway()
    if enabled:
        kick()
    else:
        print("⏸️  Boot warmup skipped (Railway) — will warm on first login")
