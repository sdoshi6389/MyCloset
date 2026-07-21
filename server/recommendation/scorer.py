"""
Multi-factor candidate scoring — both closet items and catalog products.

Returns a score dict:  { "total": float, "breakdown": { factor: float } }
All factor scores are 0.0–1.0.  Missing data → graceful neutral fallback.

Scoring weights (configurable):
  outfit_compatibility  0.25  — embedding-based complementarity
  color_harmony         0.20  — color family compatibility
  vibe_match            0.15  — tag Jaccard / inferred vibe overlap
  user_preference       0.15  — pref_vector cosine + vibe frequency
  formality_match       0.10  — formality score alignment
  category_pairing      0.10  — category/vibe/completeness rules
  novelty               0.05  — placeholder; applied at engine level via MMR
"""
import numpy as np
from .color_utils import color_harmony_score
from .category_rules import (
    category_pairing_score,
    infer_formality_from_title,
    VIBE_SLOT_KEYWORDS,
)

# ── Tunable weights ───────────────────────────────────────────────────────────
WEIGHTS: dict[str, float] = {
    "outfit_compatibility": 0.25,
    "color_harmony":        0.20,
    "vibe_match":           0.15,
    "user_preference":      0.15,
    "formality_match":      0.10,
    "category_pairing":     0.10,
    "novelty":              0.05,   # computed externally (MMR); score stored as 0.5 here
}


# ── Helpers ───────────────────────────────────────────────────────────────────
def _parse_tags(s) -> set[str]:
    if not s:
        return set()
    if isinstance(s, list):
        return {t.lower().strip() for t in s if t}
    return {t.strip().lower()
            for t in str(s).replace("[","").replace("]","").replace("'","").replace('"',"").split(",")
            if t.strip()}


def _parse_vector(v) -> np.ndarray | None:
    if v is None:
        return None
    if isinstance(v, (list, np.ndarray)):
        return np.array(v, dtype=np.float32)
    if isinstance(v, str):
        import json
        try:
            return np.array(json.loads(v), dtype=np.float32)
        except Exception:
            return None
    return None


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na < 1e-8 or nb < 1e-8:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def _outfit_embedding(outfit_items: list[dict]) -> np.ndarray | None:
    """Mean of all placed-item embeddings, normalized."""
    vecs = [_parse_vector(i.get("vector_embedding")) for i in outfit_items]
    vecs = [v for v in vecs if v is not None and v.shape[0] > 0]
    if not vecs:
        return None
    mean = np.mean(np.stack(vecs), axis=0).astype(np.float32)
    norm = np.linalg.norm(mean)
    return mean / norm if norm > 1e-8 else mean


def _outfit_vibe_tags(outfit_items: list[dict]) -> list[str]:
    seen, out = set(), []
    for item in outfit_items:
        for tag in _parse_tags(item.get("vibe")) | _parse_tags(item.get("style")):
            if tag not in seen:
                seen.add(tag)
                out.append(tag)
    return out


def _outfit_formality(outfit_items: list[dict], profile: dict) -> float:
    vals = [item.get("formality_score") for item in outfit_items
            if isinstance(item.get("formality_score"), (int, float))]
    return float(np.mean(vals)) if vals else profile.get("formality_center", 5.0)


# ── Catalog item metadata enrichment ─────────────────────────────────────────
_VIBE_TITLE_KW: dict[str, list[str]] = {
    "athletic":   ["gym", "training", "athletic", "running", "sport", "active", "performance", "compression", "workout"],
    "sporty":     ["sport", "polo", "track", "jersey", "court"],
    "streetwear": ["hoodie", "cargo", "graphic", "oversized", "street", "puffer", "bomber", "baggy", "camo"],
    "casual":     ["relaxed", "linen", "everyday", "simple", "classic", "chino", "weekend"],
    "formal":     ["blazer", "suit", "dress shirt", "button-up", "oxford", "loafer", "trouser", "slacks", "elegant"],
    "business":   ["business", "professional", "dress", "button-down", "blazer", "pencil skirt"],
    "minimalist": ["minimal", "clean", "simple", "basic", "plain", "solid", "ribbed"],
    "bohemian":   ["boho", "floral", "crochet", "wrap", "maxi", "peasant", "fringe"],
    "romantic":   ["ruffle", "lace", "bow", "feminine", "floral", "off-shoulder", "wrap"],
    "preppy":     ["polo", "chino", "plaid", "argyle", "boat shoe", "madras", "khaki"],
}


