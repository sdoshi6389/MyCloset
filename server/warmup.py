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
