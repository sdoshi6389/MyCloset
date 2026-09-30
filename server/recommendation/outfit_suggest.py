"""Whole-outfit suggestions built from a user's own closet.

The recommender already scores one candidate against a partly-filled outfit.
This assembles complete looks instead: pick a base top, then greedily add the
piece that best fits what is already chosen, so the parts are scored against
each other rather than against a fixed template.

Weather steers the result rather than filtering it -- a garment that is wrong
for the temperature is pushed down, never removed, because wanting to wear a
particular jacket is a legitimate reason to ignore the forecast.
"""
from __future__ import annotations

import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from db import get_supa
from weather import season_fit
from .engine import _infer_slot, _format_closet_item
from .profile import get_user_profile
from .scorer import score_candidate

# A look needs these to read as an outfit at all.
CORE_SLOTS = ["inner_top", "inner_bottom", "left_shoe"]
# Added when the weather or the look calls for them.
EXTRA_SLOTS = ["outer_top", "hat", "bag", "necklace", "bracelet"]

WEATHER_WEIGHT = 0.30      # share of the final score owned by weather fit


def _closet_by_slot(user_id: int) -> dict[str, list[dict]]:
    rows = (get_supa().table("closet_items")
            .select("*").eq("user_id", user_id).execute().data) or []
    out: dict[str, list[dict]] = {}
    for r in rows:
        slot = _infer_slot(r)
        if slot == "shorts":
            slot = "inner_bottom"          # shorts fill the bottom slot
        if slot:
            out.setdefault(slot, []).append(r)
    return out


LAUNDRY_PENALTY = 0.55     # multiplier, not a filter


def _blend(base: float, weather_fit: float, item: dict | None = None) -> float:
    score = base * (1 - WEATHER_WEIGHT) + weather_fit * WEATHER_WEIGHT
    if item is not None and item.get("in_laundry"):
        # Heavy enough that a clean alternative almost always wins, light
        # enough that a closet mid-wash still returns something.
        score *= LAUNDRY_PENALTY
    return score


def _best_for_slot(slot: str, pool: list[dict], chosen: list[dict],
                   profile: dict, weather: dict | None,
                   used: set[int], exclude_score_below: float = 0.0,
                   variant: int = 0):
    """Best unused item for a slot, or the variant-th best.

    Always taking the single top scorer made the whole thing deterministic: a
    given top produced exactly one outfit, so asking for more looks returned the
    same ones. Stepping down the ranking gives genuinely different combinations
    that are still the good end of the list.
    """
    ranked: list[tuple[float, dict]] = []
    for cand in pool:
        if cand["id"] in used:
            continue
        try:
            scored = score_candidate(
                candidate=cand, outfit_items=chosen, profile=profile,
                target_slot=slot, filled_slots={c["_slot"] for c in chosen},
            )
        except Exception:
            continue
        ranked.append((_blend(scored["total"], season_fit(cand, weather), cand), cand))

    if not ranked:
        return None, 0.0
    ranked.sort(key=lambda r: -r[0])
    # Variant 0 is always the best pick. After that, choose among the top few at
    # random but deterministically, seeded on the variant and the slot. Stepping
    # by an index instead collided badly -- with a window of four, variant 2 at
    # step 2 landed back on the best item, so whole sets repeated.
    if variant:
        window = min(len(ranked), 5)
        rng = random.Random((variant * 1000003) ^ (hash(slot) & 0xFFFF))
        idx = rng.randrange(window)
    else:
        idx = 0
    best_score, best = ranked[idx]
    if best_score < exclude_score_below:
        return None, 0.0
    return best, best_score


_LOOK_MEMO: dict[tuple, tuple[float, list]] = {}
_LOOK_MEMO_TTL = 300
_LOOK_MEMO_LOCK = threading.Lock()


def _memo_key(user_id: int, weather: dict | None, count: int, variant: int = 0) -> tuple:
    w = weather or {}
    return (user_id, w.get("season"), w.get("layers"), count, variant)


def suggest_outfits(user_id: int, weather: dict | None = None,
                    count: int = 6, seed: int | None = None,
                    variant: int = 0) -> list[dict[str, Any]]:
    """Complete looks assembled from the user's closet, best first.

    Memoised briefly: the recommendations page asks for outfits and Discover at
    the same moment, and Discover assembles its base looks the same way.
    """
    if seed is None:                      # a caller asking for a specific seed
        key = _memo_key(user_id, weather, count, variant)  # wants fresh randomness
        with _LOOK_MEMO_LOCK:
            hit = _LOOK_MEMO.get(key)
            if hit and time.time() - hit[0] < _LOOK_MEMO_TTL:
                return hit[1]
        looks = _suggest_outfits_uncached(user_id, weather, count, seed, variant)
        if looks:
            with _LOOK_MEMO_LOCK:
                _LOOK_MEMO[key] = (time.time(), looks)
                if len(_LOOK_MEMO) > 128:
                    for k, _ in sorted(_LOOK_MEMO.items(), key=lambda kv: kv[1][0])[:32]:
                        _LOOK_MEMO.pop(k, None)
        return looks
    return _suggest_outfits_uncached(user_id, weather, count, seed, variant)


