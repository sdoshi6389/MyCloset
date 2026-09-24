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


def _blend(base: float, weather_fit: float) -> float:
    return base * (1 - WEATHER_WEIGHT) + weather_fit * WEATHER_WEIGHT


def _best_for_slot(slot: str, pool: list[dict], chosen: list[dict],
                   profile: dict, weather: dict | None,
                   used: set[int], exclude_score_below: float = 0.0):
    """Highest-scoring unused item for a slot, given what is already chosen."""
    best, best_score = None, -1.0
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
        total = _blend(scored["total"], season_fit(cand, weather))
        if total > best_score:
            best, best_score = cand, total
    if best is None or best_score < exclude_score_below:
        return None, 0.0
    return best, best_score


def suggest_outfits(user_id: int, weather: dict | None = None,
                    count: int = 6, seed: int | None = None) -> list[dict[str, Any]]:
    """Complete looks assembled from the user's closet, best first."""
    profile = get_user_profile(user_id)
    by_slot = _closet_by_slot(user_id)
    tops = by_slot.get("inner_top") or []
    if not tops or not by_slot.get("inner_bottom"):
        return []

    rng = random.Random(seed)
    # Seed each look with a different top so the set is varied rather than six
    # versions of the same shirt.
    seeds = sorted(tops, key=lambda t: season_fit(t, weather), reverse=True)
    if len(seeds) > count * 2:
        head = seeds[: count]
        tail = rng.sample(seeds[count:], min(count, len(seeds) - count))
        seeds = head + tail

    looks = []
    for top in seeds[: count * 2]:
        used = {top["id"]}
        top = {**top, "_slot": "inner_top"}
        chosen = [top]
        parts = {"inner_top": top}
        score_sum = _blend(0.5, season_fit(top, weather))
        n = 1

        for slot in CORE_SLOTS[1:]:
            pick, sc = _best_for_slot(slot, by_slot.get(slot, []), chosen,
                                      profile, weather, used)
            if pick:
                pick = {**pick, "_slot": slot}
                used.add(pick["id"]); chosen.append(pick)
                parts[slot] = pick; score_sum += sc; n += 1

        if len(parts) < 2:
            continue

        # Outerwear only when the temperature actually calls for a layer.
        if weather and weather.get("layers", 1) >= 2:
            pick, sc = _best_for_slot("outer_top", by_slot.get("outer_top", []),
                                      chosen, profile, weather, used)
            if pick:
                pick = {**pick, "_slot": "outer_top"}
                used.add(pick["id"]); chosen.append(pick)
                parts["outer_top"] = pick; score_sum += sc; n += 1

        # One accessory, if a good one exists.
        for slot in ("hat", "bag", "necklace", "bracelet"):
            pool = by_slot.get(slot) or []
            if not pool:
                continue
            pick, sc = _best_for_slot(slot, pool, chosen, profile, weather, used,
                                      exclude_score_below=0.45)
            if pick:
                pick = {**pick, "_slot": slot}
                used.add(pick["id"]); chosen.append(pick)
                parts[slot] = pick; score_sum += sc; n += 1
                break

        looks.append({
            "score": round(score_sum / max(n, 1), 4),
            "weather_fit": round(
                sum(season_fit(p, weather) for p in parts.values()) / len(parts), 3),
            "items": {
                slot: _format_closet_item(it, user_id, {"total": 0, "breakdown": {}}, "")
                for slot, it in parts.items()
            },
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
    return f"{lead} — {', '.join(kinds)}" if kinds else lead


# ── Discover: an existing look plus one or two catalog pieces ────────────────
def discover_additions(user_id: int, weather: dict | None = None,
                       count: int = 6, max_new: int = 2,
                       gender: str | None = None) -> list[dict[str, Any]]:
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

    if not base_looks:
        for L in suggest_outfits(user_id, weather=weather, count=count):
            parts = {}
            for slot, formatted in L["items"].items():
                if formatted.get("id"):
                    parts[slot] = {"id": formatted["id"], **formatted}
            if parts:
                base_looks.append({"name": None, "outfit_id": None, "parts": parts})

    # Slots worth shopping for, in the order they tend to complete a look.
    WISH = ["outer_top", "left_shoe", "bag", "hat", "necklace", "bracelet"]

    out = []
    for look in base_looks[:count]:
        have = set(look["parts"])
        wants = [s for s in WISH if s not in have][:max_new]
        if not wants:
            continue
        outfit_arg = {slot: {"id": row["id"]} for slot, row in look["parts"].items()
                      if row.get("id")}
        try:
            res = get_recommendations(
                user_id=user_id, outfit=outfit_arg, fill_slots=wants,
                mode="catalog", top_k=3, gender=gender,
            )
        except Exception as e:
            print(f"⚠️  discover: recommendation failed: {type(e).__name__}: {e}")
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
            "base": {slot: _format_closet_item(row, user_id, {"total": 0, "breakdown": {}}, "")
                     for slot, row in look["parts"].items() if row.get("filename")},
            "additions": additions,
            "reason": (f"Pairs with {look['name']}" if look["name"] else "Completes this look")
                      + (f" · {weather['label']}" if weather else ""),
        })
    return out
