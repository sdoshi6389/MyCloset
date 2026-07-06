"""User style profile — compute from closet + cache in user_profiles table."""
import numpy as np
from datetime import datetime, timezone
from db import get_supa


def _parse_vector(v) -> np.ndarray | None:
    """Handle list, JSON string, or None from Supabase."""
    if v is None:
        return None
    if isinstance(v, np.ndarray):
        return v.astype(np.float32)
    if isinstance(v, list):
        return np.array(v, dtype=np.float32)
    if isinstance(v, str):
        import json
        try:
            return np.array(json.loads(v), dtype=np.float32)
        except Exception:
            return None
    return None


def _parse_tags(s: str | None) -> list[str]:
    if not s:
        return []
    return [t.strip().lower() for t in s.replace("[", "").replace("]", "").replace("'", "").replace('"', "").split(",") if t.strip()]


def compute_user_profile(user_id: int) -> dict:
    """
    Derive style profile from all closet items + saved outfits.
    Upserts result into user_profiles table and returns the profile dict.
    """
    supa = get_supa()

    rows = supa.table("closet_items").select(
        "id, category, type, color, vibe, style, season, formality_score, occasion, vector_embedding"
    ).eq("user_id", user_id).execute().data or []

    embeddings = []
    vibe_counts: dict[str, int] = {}
    style_counts: dict[str, int] = {}
    color_counts: dict[str, int] = {}
    formality_vals: list[float] = []

    for row in rows:
        vec = _parse_vector(row.get("vector_embedding"))
        if vec is not None and vec.shape[0] > 0:
            embeddings.append(vec)

        for v in _parse_tags(row.get("vibe")):
            vibe_counts[v] = vibe_counts.get(v, 0) + 1
        for s in _parse_tags(row.get("style")):
            style_counts[s] = style_counts.get(s, 0) + 1

        c = (row.get("color") or "").lower().strip()
        if c:
            color_counts[c] = color_counts.get(c, 0) + 1

        fs = row.get("formality_score")
        if isinstance(fs, (int, float)):
            formality_vals.append(float(fs))

    # Merge vibe + style into unified vibe_weights
    vibe_weights = {**vibe_counts}
    for k, v in style_counts.items():
        vibe_weights[k] = vibe_weights.get(k, 0) + v

    formality_center = float(np.mean(formality_vals)) if formality_vals else 5.0
    formality_std    = float(np.std(formality_vals))  if len(formality_vals) > 1 else 2.0

    style_vector = None
    if embeddings:
        sv = np.mean(np.stack(embeddings), axis=0).astype(np.float32)
        norm = np.linalg.norm(sv)
        if norm > 1e-8:
            sv = sv / norm
        style_vector = sv

    profile = {
        "user_id":          user_id,
        "vibe_weights":     vibe_weights,
        "color_palette":    color_counts,
        "formality_center": formality_center,
        "formality_std":    formality_std,
        "style_vector":     style_vector.tolist() if style_vector is not None else None,
        "pref_vector":      style_vector.tolist() if style_vector is not None else None,
        "updated_at":       datetime.now(timezone.utc).isoformat(),
    }

    # Cache in DB — store vectors as lists (Supabase pgvector accepts JSON arrays)
    try:
        supa.table("user_profiles").upsert(profile, on_conflict="user_id").execute()
    except Exception as e:
        print(f"⚠️  user_profiles upsert failed: {e}")

    return profile


def get_user_profile(user_id: int) -> dict:
    """Return cached profile if fresh (<24 h), else recompute."""
    supa = get_supa()
    res = supa.table("user_profiles").select("*").eq("user_id", user_id).execute()

    if res.data:
        row = res.data[0]
        updated_at = row.get("updated_at")
        if updated_at:
            try:
                last = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                if (datetime.now(timezone.utc) - last).total_seconds() < 86400:
                    return row
            except Exception:
                pass

    return compute_user_profile(user_id)


def update_pref_vector(user_id: int, item_id: int, direction: int) -> None:
    """
    Nudge pref_vector toward (direction=+1) or away from (direction=-1) an item.
    Learning rate 0.05 — preferences shift gradually.
    Works for closet items only (catalog items have no stored embedding).
    """
    supa = get_supa()

    item_res = supa.table("closet_items").select("vector_embedding").eq("id", item_id).execute()
    if not item_res.data:
        return
    item_vec = _parse_vector(item_res.data[0].get("vector_embedding"))
    if item_vec is None:
        return

    prof_res = supa.table("user_profiles").select("pref_vector").eq("user_id", user_id).execute()
    if not prof_res.data:
        return
    pref = _parse_vector(prof_res.data[0].get("pref_vector"))
    if pref is None:
        return

    pref = pref + 0.05 * direction * item_vec
    norm = np.linalg.norm(pref)
    if norm > 1e-8:
        pref = pref / norm

    try:
        supa.table("user_profiles").update({
            "pref_vector": pref.tolist()
        }).eq("user_id", user_id).execute()
    except Exception as e:
        print(f"⚠️  pref_vector update failed: {e}")