def infer_vibes_from_title(title: str) -> list[str]:
    """Return a list of probable vibe tags inferred from a product title."""
    t     = title.lower()
    vibes = []
    for vibe, kws in _VIBE_TITLE_KW.items():
        if any(kw in t for kw in kws):
            vibes.append(vibe)
    return vibes or ["casual"]   # default fallback


def enrich_catalog_item(hit: dict) -> dict:
    """
    Add inferred metadata to a raw FAISS hit (catalog product) so the full
    7-factor scorer can run.  Original dict is not mutated.
    """
    title    = hit.get("title", "")
    enriched = dict(hit)
    enriched.setdefault("inferred_vibes",     infer_vibes_from_title(title))
    enriched.setdefault("inferred_formality", infer_formality_from_title(title))
    return enriched


# ── Individual factor scorers ─────────────────────────────────────────────────

def _score_outfit_compatibility(candidate_vec, outfit_emb) -> float:
    """Cosine similarity between candidate and outfit mean embedding → 0–1."""
    if candidate_vec is None or outfit_emb is None:
        return 0.50
    sim = _cosine(candidate_vec, outfit_emb)
    return round((sim + 1.0) / 2.0, 4)   # -1…1 → 0…1


def _score_color_harmony(candidate: dict, outfit_items: list[dict]) -> float:
    outfit_colors = [i.get("color", "").lower().strip() for i in outfit_items if i.get("color")]
    cand_color    = (candidate.get("color") or "").lower().strip()
    if not outfit_colors or not cand_color:
        return 0.65
    return round(float(np.mean([color_harmony_score(c, cand_color) for c in outfit_colors])), 4)


def _score_vibe_match(
    cand_tags: set[str],
    outfit_tags: list[str],
    profile_vibe_weights: dict,
) -> float:
    outfit_set = set(outfit_tags)
    if not outfit_set and not profile_vibe_weights:
        return 0.50

    # Jaccard with outfit tags
    if outfit_set and cand_tags:
        union        = outfit_set | cand_tags
        intersection = outfit_set & cand_tags
        jaccard      = len(intersection) / len(union)
    else:
        jaccard = 0.0

    # Profile vibe frequency alignment
    if profile_vibe_weights and cand_tags:
        total   = sum(profile_vibe_weights.values()) or 1
        matched = sum(profile_vibe_weights.get(t, 0) for t in cand_tags)
        prof    = min(1.0, (matched / total) * 4)
    else:
        prof = 0.50

    # Weighted combination
    score = 0.60 * jaccard + 0.40 * prof if outfit_set else prof
    return round(max(0.0, min(1.0, score)), 4)


def _score_user_preference(
    candidate_vec,
    cand_tags: set[str],
    profile: dict,
) -> float:
    pref_vec      = _parse_vector(profile.get("pref_vector"))
    vibe_weights  = profile.get("vibe_weights") or {}
    disliked_vec  = _parse_vector(profile.get("disliked_embedding"))

    # Embedding proximity to pref_vector
    if pref_vec is not None and candidate_vec is not None:
        sim       = _cosine(pref_vec, candidate_vec)
        emb_score = (sim + 1.0) / 2.0
    else:
        emb_score = 0.50

    # Penalise if similar to disliked items
    if disliked_vec is not None and candidate_vec is not None:
        dislike_sim = _cosine(disliked_vec, candidate_vec)
        if dislike_sim > 0.85:
            emb_score = max(0.0, emb_score - 0.30)

    # Vibe frequency alignment
    if vibe_weights and cand_tags:
        total   = sum(vibe_weights.values()) or 1
        matched = sum(vibe_weights.get(t, 0) for t in cand_tags)
        vf      = min(1.0, (matched / total) * 4)
    else:
        vf = 0.50

    return round(0.70 * emb_score + 0.30 * vf, 4)


def _score_formality_match(
    candidate: dict,
    outfit_formality: float,
    inferred_formality: float | None,
) -> float:
    cand_fs = candidate.get("formality_score") or inferred_formality
    if not isinstance(cand_fs, (int, float)):
        return 0.55
    diff = abs(float(cand_fs) - outfit_formality)
    return round(max(0.0, 1.0 - diff / 8.0), 4)


