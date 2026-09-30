"""Recommendations-for-you surface — /suggestions

Two reads:
  /suggestions/outfits  — complete looks assembled from the user's own closet
  /suggestions/discover — their looks plus one or two catalog pieces

Both take optional lat/lon. Weather steers ranking when it is supplied and is
simply absent when it is not, so the page works before anyone grants location.
"""
import threading
import time

import jwt
from flask import Blueprint, request, jsonify

from config import JWT_SECRET
from weather import get_weather

suggestions_bp = Blueprint("suggestions", __name__)

# Assembling looks means scoring every candidate against a partial outfit, and
# Discover adds a catalog search per look on top. None of that changes minute to
# minute, so a short cache turns a revisit from seconds into nothing. Keyed on
# the weather season rather than the raw temperature, since a 0.4 degree change
# should not invalidate anything.
_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_TTL = 600
_CACHE_LOCK = threading.Lock()


# One pool per closet, sliced to whatever the caller asked for. Keying on the
# requested count instead meant a precomputed pool of 12 was a miss for a page
# asking for 6, and every refresh was a fresh cache entry.
POOL_SIZE = 12


def _cache_key(kind: str, user_id: int, weather: dict | None, **kw) -> tuple:
    season = (weather or {}).get("season")
    layers = (weather or {}).get("layers")
    return (kind, user_id, season, layers, tuple(sorted(kw.items())))


_INFLIGHT: set = set()
_INFLIGHT_LOCK = threading.Lock()


def _prefetch(kind: str, user_id: int, weather: dict | None, variant: int, **kw) -> None:
    """Build the next variant off the request thread.

    Paging within a pool is instant, but rolling to a new set had to generate
    it while the user waited -- about a second for outfits and over three for
    Discover, which runs a catalog search per look. Building it as soon as the
    current set is served means the next click is a cache hit too.
    """
    key = _cache_key(kind, user_id, weather, variant=variant, **kw)
    if _cache_get(key) is not None:
        return

    # Without this, paging through a pool fired a prefetch per click and three
    # threads raced to build the same variant, competing with the request the
    # user was waiting on.
    with _INFLIGHT_LOCK:
        if key in _INFLIGHT:
            return
        _INFLIGHT.add(key)

    def work():
        try:
            if kind == "outfits":
                from recommendation.outfit_suggest import suggest_outfits
                pool = suggest_outfits(user_id, weather=weather,
                                       count=POOL_SIZE, variant=variant)
            else:
                from recommendation.outfit_suggest import discover_additions
                pool = discover_additions(user_id, weather=weather, count=POOL_SIZE,
                                          max_new=kw.get("max_new", 2),
                                          gender=kw.get("gender") or None,
                                          variant=variant)
            if pool:
                _cache_put(key, pool)
        except Exception as e:
            print(f"⚠️  prefetch {kind} variant {variant}: {type(e).__name__}: {e}")
        finally:
            with _INFLIGHT_LOCK:
                _INFLIGHT.discard(key)

    threading.Thread(target=work, daemon=True,
                     name=f"prefetch-{kind}-{variant}").start()


def _slice(pool: list, count: int, offset: int) -> list:
    """Wrap around the pool so Refresh keeps returning something."""
    if not pool:
        return []
    n = len(pool)
    return [pool[(offset + i) % n] for i in range(min(count, n))]


def _cache_get(key):
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit and time.time() - hit[0] < _CACHE_TTL:
            return hit[1]
        if hit:
            _CACHE.pop(key, None)
    return None


def _cache_put(key, value):
    with _CACHE_LOCK:
        _CACHE[key] = (time.time(), value)
        if len(_CACHE) > 256:                  # bound it; this is a dev-scale cache
            oldest = sorted(_CACHE.items(), key=lambda kv: kv[1][0])[:64]
            for k, _ in oldest:
                _CACHE.pop(k, None)


def _get_user_id(req) -> int | None:
    auth = req.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    try:
        return jwt.decode(auth.split(" ")[1], JWT_SECRET, algorithms=["HS256"])["user_id"]
    except Exception:
        return None


def _weather_from(req) -> dict | None:
    lat, lon = req.args.get("lat"), req.args.get("lon")
    if lat is None or lon is None:
        return None
    try:
        return get_weather(float(lat), float(lon))
    except (TypeError, ValueError):
        return None


@suggestions_bp.route("/weather", methods=["GET"])
def weather_now():
    w = _weather_from(request)
    return jsonify({"weather": w}), 200


@suggestions_bp.route("/outfits", methods=["GET"])
def outfit_suggestions():
    user_id = _get_user_id(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401
    try:
        count = min(int(request.args.get("count", 6)), 12)
    except ValueError:
        count = 6
    try:
        offset = max(0, int(request.args.get("offset", 0)))
    except ValueError:
        offset = 0
    try:
        variant = max(0, int(request.args.get("variant", 0)))
    except ValueError:
        variant = 0

    w = _weather_from(request)
    key = _cache_key("outfits", user_id, w, variant=variant)
    pool = _cache_get(key)
    was_cached = pool is not None
    try:
        if pool is None:
            from recommendation.outfit_suggest import suggest_outfits
            pool = suggest_outfits(user_id, weather=w, count=POOL_SIZE, variant=variant)
            if pool:
                _cache_put(key, pool)
        # Every response, not only a freshly built one: gating this on a cache
        # miss meant the chain stopped after a single step, so rolling to set 3
        # had to build it while the page waited. _prefetch is a no-op when the
        # variant is already cached or already being built.
        _prefetch("outfits", user_id, w, variant + 1)
        return jsonify({
            "weather": w,
            "outfits": _slice(pool or [], count, offset),
            "total": len(pool or []),
            "offset": offset,
            "variant": variant,
            "cached": was_cached,
        }), 200
    except Exception as e:
        print(f"❌ /suggestions/outfits: {type(e).__name__}: {e}")
        return jsonify({"weather": w, "outfits": [], "total": 0, "error": "unavailable"}), 200


@suggestions_bp.route("/discover", methods=["GET"])
def discover():
    user_id = _get_user_id(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401
    try:
        count = min(int(request.args.get("count", 5)), 10)
    except ValueError:
        count = 5
    try:
        max_new = max(1, min(int(request.args.get("max_new", 2)), 2))
    except ValueError:
        max_new = 2
    gender = request.args.get("gender") or None
    try:
        offset = max(0, int(request.args.get("offset", 0)))
    except ValueError:
        offset = 0
    try:
        variant = max(0, int(request.args.get("variant", 0)))
    except ValueError:
        variant = 0

    w = _weather_from(request)
    key = _cache_key("discover", user_id, w, max_new=max_new,
                     gender=gender or "", variant=variant)
    pool = _cache_get(key)
    was_cached = pool is not None
    try:
        if pool is None:
            from recommendation.outfit_suggest import discover_additions
            pool = discover_additions(user_id, weather=w, count=POOL_SIZE,
                                      max_new=max_new, gender=gender, variant=variant)
            if pool:
                _cache_put(key, pool)
        _prefetch("discover", user_id, w, variant + 1,
                  max_new=max_new, gender=gender or "")
        return jsonify({
            "weather": w,
            "discover": _slice(pool or [], count, offset),
            "total": len(pool or []),
            "offset": offset,
            "variant": variant,
            "cached": was_cached,
        }), 200
    except Exception as e:
        print(f"❌ /suggestions/discover: {type(e).__name__}: {e}")
        return jsonify({"weather": w, "discover": [], "total": 0, "error": "unavailable"}), 200
