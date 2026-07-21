"""
Main recommendation engine — upgraded to 7-factor scoring + MMR diversity.

Closet mode : scores user's own items not yet in the outfit.
Catalog mode: CLIP text query → FAISS (250 candidates) → scored → MMR top-k.
"""
import os
import re
import numpy as np
from db import get_supa
from .profile import get_user_profile
from .scorer import score_candidate, enrich_catalog_item, _parse_vector
from .explanations import generate_reason
from .rec_logging import log_recommendations

# ── Slot → DB category mapping ────────────────────────────────────────────────
SLOT_CATEGORIES: dict[str, list[str]] = {
    "inner_top":    ["Tops"],
    "inner_bottom": ["Bottoms"],
    "outer_top":    ["Outerwear"],
    "outer_bottom": ["Bottoms"],
    "shorts":       ["Bottoms"],
    "left_shoe":    ["Shoes"],
    "right_shoe":   ["Shoes"],
    "hat":          ["Accessories"],
    "necklace":     ["Accessories"],
    "bracelet":     ["Accessories"],
    "bag":          ["Accessories"],
    "innerwear":    ["Innerwear"],
    "underwear":    ["Innerwear"],
}

# CLIP text hint per slot — used to build the FAISS query embedding
SLOT_KEYWORDS: dict[str, str] = {
    "inner_top":    "shirt top",
    "inner_bottom": "pants trousers",
    "outer_top":    "jacket outerwear",
    "outer_bottom": "skirt",
    "shorts":       "shorts",
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

# Slots that share a DB category with at least one other slot — need zone-level filter
_SHARED_CATEGORY_SLOTS = {
    "hat", "necklace", "bracelet", "bag",
    "innerwear", "underwear",
    "inner_bottom", "outer_bottom", "shorts",
}

# Candidate pool size for FAISS catalog retrieval
FAISS_POOL_K = 250


# ── Slot inference (mirrors frontend inferZone) ───────────────────────────────
def _infer_slot(item: dict) -> str | None:
    text = " ".join(filter(None, [
        item.get("matched_title"), item.get("type"), item.get("caption"),
        item.get("category"), item.get("subcategory"),
    ])).lower()

    if re.search(r"\b(hat|cap|beanie|beret|visor|snapback|fedora|bucket hat|trucker|baseball cap|toboggan)\b", text): return "hat"
    if re.search(r"\b(glasses|sunglasses|shades|eyewear|frames|specs)\b", text): return "hat"
    if re.search(r"\b(necklace|chain|choker|pendant|locket|collar chain)\b", text): return "necklace"
    if re.search(r"\b(scarf|bandana)\b", text): return "necklace"
    if re.search(r"\b(bracelet|bangle|cuff|watch|wristband|wristwatch|arm candy)\b", text): return "bracelet"
    if re.search(r"\b(bag|purse|handbag|clutch|backpack|tote|satchel|crossbody|fanny pack|shoulder bag|mini bag)\b", text): return "bag"
    if re.search(r"\b(jacket|coat|blazer|puffer|windbreaker|trench|parka|overcoat|raincoat|bomber|denim jacket|leather jacket|varsity)\b", text): return "outer_top"
    if re.search(r"\b(hoodie|zip.?up|fleece)\b", text) and "shirt" not in text: return "outer_top"
    if re.search(r"\b(bralette|sports.?bra|camisole|cami|undershirt|base.?layer|thermal|bodysuit|lingerie)\b", text): return "innerwear"
    if re.search(r"\bbra\b", text) and not re.search(r"\b(bracelet|bangle)\b", text): return "innerwear"
    if re.search(r"\btank\b", text) and re.search(r"\b(top|under|inner)\b", text): return "innerwear"
    if re.search(r"\b(boxers|briefs|boxer.?briefs|underwear)\b", text): return "underwear"
    if re.search(r"\b(shirt|tee|t-shirt|blouse|knit|sweater|pullover|sweatshirt|jersey|crop|cardigan|polo|tank|tube top)\b", text): return "inner_top"
    if re.search(r"\bhoodie\b", text): return "inner_top"
    if re.search(r"\btop\b", text) and not re.search(r"(jacket|coat|outer)", text): return "inner_top"
    if re.search(r"\bshorts?\b", text): return "shorts"
    if re.search(r"\b(pants|jeans|trousers|chinos|slacks|legging|jogger|sweatpant|cargo|denim)\b", text): return "inner_bottom"
    if re.search(r"\b(skirt|mini|midi|maxi|culottes)\b", text): return "outer_bottom"
    if re.search(r"\b(shoe|sneaker|boot|loafer|sandal|heel|flat|pump|oxford|mule|slipper|clog|kicks)\b", text): return "left_shoe"
    if re.search(r"\b(sock|stocking|tight|anklet)\b", text): return "left_sock"

    t = (item.get("type") or "").lower()
    c = (item.get("category") or "").lower()
    if "outerwear" in t or "outerwear" in c: return "outer_top"
    if t == "top"    or c == "top":          return "inner_top"
    if t == "bottom" or c == "bottom":       return "inner_bottom"
    if "shoe" in t or "footwear" in t:       return "left_shoe"
    if "hat" in t or "headwear" in t:        return "hat"
    if c == "innerwear":                     return "innerwear"
    if c == "underwear":                     return "underwear"
    return None


def _parse_tags(s) -> list[str]:
    if not s:
        return []
    if isinstance(s, list):
        return [t.lower().strip() for t in s if t]
    return [t.strip().lower()
            for t in str(s).replace("[","").replace("]","").replace("'","").replace('"',"").split(",")
            if t.strip()]


# ── Output formatters ─────────────────────────────────────────────────────────
def _format_closet_item(row: dict, user_id: int, scored: dict, reason: str) -> dict:
    icon_path = row.get("icon_path")
    fname = os.path.basename(icon_path) if icon_path else None
    return {
        "id":              row["id"],
        "title":           row.get("matched_title") or row.get("caption") or row.get("type") or "Item",
        "brand":           row.get("brand"),
        "color":           row.get("color"),
        "category":        row.get("category"),
        "icon_url":        f"/icons/{fname}" if fname else None,
        "image_url":       f"/static/{user_id}/{row['filename']}",
        "price":           None,
        "shop_url":        None,
        "source":          "closet",
        "score":           scored["total"],
        "score_breakdown": scored["breakdown"],
        "reason":          reason,
    }


def _format_catalog_item(hit: dict, scored: dict, reason: str) -> dict:
    return {
        "id":              None,
        "title":           hit.get("title", ""),
        "brand":           hit.get("source", ""),
        "color":           hit.get("color", ""),
        "category":        None,
        "icon_url":        None,
        "image_url":       hit.get("image", ""),
        "price":           hit.get("price"),
        "shop_url":        hit.get("url"),
        "source":          "catalog",
        "score":           scored["total"],
        "score_breakdown": scored["breakdown"],
        "reason":          reason,
    }


# ── FAISS text query builder ──────────────────────────────────────────────────
def _build_text_query(slot: str, outfit_items: list[dict], profile: dict) -> str:
    vibes = []
    for item in outfit_items:
        vibes.extend(_parse_tags(item.get("vibe")))
        vibes.extend(_parse_tags(item.get("style")))
    vibe_w = profile.get("vibe_weights") or {}
    if vibe_w:
        vibes.append(max(vibe_w, key=lambda k: vibe_w[k]))
    seen, unique = set(), []
    for v in vibes:
        if v not in seen:
            seen.add(v)
            unique.append(v)
    return f"{' '.join(unique[:2])} {SLOT_KEYWORDS.get(slot, 'clothing item')}".strip()


# ── DB helpers ────────────────────────────────────────────────────────────────
def _fetch_item_meta(item_id: int) -> dict | None:
    supa = get_supa()
    res = supa.table("closet_items").select(
        "id, type, matched_title, category, color, vibe, style, season, formality_score, "
        "occasion, vector_embedding"
    ).eq("id", item_id).execute()
    return res.data[0] if res.data else None


def _closet_candidates(user_id: int, slot: str, placed_ids: set[int], gender: str | None = None) -> list[dict]:
    categories = SLOT_CATEGORIES.get(slot, [])
    if not categories:
        return []
    supa = get_supa()
    q = supa.table("closet_items").select(
        "id, filename, matched_title, caption, type, category, subcategory, "
        "color, vibe, style, season, formality_score, occasion, "
        "vector_embedding, icon_path, brand, gender"
    ).eq("user_id", user_id).in_("category", categories)
    res = q.execute()

    all_rows   = res.data or []
    candidates = [r for r in all_rows if r["id"] not in placed_ids]
    after_placed = len(candidates)

    # Gender filter: exclude only items explicitly tagged as the opposite gender.
    # GPT-4o returns freeform values ("male", "men's", "unisex", etc.) so a strict
    # equality check against "mens"/"womens" silently drops most closet items.
    if gender:
        _MENS_VALS   = {"mens", "men's", "men", "male", "boys", "boy"}
        _WOMENS_VALS = {"womens", "women's", "women", "female", "girls", "girl", "ladies"}
        opposite = _WOMENS_VALS if gender == "mens" else _MENS_VALS
        candidates = [
            c for c in candidates
            if not c.get("gender") or c.get("gender").lower().strip() not in opposite
        ]

    print(f"🗄  closet slot={slot} db={len(all_rows)} "
          f"→placed={after_placed} →gender={len(candidates)}", end="")
    if slot in _SHARED_CATEGORY_SLOTS:
        filtered = [c for c in candidates if _infer_slot(c) == slot]
        print(f" →infer={len(filtered)}")
        return filtered
    print()
    return candidates


def _catalog_candidates(slot: str, outfit_items: list[dict], profile: dict, gender: str | None = None) -> list[dict]:
    from callable_embedding import encode_text
    from callable_faiss import search_similar_products

    query = _build_text_query(slot, outfit_items, profile)
    print(f"🔍 Catalog query for '{slot}': \"{query}\" gender={gender}")
    query_vec = encode_text(query)
    hits = search_similar_products(query_vec, brand=None, top_k=FAISS_POOL_K, gender=gender)

    filtered = [
        h for h in hits
        if _infer_slot({
            "matched_title": h.get("title", ""),
            "type": "", "category": "", "subcategory": ""
        }) == slot
    ]
    return filtered


# ── MMR diversity selection ───────────────────────────────────────────────────
def _mmr_select(
    scored_candidates: list[dict],
    top_k: int,
    lambda_: float = 0.6,
) -> list[dict]:
    """
    Maximum Marginal Relevance — balance relevance and diversity.
    lambda_=1.0 → pure relevance ranking; 0.0 → pure diversity.
    Uses the score_breakdown vectors (or raw scores) as the feature representation.
    """
    if len(scored_candidates) <= top_k:
        return scored_candidates

    def _vec(item: dict) -> np.ndarray:
        bd = item.get("score_breakdown") or {}
        keys = ["outfit_compatibility", "color_harmony", "vibe_match",
                "user_preference", "formality_match", "category_pairing", "novelty"]
        return np.array([bd.get(k, 0.5) for k in keys], dtype=np.float32)

    def _cos(a: np.ndarray, b: np.ndarray) -> float:
        na, nb = np.linalg.norm(a), np.linalg.norm(b)
        return float(np.dot(a, b) / (na * nb)) if na > 1e-8 and nb > 1e-8 else 0.0

    remaining = list(scored_candidates)
    selected  = []

    # First pick: highest relevance score
    best = max(remaining, key=lambda x: x.get("score", 0))
    selected.append(best)
    remaining.remove(best)

    while len(selected) < top_k and remaining:
        sel_vecs = [_vec(s) for s in selected]
        best_val, best_item = -1e9, None
        for item in remaining:
            v   = _vec(item)
            rel = item.get("score", 0)
            max_sim = max(_cos(v, sv) for sv in sel_vecs)
            mmr_val = lambda_ * rel - (1 - lambda_) * max_sim
            if mmr_val > best_val:
                best_val, best_item = mmr_val, item
        selected.append(best_item)
        remaining.remove(best_item)

    return selected


# ── Main entry point ──────────────────────────────────────────────────────────
def get_recommendations(
    user_id: int,
    outfit: dict,
    fill_slots: list[str] | None,
    mode: str = "closet",
    top_k: int = 5,
    gender: str | None = None,
) -> dict:
    """
    outfit: { slot: { id, ... metadata ... } | None }
    fill_slots: list of slot ids to fill; None = all empty slots with known categories
    mode: "closet" | "catalog"
    Returns: { "recommendations": { slot: [ item_dict ] } }

    Each item dict includes: id, title, brand, color, icon_url, image_url,
    price, shop_url, source, score, score_breakdown, reason.
    """
    profile = get_user_profile(user_id)

    # Normalise frontend "male"/"female" → DB/FAISS "mens"/"womens"
    _GENDER_MAP = {"male": "mens", "female": "womens", "mens": "mens", "womens": "womens"}
    gender = _GENDER_MAP.get(gender) if gender else None

    # ── Build outfit context ───────────────────────────────────────────────
    outfit_items: list[dict] = []
    placed_ids: set[int] = set()
    for slot, item in (outfit or {}).items():
        if item and item.get("id"):
            full = _fetch_item_meta(item["id"])
            if full:
                merged = {**item, **{k: v for k, v in full.items() if v is not None}}
                outfit_items.append(merged)
                placed_ids.add(item["id"])

    filled_slots = set(s for s, item in (outfit or {}).items() if item)

    # ── Determine which slots need recommendations ─────────────────────────
    if fill_slots is None:
        fill_slots = [
            s for s, item in (outfit or {}).items()
            if not item and s in SLOT_CATEGORIES
        ]

    # ── Bottom conflict rules ──────────────────────────────────────────────
    # Placed bottom type → blocked rec slots:
    #   pants (inner_bottom) → no shorts or skirt recs
    #   shorts               → no pants recs
    #   skirt (outer_bottom) → no pants or shorts recs
    bottom_types_placed = {
        _infer_slot(item)
        for item in outfit_items
        if _infer_slot(item) in ("inner_bottom", "shorts", "outer_bottom")
    }
    if bottom_types_placed:
        _bottom_excl: set[str] = set()
        if "inner_bottom" in bottom_types_placed:
            _bottom_excl.update(("outer_bottom", "shorts"))
        if "shorts" in bottom_types_placed:
            _bottom_excl.add("inner_bottom")
        if "outer_bottom" in bottom_types_placed:
            _bottom_excl.update(("inner_bottom", "shorts"))
        if _bottom_excl:
            fill_slots = [s for s in fill_slots if s not in _bottom_excl]
            print(f"🔒 Bottom conflict: placed={bottom_types_placed} → excluded={_bottom_excl}")

    results: dict[str, list] = {}

    for slot in fill_slots:
        if mode == "closet":
            raw_candidates = _closet_candidates(user_id, slot, placed_ids, gender=gender)
            scored_list = []
            for c in raw_candidates:
                result = score_candidate(
                    candidate=c,
                    outfit_items=outfit_items,
                    profile=profile,
                    target_slot=slot,
                    filled_slots=filled_slots,
                )
                reason = generate_reason(result["breakdown"], c, outfit_items, slot)
                formatted = _format_closet_item(c, user_id, result, reason)
                scored_list.append(formatted)

        else:  # catalog
            raw_hits = _catalog_candidates(slot, outfit_items, profile, gender=gender)
            scored_list = []
            for hit in raw_hits:
                enriched = enrich_catalog_item(hit)
                result = score_candidate(
                    candidate=enriched,
                    outfit_items=outfit_items,
                    profile=profile,
                    target_slot=slot,
                    filled_slots=filled_slots,
                    faiss_distance=hit.get("distance", 1.0),
                )
                reason = generate_reason(result["breakdown"], enriched, outfit_items, slot)
                formatted = _format_catalog_item(enriched, result, reason)
                scored_list.append(formatted)

        # Sort by total score descending
        scored_list.sort(key=lambda x: -x["score"])

        # Apply MMR diversity to final top-k
        final = _mmr_select(scored_list, top_k=top_k, lambda_=0.65)

        results[slot] = final

        # Log impressions (non-blocking)
        try:
            outfit_ctx = {
                "filled_slots": list(filled_slots),
                "mode": mode,
                "item_count": len(outfit_items),
            }
            log_recommendations(user_id, slot, outfit_ctx, final)
        except Exception as e:
            print(f"⚠️  log_recommendations failed silently: {e}")

    return {"recommendations": results}
