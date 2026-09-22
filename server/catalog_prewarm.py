"""Start background-removing catalog images as soon as they are recommended.

The browser requests an extraction per card when it renders, so the work happens
either way — but serially-ish, after paint, and a cold card that escalates to
Gemini can take ~18 s while the user stares at a raw product photo.

Kicking the same extractions off when the recommendation is built means they are
usually cached by the time the card asks, without changing what gets extracted
or what it costs. Dedup keeps concurrent slot clicks from doubling the work.
"""
import threading
from concurrent.futures import ThreadPoolExecutor

# Small pool: these are network/API bound, and we never want prewarm to starve
# request handling (gunicorn runs few worker threads).
_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="prewarm")
_inflight: set[tuple] = set()
_lock = threading.Lock()


def _run(key, image_url, slot, product_url, source_brand, product_name):
    try:
        from catalog_icon import extract_catalog_icon
        extract_catalog_icon(image_url, slot,
                             product_url=product_url,
                             source_brand=source_brand,
                             product_name=product_name)
    except Exception as e:
        print(f"⚠️  prewarm failed ({slot}): {type(e).__name__}: {e}")
    finally:
        with _lock:
            _inflight.discard(key)


def prewarm(candidates: list[dict], slot: str, limit: int = 5) -> int:
    """Queue background extraction for catalog candidates. Returns how many started."""
    started = 0
    for c in candidates[:limit]:
        image_url = c.get("image_url")
        if not image_url:
            continue
        key = (image_url, slot)
        with _lock:
            if key in _inflight:
                continue
            _inflight.add(key)
        try:
            _POOL.submit(_run, key, image_url, slot,
                         c.get("shop_url"), c.get("brand"), c.get("title"))
            started += 1
        except Exception as e:
            with _lock:
                _inflight.discard(key)
            print(f"⚠️  prewarm submit failed: {e}")
    return started