def _score_category_pairing(
    target_slot: str,
    filled_slots: set[str],
    candidate: dict,
    outfit_vibe_tags: list[str],
    outfit_formality: float,
    inferred_formality: float | None,
) -> float:
    title      = candidate.get("title") or candidate.get("matched_title") or ""
    cand_form  = candidate.get("formality_score") or inferred_formality
    return category_pairing_score(
        target_slot, filled_slots, title, outfit_vibe_tags, outfit_formality, cand_form
    )


# ── Public scoring functions ──────────────────────────────────────────────────

def score_candidate(
    candidate: dict,
    outfit_items: list[dict],
    profile: dict,
    target_slot: str,
    filled_slots: set[str],
    faiss_distance: float | None = None,
) -> dict:
    """
    Full 7-factor score for any candidate (closet OR catalog).
    Returns: { "total": float, "breakdown": { factor: float } }

    For closet items supply vector_embedding in candidate.
    For catalog items supply faiss_distance (distance from FAISS query).
    Graceful fallbacks for any missing data.
    """
    outfit_emb      = _outfit_embedding(outfit_items)
    outfit_tags     = _outfit_vibe_tags(outfit_items)
    outfit_formality = _outfit_formality(outfit_items, profile)

    candidate_vec  = _parse_vector(candidate.get("vector_embedding"))
    inferred_form  = candidate.get("inferred_formality")

    # Candidate vibe tags: use stored tags for closet items; use inferred for catalog
    stored_tags    = _parse_tags(candidate.get("vibe")) | _parse_tags(candidate.get("style"))
    inferred_tags  = set(candidate.get("inferred_vibes") or [])
    cand_tags      = stored_tags | inferred_tags

    # ── Factor 1: outfit compatibility ─────────────────────────────────────
    if candidate_vec is not None and outfit_emb is not None:
        oc = _score_outfit_compatibility(candidate_vec, outfit_emb)
    elif faiss_distance is not None:
        # Catalog item: use FAISS distance as proxy (typical range 0–2 for normalised CLIP)
        oc = round(max(0.0, 1.0 - faiss_distance / 2.0), 4)
    else:
        oc = 0.50

    # ── Factor 2: color harmony ────────────────────────────────────────────
    ch = _score_color_harmony(candidate, outfit_items)

    # ── Factor 3: vibe match ───────────────────────────────────────────────
    vm = _score_vibe_match(cand_tags, outfit_tags, profile.get("vibe_weights") or {})

    # ── Factor 4: user preference ──────────────────────────────────────────
    up = _score_user_preference(candidate_vec, cand_tags, profile)

    # ── Factor 5: formality match ──────────────────────────────────────────
    fm = _score_formality_match(candidate, outfit_formality, inferred_form)

    # ── Factor 6: category pairing ─────────────────────────────────────────
    cp = _score_category_pairing(
        target_slot, filled_slots, candidate, outfit_tags, outfit_formality, inferred_form
    )

    # ── Factor 7: novelty (placeholder; real diversity applied via MMR) ────
    nv = 0.50

    breakdown = {
        "outfit_compatibility": oc,
        "color_harmony":        ch,
        "vibe_match":           vm,
        "user_preference":      up,
        "formality_match":      fm,
        "category_pairing":     cp,
        "novelty":              nv,
    }

    total = round(sum(breakdown[k] * WEIGHTS[k] for k in WEIGHTS), 4)

    return {"total": total, "breakdown": breakdown}


# ── Backward-compatible shims (used by existing callers) ─────────────────────

def score_closet_candidate(candidate: dict, outfit_items: list[dict], profile: dict) -> float:
    """Legacy shim — returns total score only."""
    filled = {slot for slot, item in (profile.get("_outfit_state") or {}).items() if item}
    result = score_candidate(candidate, outfit_items, profile,
                             target_slot="inner_top", filled_slots=filled)
    return result["total"]


def score_catalog_candidate(candidate: dict, outfit_items: list[dict], faiss_distance: float) -> float:
    """Legacy shim — returns total score only."""
    enriched = enrich_catalog_item(candidate)
    result   = score_candidate(enriched, outfit_items, {}, target_slot="left_shoe",
                                filled_slots=set(), faiss_distance=faiss_distance)
    return result["total"]