def _suggest_outfits_uncached(user_id: int, weather: dict | None = None,
                              count: int = 6, seed: int | None = None,
                              variant: int = 0) -> list[dict[str, Any]]:
    profile = get_user_profile(user_id)
    by_slot = _closet_by_slot(user_id)
    tops = by_slot.get("inner_top") or []
    if not tops or not by_slot.get("inner_bottom"):
        return []

    rng = random.Random(seed)
    # Seed each look with a different top so the set is varied rather than six
    # versions of the same shirt.
    seeds = sorted(
        tops,
        key=lambda t: (
            -season_fit(t, weather),
            bool(t.get("in_laundry")),      # clean first
            t.get("wear_count") or 0,       # then least-worn, for variety
        ),
    )
    if len(seeds) > count * 2:
        head = seeds[: count]
        tail = rng.sample(seeds[count:], min(count, len(seeds) - count))
        seeds = head + tail

    if variant and seeds:
        # Shuffle rather than rotate: rotating showed the same looks in a
        # different order once dedup-by-top collapsed them again.
        rng2 = random.Random(variant * 7919)
        seeds = list(seeds)
        rng2.shuffle(seeds)

    looks = []
    for top in seeds[: count * 2]:
        used = {top["id"]}
        top = {**top, "_slot": "inner_top"}
        chosen = [top]
        parts = {"inner_top": top}
        score_sum = _blend(0.5, season_fit(top, weather), top)
        n = 1

        for slot in CORE_SLOTS[1:]:
            pick, sc = _best_for_slot(slot, by_slot.get(slot, []), chosen,
                                      profile, weather, used, variant=variant)
            if pick:
                pick = {**pick, "_slot": slot}
                used.add(pick["id"]); chosen.append(pick)
                parts[slot] = pick; score_sum += sc; n += 1

        if len(parts) < 2:
            continue

        # Outerwear only when the temperature actually calls for a layer.
        if weather and weather.get("layers", 1) >= 2:
            pick, sc = _best_for_slot("outer_top", by_slot.get("outer_top", []),
                                      chosen, profile, weather, used, variant=variant)
            if pick:
                pick = {**pick, "_slot": "outer_top"}
                used.add(pick["id"]); chosen.append(pick)
                parts["outer_top"] = pick; score_sum += sc; n += 1

        # Accessories are collected but kept out of the outfit's own score, so a
        # look is judged on the clothes and the extras stay optional.
        accessories: dict[str, dict] = {}
        for slot in ("hat", "necklace", "bag", "bracelet"):
            pool = by_slot.get(slot) or []
            if not pool:
                continue
            pick, _sc = _best_for_slot(slot, pool, chosen, profile, weather, used,
                                       exclude_score_below=0.40, variant=variant)
            if pick:
                pick = {**pick, "_slot": slot}
                used.add(pick["id"])
                accessories[slot] = pick

        def fmt(it):
            out = _format_closet_item(it, user_id, {"total": 0, "breakdown": {}}, "")
            out["in_laundry"] = bool(it.get("in_laundry"))
            out["wear_count"] = it.get("wear_count") or 0
            return out
        looks.append({
            "score": round(score_sum / max(n, 1), 4),
            "weather_fit": round(
                sum(season_fit(p, weather) for p in parts.values()) / len(parts), 3),
            # The outfit proper: what the card shows by default.
            "items": {slot: fmt(it) for slot, it in parts.items()},
            # Held back until asked for.
            "accessories": {slot: fmt(it) for slot, it in accessories.items()},
            "reason": _reason(parts, weather),
        })

    looks.sort(key=lambda L: L["score"], reverse=True)
    # Never open with two looks built on the same top.
    seen_tops, deduped = set(), []
    for L in looks:
        tid = (L["items"].get("inner_top") or {}).get("id")
        if tid in seen_tops:
            continue
        seen_tops.add(tid); deduped.append(L)
    return deduped[:count]


def _reason(parts: dict, weather: dict | None) -> str:
    if weather:
        lead = f"For {weather['label']}"
        if weather.get("is_wet"):
            lead += ", and it's wet out"
        elif weather.get("layers", 1) >= 3:
            lead += ", so layer up"
    else:
        lead = "From your closet"
    kinds = [p.get("subcategory") or p.get("type") or "" for p in parts.values()]
    kinds = [k for k in kinds if k][:3]
    text = f"{lead} — {', '.join(kinds)}" if kinds else lead
    washing = sum(1 for p in parts.values() if p.get("in_laundry"))
    if washing:
        text += f" · {washing} piece{'s' if washing > 1 else ''} may be in the wash"
    return text


