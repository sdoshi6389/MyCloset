"""
Category pairing rules for outfit compatibility scoring.

Answers: "given what's already in the outfit, how well does this candidate
category complete or complement it?"

Kept as a plain config-style module so weights can be tuned without touching
the scoring logic, and so a future ML ranker can absorb these features directly.
"""

# ── Outfit completeness bonus ─────────────────────────────────────────────────
# Maps frozenset of FILLED slots → {target_slot → bonus (0-1)}.
# The bonus represents how much filling 'target_slot' completes a logical outfit.
COMPLETENESS: dict[frozenset, dict[str, float]] = {
    frozenset({"inner_top"}): {
        "inner_bottom": 0.85, "outer_bottom": 0.80,
        "left_shoe": 0.60, "outer_top": 0.75,
        "hat": 0.55, "bag": 0.55, "necklace": 0.50, "bracelet_left": 0.50,
    },
    frozenset({"inner_bottom"}): {
        "inner_top": 0.85, "outer_top": 0.70,
        "left_shoe": 0.60,
    },
    frozenset({"inner_top", "inner_bottom"}): {
        "left_shoe": 0.90, "outer_top": 0.80,
        "hat": 0.60, "bag": 0.60, "necklace": 0.55,
    },
    frozenset({"outer_top", "inner_bottom"}): {
        "left_shoe": 0.90, "inner_top": 0.85,
        "bag": 0.65, "hat": 0.60,
    },
    frozenset({"inner_top", "inner_bottom", "outer_top"}): {
        "left_shoe": 0.95, "hat": 0.65, "bag": 0.65, "necklace": 0.55,
    },
    frozenset({"inner_top", "inner_bottom", "left_shoe"}): {
        "outer_top": 0.80, "hat": 0.65, "bag": 0.65, "necklace": 0.55,
    },
    frozenset({"inner_top", "outer_bottom"}): {
        "left_shoe": 0.90, "outer_top": 0.75, "bag": 0.65,
    },
}

# Default bonus if no exact match found (fewer than 2 items in outfit, etc.)
DEFAULT_BONUS = 0.50

# ── Formality-slot affinity ───────────────────────────────────────────────────
# Certain slots signal formality levels.  Scoring penalises mismatches.
# E.g. a "gym sneaker" (inferred formality ~2) in a formal outfit (score 8+)
# should score low on category_pairing.

# Keywords in candidate title → inferred formality bucket
_FORMAL_KW   = {"blazer", "dress shoe", "oxford", "loafer", "trouser", "slacks",
                "button", "dress shirt", "suit", "chino", "monk strap", "derby",
                "brogues", "formal"}
_CASUAL_KW   = {"hoodie", "sweatshirt", "jogger", "cargo", "sweatpant", "sneaker",
                "canvas", "slip on", "tee", "t-shirt", "denim", "jean", "polo"}
_ATHLETIC_KW = {"gym", "athletic", "training", "sport", "running", "active", "compression",
                "spandex", "legging", "shorts", "tank", "performance"}


def infer_formality_from_title(title: str) -> float | None:
    """Return a rough 1-10 formality score inferred from a product title, or None."""
    t = title.lower()
    if any(kw in t for kw in _FORMAL_KW):
        return 8.0
    if any(kw in t for kw in _ATHLETIC_KW):
        return 2.0
    if any(kw in t for kw in _CASUAL_KW):
        return 3.5
    return None


