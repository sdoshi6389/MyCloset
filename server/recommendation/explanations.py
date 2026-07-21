"""
Generate short, human-readable recommendation reasons from score breakdowns.
Keeps the logic separate so it can be improved without touching the ranker.
"""


def _top_vibe(outfit_items: list[dict]) -> str | None:
    counts: dict[str, int] = {}
    for item in outfit_items:
        raw = item.get("vibe") or item.get("style") or ""
        if isinstance(raw, list):
            tags = raw
        else:
            tags = [t.strip().lower() for t in
                    str(raw).replace("[", "").replace("]", "").replace("'", "").split(",")
                    if t.strip()]
        for t in tags:
            counts[t] = counts.get(t, 0) + 1
    if not counts:
        return None
    return max(counts, key=lambda k: counts[k])


def generate_reason(
    breakdown: dict,
    candidate: dict,
    outfit_items: list[dict],
    target_slot: str,
) -> str:
    """
    Build a 1-2 sentence explanation from the score breakdown.
    Each sentence contributes one primary insight so the result stays concise.
    """
    parts: list[str] = []

    color = (candidate.get("color") or "").strip()
    title = (candidate.get("title") or candidate.get("matched_title") or "").strip()
    brand = (candidate.get("brand") or candidate.get("source") or "").strip()

    # ── Color harmony ─────────────────────────────────────────────────────────
    color_score = breakdown.get("color_harmony", 0)
    if color_score >= 0.85 and color:
        outfit_colors = [i.get("color", "") for i in outfit_items if i.get("color")]
        if outfit_colors:
            dominant = outfit_colors[0]
            parts.append(f"{color.capitalize()} pairs well with the {dominant} already in your outfit")
        else:
            parts.append(f"The {color} colorway works well with your palette")
    elif color_score < 0.45 and color:
        parts.append(f"A bolder color choice — it will stand out against the current palette")

    # ── Vibe match ────────────────────────────────────────────────────────────
    vibe_score = breakdown.get("vibe_match", 0)
    top_vibe   = _top_vibe(outfit_items)
    if vibe_score >= 0.70 and top_vibe:
        parts.append(f"fits the {top_vibe} aesthetic of this look")
    elif vibe_score < 0.40 and top_vibe:
        parts.append(f"adds contrast to the {top_vibe} vibe")

    # ── Category pairing ──────────────────────────────────────────────────────
    cat_score = breakdown.get("category_pairing", 0)
    if cat_score >= 0.80 and not parts:
        slot_labels = {
            "left_shoe": "completes the footwear",
            "outer_top": "adds the finishing outerwear layer",
            "hat":        "tops off the look",
            "bag":        "adds the finishing accessory",
            "necklace":   "adds a nice neckline detail",
        }
        label = slot_labels.get(target_slot)
        if label:
            parts.append(label)

    # ── User preference ───────────────────────────────────────────────────────
    pref_score = breakdown.get("user_preference", 0)
    if pref_score >= 0.75 and not any("style" in p or "aesthetic" in p for p in parts):
        parts.append("aligns with your personal style")

    # ── Formality ────────────────────────────────────────────────────────────
    form_score = breakdown.get("formality_match", 0)
    if form_score >= 0.85 and not parts:
        parts.append("matches the formality level of this outfit")
    elif form_score < 0.35:
        parts.append("note: this may be a formality mismatch for this outfit")

    # ── Outfit compatibility ──────────────────────────────────────────────────
    compat = breakdown.get("outfit_compatibility", 0)
    if compat >= 0.80 and not parts:
        item_name = title or brand or "This piece"
        parts.append(f"{item_name} is a strong visual complement to the current outfit")

    # ── Fallback ─────────────────────────────────────────────────────────────
    if not parts:
        if brand and title:
            parts.append(f"{brand} — a solid pick for this slot")
        else:
            parts.append("A good complement for this outfit")

    # Build sentence: capitalize first, period at end
    sentence = "; ".join(parts[:2])
    sentence = sentence[0].upper() + sentence[1:]
    if not sentence.endswith("."):
        sentence += "."

    return sentence