# ── Discover: an existing look plus one or two catalog pieces ────────────────
def discover_additions(user_id: int, weather: dict | None = None,
                       count: int = 6, max_new: int = 2,
                       gender: str | None = None,
                       variant: int = 0) -> list[dict[str, Any]]:
    """Saved outfits with catalog pieces that would complete them.

    Works from saved looks first, since those are outfits the user actually
    built and so carry real signal, and falls back to generated ones when there
    are none saved yet.
    """
    from .engine import get_recommendations

    supa = get_supa()
    base_looks: list[dict] = []

    # Outfit pieces live in outfit_items, not on the outfit row.
    saved = (supa.table("outfits").select("id, name")
             .eq("user_id", user_id).order("id", desc=True).limit(count).execute().data) or []
    if not saved:
        saved = []
    outfit_ids = [o["id"] for o in saved]
    rows_by_outfit: dict[int, list[dict]] = {}
    meta: dict[int, dict] = {}
    if outfit_ids:
        entries = (supa.table("outfit_items")
                   .select("outfit_id, closet_item_id, slot")
                   .in_("outfit_id", outfit_ids).execute().data) or []
        for e in entries:
            rows_by_outfit.setdefault(e["outfit_id"], []).append(e)
        item_ids = list({e["closet_item_id"] for e in entries if e.get("closet_item_id")})
        if item_ids:
            rows = (supa.table("closet_items").select("*")
                    .in_("id", item_ids).execute().data) or []
            meta = {r["id"]: r for r in rows}

    for o in saved:
        parts: dict[str, dict] = {}
        for entry in rows_by_outfit.get(o["id"], []):
            row = meta.get(entry.get("closet_item_id"))
            if not row:
                continue
            slot = entry.get("slot") or _infer_slot(row)
            if slot:
                parts[slot] = row
        if len(parts) >= 2:
            base_looks.append({"name": o.get("name"), "outfit_id": o.get("id"), "parts": parts})

    # Saved looks carry the strongest signal, but a page made entirely of them is
    # a list of things you have already worn. At most half the slots go to saved
    # outfits so the rest can be looks the generator built, and the two are
    # interleaved below so the section reads as a feed rather than two blocks.
    keep_saved = max(1, count // 2)
    if len(base_looks) > keep_saved:
        base_looks = base_looks[:keep_saved]

    saved_count = len(base_looks)
    if saved_count < count:
        for L in suggest_outfits(user_id, weather=weather,
                                 count=count - saved_count, variant=variant):
            parts = {}
            for slot, formatted in L["items"].items():
                if formatted.get("id"):
                    parts[slot] = {"id": formatted["id"], **formatted}
            if len(parts) >= 2:
                base_looks.append({"name": None, "outfit_id": None, "parts": parts})

    # Slots worth shopping for, in the order they tend to complete a look.
    WISH = ["outer_top", "left_shoe", "bag", "hat", "necklace", "bracelet"]

    # One catalog search per look, run together rather than one after another.
    # Each is a CLIP encode plus a FAISS query -- both release the GIL, so this
    # turns a cost that grew with the number of looks into roughly the cost of
    # the slowest one.
    def _fetch(look):
        have = set(look["parts"])
        wants = [sl for sl in WISH if sl not in have][:max_new]
        if not wants:
            return look, None, []
        outfit_arg = {slot: {"id": row["id"]} for slot, row in look["parts"].items()
                      if row.get("id")}
        try:
            res = get_recommendations(
                user_id=user_id, outfit=outfit_arg, fill_slots=wants,
                mode="catalog", top_k=3, gender=gender,
            )
        except Exception as e:
            print(f"⚠️  discover: recommendation failed: {type(e).__name__}: {e}")
            return look, None, wants
        return look, res, wants

    todo = base_looks[:count]
    results = []
    if todo:
        # A pool of 12 looks means 12 catalog searches; four at a time left the
        # rest queued behind them for seconds.
        with ThreadPoolExecutor(max_workers=min(8, len(todo))) as ex:
            results = list(ex.map(_fetch, todo))

    out = []
    for look, res, wants in results:
        if res is None:
            continue

        additions = []
        for slot in wants:
            picks = (res.get("recommendations") or {}).get(slot) or []
            if not picks:
                continue
            best = picks[0]
            if weather:
                # A catalog hit has no season tag, so lean on the slot: pushing
                # outerwear in warm weather is the main thing to avoid.
                if slot == "outer_top" and weather.get("layers", 1) < 2:
                    continue
            additions.append({"slot": slot, "item": best})
        if not additions:
            continue

        out.append({
            "outfit_id": look["outfit_id"],
            "name": look["name"] or "Your look",
            "base": {
                slot: (_format_closet_item(row, user_id, {"total": 0, "breakdown": {}}, "")
                       if row.get("filename") else row)
                for slot, row in look["parts"].items()
            },
            "additions": additions,
            "reason": (f"Pairs with {look['name']}" if look["name"]
                       else "A look from your closet, finished off")
                      + (f" · {weather['label']}" if weather else ""),
            "from_saved": bool(look["outfit_id"]),
        })

    # Alternate the two kinds instead of listing all the saved ones first.
    saved = [o for o in out if o["from_saved"]]
    fresh = [o for o in out if not o["from_saved"]]
    mixed = []
    while saved or fresh:
        if fresh:
            mixed.append(fresh.pop(0))
        if saved:
            mixed.append(saved.pop(0))
    return mixed
