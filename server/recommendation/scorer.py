"""Multi-factor candidate scoring."""
import numpy as np
from .color_utils import color_harmony_score


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


def score_closet_candidate(candidate: dict, outfit_items: list[dict], profile: dict) -> float:
    """
    Full 5-factor score for a closet item candidate. Returns 0.0–1.0.
    Factors: style_compat, color_harmony, formality_fit, clip_similarity, user_pref
    """
    scores: dict[str, float] = {}

    # ── 1. Style compatibility (vibe + style tag Jaccard) ──────────────────
    outfit_tags = set()
    for item in outfit_items:
        outfit_tags |= _parse_tags(item.get("vibe"))
        outfit_tags |= _parse_tags(item.get("style"))

    cand_tags = _parse_tags(candidate.get("vibe")) | _parse_tags(candidate.get("style"))

    if outfit_tags and cand_tags:
        union = outfit_tags | cand_tags
        intersection = outfit_tags & cand_tags
        scores["style"] = len(intersection) / len(union)
    else:
        scores["style"] = 0.50

    # ── 2. Color harmony ───────────────────────────────────────────────────
    outfit_colors = [item.get("color","").lower().strip() for item in outfit_items if item.get("color")]
    cand_color = (candidate.get("color") or "").lower().strip()

    if outfit_colors and cand_color:
        scores["color"] = float(np.mean([color_harmony_score(c, cand_color) for c in outfit_colors]))
    else:
        scores["color"] = 0.65

    # ── 3. Formality alignment ────────────────────────────────────────────
    fs_vals = [item.get("formality_score") for item in outfit_items
               if isinstance(item.get("formality_score"), (int, float))]
    outfit_formality = float(np.mean(fs_vals)) if fs_vals else profile.get("formality_center", 5.0)

    cand_fs = candidate.get("formality_score")
    if isinstance(cand_fs, (int, float)):
        diff = abs(float(cand_fs) - outfit_formality)
        scores["formality"] = max(0.0, 1.0 - diff / 8.0)
    else:
        scores["formality"] = 0.55

    # ── 4. CLIP similarity to user preference vector ───────────────────────
    pref = _parse_vector(profile.get("pref_vector"))
    cand_emb = _parse_vector(candidate.get("vector_embedding"))

    if pref is not None and cand_emb is not None:
        sim = _cosine(pref, cand_emb)
        scores["clip"] = (sim + 1.0) / 2.0  # -1…1 → 0…1
    else:
        scores["clip"] = 0.50

    # ── 5. User vibe preference frequency ────────────────────────────────
    vibe_w = profile.get("vibe_weights") or {}
    if vibe_w and cand_tags:
        total = sum(vibe_w.values()) or 1
        matched = sum(vibe_w.get(t, 0) for t in cand_tags)
        scores["user_pref"] = min(1.0, (matched / total) * 4)
    else:
        scores["user_pref"] = 0.50

    # ── Weighted sum ──────────────────────────────────────────────────────
    W = {"style": 0.25, "color": 0.25, "formality": 0.15, "clip": 0.25, "user_pref": 0.10}
    return round(sum(scores[k] * W[k] for k in W), 4)


def score_catalog_candidate(candidate: dict, outfit_items: list[dict], faiss_distance: float) -> float:
    """
    Simplified scoring for catalog items (no vibe/formality metadata).
    Factors: color_harmony (50%) + CLIP proximity from FAISS distance (50%)
    """
    outfit_colors = [item.get("color","").lower().strip() for item in outfit_items if item.get("color")]
    cand_color = (candidate.get("color") or "").lower().strip()

    if outfit_colors and cand_color:
        color_score = float(np.mean([color_harmony_score(c, cand_color) for c in outfit_colors]))
    else:
        color_score = 0.65

    # FAISS L2 distance → similarity: lower distance = higher score
    # Typical distances are 0–2 for normalised CLIP embeddings
    clip_score = max(0.0, 1.0 - faiss_distance / 2.0)

    return round(0.50 * color_score + 0.50 * clip_score, 4)
