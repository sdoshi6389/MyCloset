"""
Rule-based outfit recommender.
Interface: recommend_outfits(user_id, occasion=None, style_prompt=None, circle_id=None)
Returns: list of ranked outfit candidates with explanations.

TODO: Replace rule logic with ML/embedding-based ranker once user feedback accumulates.
"""
from db import get_db
from services.outfit_service import get_outfits


COMPATIBLE_CATEGORY_COMBOS = [
    {"Tops", "Bottoms"},
    {"Tops", "Bottoms", "Shoes"},
    {"Tops", "Bottoms", "Outerwear", "Shoes"},
    {"Tops", "Bottoms", "Accessories"},
    {"Tops", "Bottoms", "Outerwear", "Accessories", "Shoes"},
]


def recommend_outfits(user_id, occasion=None, style_prompt=None, circle_id=None):
    """
    Returns up to 5 ranked outfit suggestions from the user's existing saved outfits,
    or generates candidate combos from closet items.
    """
    saved = get_outfits(user_id)
    candidates = []

    for outfit in saved:
        score = 0
        explanation = []

        # Boost by rating
        if outfit.get("rating"):
            score += outfit["rating"] * 10
            explanation.append(f"Rated {outfit['rating']}/5")

        # Boost by occasion match
        if occasion and outfit.get("occasion") and occasion.lower() in (outfit["occasion"] or "").lower():
            score += 20
            explanation.append(f"Matches occasion: {occasion}")

        # Boost by style_prompt keyword match in tags/notes
        if style_prompt:
            text = " ".join(filter(None, [outfit.get("tags", ""), outfit.get("notes", "")]))
            if style_prompt.lower() in text.lower():
                score += 15
                explanation.append(f"Matches style: {style_prompt}")

        categories = {item["category"] for item in outfit["items"] if item.get("category")}
        if any(categories.issubset(combo) for combo in COMPATIBLE_CATEGORY_COMBOS):
            score += 10
            explanation.append("Well-balanced category mix")

        candidates.append({
            "outfit": outfit,
            "score": score,
            "explanation": "; ".join(explanation) or "Saved outfit",
        })

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:5]