# ── Vibe→slot affinity ────────────────────────────────────────────────────────
# Maps outfit vibe tags to preferred title keywords for each target slot.
# Higher keyword overlap → higher vibe-category score.
VIBE_SLOT_KEYWORDS: dict[str, dict[str, list[str]]] = {
    "athletic": {
        "left_shoe":    ["sneaker", "running", "trainer", "athletic", "sport", "air", "boost"],
        "inner_top":    ["tank", "compression", "jersey", "athletic", "training"],
        "inner_bottom": ["jogger", "shorts", "legging", "sweatpant", "athletic"],
        "outer_top":    ["track jacket", "windbreaker", "hoodie", "zip"],
    },
    "sporty": {
        "left_shoe":    ["sneaker", "trainer", "running", "court", "sport"],
        "inner_top":    ["polo", "jersey", "tank", "sport"],
        "outer_top":    ["zip", "hoodie", "track"],
    },
    "streetwear": {
        "left_shoe":    ["sneaker", "jordan", "air", "yeezy", "chunky", "platform", "canvas"],
        "inner_top":    ["hoodie", "graphic", "tee", "sweatshirt", "oversized"],
        "inner_bottom": ["cargo", "baggy", "wide leg", "denim"],
        "outer_top":    ["bomber", "varsity", "puffer", "windbreaker"],
        "hat":          ["cap", "snapback", "bucket", "beanie"],
    },
    "casual": {
        "left_shoe":    ["sneaker", "loafer", "slip", "canvas", "sandal", "boat shoe"],
        "inner_top":    ["tee", "polo", "henley", "linen"],
        "inner_bottom": ["chino", "jean", "khaki", "relaxed"],
        "outer_top":    ["hoodie", "cardigan", "flannel", "denim jacket"],
    },
    "formal": {
        "left_shoe":    ["oxford", "loafer", "derby", "brogue", "dress", "monk", "leather"],
        "inner_top":    ["button", "dress shirt", "blouse", "oxford shirt"],
        "inner_bottom": ["trouser", "slacks", "dress pant", "chino"],
        "outer_top":    ["blazer", "suit", "sport coat", "cardigan"],
    },
    "business": {
        "left_shoe":    ["oxford", "loafer", "derby", "leather"],
        "inner_top":    ["button", "dress shirt", "blouse"],
        "inner_bottom": ["trouser", "slacks", "dress pant"],
        "outer_top":    ["blazer", "suit", "cardigan"],
    },
    "minimalist": {
        "left_shoe":    ["loafer", "clean", "simple", "white sneaker", "leather"],
        "inner_top":    ["basic", "plain", "solid", "crew neck", "simple"],
        "inner_bottom": ["slim", "straight", "simple", "solid"],
    },
    "bohemian": {
        "left_shoe":    ["sandal", "boot", "platform", "ankle"],
        "inner_top":    ["floral", "crochet", "lace", "peasant", "flowy"],
        "outer_top":    ["cardigan", "kimono", "wrap"],
    },
    "romantic": {
        "left_shoe":    ["heel", "pump", "sandal", "flat", "mule"],
        "inner_top":    ["floral", "ruffle", "lace", "bow", "feminine"],
        "outer_bottom": ["skirt", "midi", "maxi", "mini"],
    },
    "preppy": {
        "left_shoe":    ["loafer", "oxford", "boat shoe", "penny"],
        "inner_top":    ["polo", "button", "oxford shirt", "sweater"],
        "inner_bottom": ["chino", "khaki", "plaid"],
        "outer_top":    ["blazer", "cardigan", "sweater"],
    },
}


def vibe_category_score(outfit_vibe_tags: list[str], target_slot: str, candidate_title: str) -> float:
    """
    Score how well a candidate title matches the vibe→slot affinity rules.
    Returns 0.0–1.0. Default 0.50 when no data.
    """
    if not outfit_vibe_tags or not candidate_title:
        return 0.50

    title_lower = candidate_title.lower()
    total_hits  = 0
    total_kw    = 0

    for vibe in outfit_vibe_tags:
        slot_kw_map = VIBE_SLOT_KEYWORDS.get(vibe, {})
        kw_list = slot_kw_map.get(target_slot, [])
        if not kw_list:
            continue
        hits = sum(1 for kw in kw_list if kw in title_lower)
        total_hits += hits
        total_kw   += len(kw_list)

    if total_kw == 0:
        return 0.50

    raw = total_hits / total_kw
    # Scale: 0 hits → 0.35, any hit → 0.60–0.95
    if total_hits == 0:
        return 0.35
    return min(0.95, 0.60 + raw * 0.35)


def completeness_score(filled_slots: set[str], target_slot: str) -> float:
    """
    How much does filling `target_slot` complete the outfit?
    Checks progressively smaller subset matches.
    """
    fs = frozenset(filled_slots)

    # Exact match
    if fs in COMPLETENESS:
        return COMPLETENESS[fs].get(target_slot, DEFAULT_BONUS)

    # Subset matches — find the largest matching subset
    best_bonus = DEFAULT_BONUS
    best_size  = 0
    for key, bonuses in COMPLETENESS.items():
        if key.issubset(fs) and len(key) > best_size:
            bonus = bonuses.get(target_slot)
            if bonus is not None:
                best_bonus = bonus
                best_size  = len(key)

    return best_bonus


def category_pairing_score(
    target_slot: str,
    filled_slots: set[str],
    candidate_title: str,
    outfit_vibe_tags: list[str],
    outfit_formality: float,
    candidate_formality: float | None,
) -> float:
    """
    Combined category-pairing score (0–1).
    Weights:
      40% completeness bonus
      35% vibe-category affinity
      25% formality consistency
    """
    comp  = completeness_score(filled_slots, target_slot)
    vibe  = vibe_category_score(outfit_vibe_tags, target_slot, candidate_title)

    if candidate_formality is not None:
        diff     = abs(candidate_formality - outfit_formality)
        formality = max(0.0, 1.0 - diff / 8.0)
    else:
        formality = 0.55

    return round(0.40 * comp + 0.35 * vibe + 0.25 * formality, 4)
