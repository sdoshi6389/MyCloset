"""
Main recommendation engine.

Closet mode: scores user's own items not yet in the outfit.
Catalog mode: CLIP text query → FAISS → scored catalog products.
"""
import os
import numpy as np
from db import get_supa
from .profile import get_user_profile
from .scorer import score_closet_candidate, score_catalog_candidate

# Which categories belong to each builder slot
SLOT_CATEGORIES: dict[str, list[str]] = {
    "inner_top":    ["Tops"],
    "inner_bottom": ["Bottoms"],
    "outer_top":    ["Outerwear"],
    "outer_bottom": ["Bottoms"],
    "left_shoe":    ["Shoes"],
    "right_shoe":   ["Shoes"],
    "hat":          ["Accessories"],
    "necklace":     ["Accessories"],
    "bracelet":     ["Accessories"],
    "bag":          ["Accessories"],
    "innerwear":    ["Innerwear"],
    "underwear":    ["Innerwear"],
}

# Human-readable slot → CLIP text keyword
SLOT_KEYWORDS: dict[str, str] = {
    "inner_top":    "shirt top",
    "inner_bottom": "pants trousers",
    "outer_top":    "jacket outerwear",
    "outer_bottom": "skirt",
    "left_shoe":    "shoes sneakers",
    "right_shoe":   "shoes sneakers",
    "hat":          "hat cap",
    "necklace":     "necklace chain",
    "bracelet":     "bracelet watch",
    "bag":          "bag",
    "innerwear":    "undershirt bra",
    "underwear":    "underwear boxers",
}

API_BASE = os.getenv("PUBLIC_BASE_URL", "http://localhost:5000")


def _parse_tags(s) -> list[str]:
    if not s:
        return []
    if isinstance(s, list):
        return [t.lower().strip() for t in s if t]
    return [t.strip().lower()
            for t in str(s).replace("[","").replace("]","").replace("'","").replace('"',"").split(",")
            if t.strip()]


def _format_closet_item(row: dict, user_id: int, score: float) -> dict:
    icon_path = row.get("icon_path")
    fname = os.path.basename(icon_path) if icon_path else None
    return {
        "id":         row["id"],
        "title":      row.get("matched_title") or row.get("caption") or row.get("type") or "Item",
        "brand":      row.get("brand"),
        "color":      row.get("color"),
        "category":   row.get("category"),
        "icon_url":   f"/icons/{fname}" if fname else None,
        "image_url":  f"/static/{user_id}/{row['filename']}",
        "price":      None,
        "shop_url":   None,
        "source":     "closet",
        "score":      score,
    }


def _format_catalog_item(hit: dict, score: float) -> dict:
    return {
        "id":        None,
        "title":     hit.get("title", ""),
        "brand":     hit.get("source", ""),
        "color":     hit.get("color", ""),
        "category":  None,
        "icon_url":  None,
        "image_url": hit.get("image", ""),
        "price":     hit.get("price"),
        "shop_url":  hit.get("url"),
        "source":    "catalog",
        "score":     score,
    }


def _build_text_query(slot: str, outfit_items: list[dict], profile: dict) -> str:
    vibes = []
    for item in outfit_items:
        vibes.extend(_parse_tags(item.get("vibe")))
        vibes.extend(_parse_tags(item.get("style")))

    # Add top user vibe
    vibe_w = profile.get("vibe_weights") or {}
    if vibe_w:
        top_user_vibe = max(vibe_w, key=lambda k: vibe_w[k])
        vibes.append(top_user_vibe)

    # Deduplicate and take top 2
    seen, unique = set(), []
    for v in vibes:
        if v not in seen:
            seen.add(v)
            unique.append(v)
    top_vibes = " ".join(unique[:2])

    slot_kw = SLOT_KEYWORDS.get(slot, "clothing item")
    return f"{top_vibes} {slot_kw}".strip()


def _fetch_item_meta(item_id: int) -> dict | None:
    """Fetch full metadata (including vector_embedding) for a placed outfit item."""
    supa = get_supa()
    res = supa.table("closet_items").select(
        "id, type, category, color, vibe, style, season, formality_score, occasion, vector_embedding"
    ).eq("id", item_id).execute()
    return res.data[0] if res.data else None


def _closet_candidates(user_id: int, slot: str, placed_ids: set[int]) -> list[dict]:
    categories = SLOT_CATEGORIES.get(slot, [])
    if not categories:
        return []
    supa = get_supa()
    res = supa.table("closet_items").select(
        "id, filename, matched_title, caption, type, category, color, vibe, style, "
        "season, formality_score, occasion, vector_embedding, icon_path, brand"
    ).eq("user_id", user_id).in_("category", categories).execute()

    return [r for r in (res.data or []) if r["id"] not in placed_ids]


def _catalog_candidates(slot: str, outfit_items: list[dict], profile: dict) -> list[dict]:
    from callable_embedding import encode_text
    from callable_faiss import search_similar_products

    query = _build_text_query(slot, outfit_items, profile)
    print(f"🔍 Catalog query for '{slot}': \"{query}\"")
    query_vec = encode_text(query)
    hits = search_similar_products(query_vec, brand=None)
    return hits  # each has: title, price, color, url, image, source, distance


def get_recommendations(
    user_id: int,
    outfit: dict,
    fill_slots: list[str] | None,
    mode: str = "closet",
    top_k: int = 5,
) -> dict:
    """
    outfit: { slot: { id, ... metadata ... } | None }
    fill_slots: list of slot ids to fill; None = all empty slots with known categories
    Returns: { "recommendations": { slot: [ { item, score, source } ] } }
    """
    # ── 1. Get user profile ────────────────────────────────────────────────
    profile = get_user_profile(user_id)

    # ── 2. Build outfit context: fetch full metadata for placed items ──────
    outfit_items: list[dict] = []
    placed_ids: set[int] = set()
    for slot, item in (outfit or {}).items():
        if item and item.get("id"):
            full = _fetch_item_meta(item["id"])
            if full:
                # Merge frontend metadata (has color, vibe, etc.) with DB record
                merged = {**item, **{k: v for k, v in full.items() if v is not None}}
                outfit_items.append(merged)
                placed_ids.add(item["id"])

    # ── 3. Determine which slots to fill ──────────────────────────────────
    if fill_slots is None:
        fill_slots = [
            s for s, item in (outfit or {}).items()
            if not item and s in SLOT_CATEGORIES
        ]

    results: dict[str, list] = {}

    for slot in fill_slots:
        if mode == "closet":
            candidates = _closet_candidates(user_id, slot, placed_ids)
            scored = []
            for c in candidates:
                score = score_closet_candidate(c, outfit_items, profile)
                scored.append(_format_closet_item(c, user_id, score))

        else:  # catalog
            raw_hits = _catalog_candidates(slot, outfit_items, profile)
            scored = []
            for hit in raw_hits:
                score = score_catalog_candidate(hit, outfit_items, hit.get("distance", 1.0))
                scored.append(_format_catalog_item(hit, score))

        scored.sort(key=lambda x: -x["score"])
        results[slot] = scored[:top_k]

    return {"recommendations": results}
