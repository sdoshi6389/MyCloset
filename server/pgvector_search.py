"""Catalog similarity search served by Postgres (pgvector) instead of in-process FAISS.

FAISS held every vector in the app: ~0.9 GB resident at 207k products, a full
download on boot, and an exact scan that grows linearly with the catalog. This
asks Postgres for the nearest rows instead, so the app holds nothing and the
HNSW index does the work.

Results are shaped exactly like callable_faiss.search_similar_products so the
two are interchangeable, including `distance` on the same squared-L2 scale the
scorer expects (1 - distance/2).
"""
import os

import numpy as np

from db import get_supa

# Fetch more than asked for: results are deduplicated per product afterwards,
# the same way the FAISS path does it.
_OVERFETCH = 4


def enabled() -> bool:
    return os.environ.get("USE_PGVECTOR", "").strip().lower() in ("1", "true", "yes")


def available() -> bool:
    """True when the table and match_products() are actually in place."""
    try:
        get_supa().rpc("match_products", {
            "query_embedding": [0.0] * 512,
            "match_count": 1,
        }).execute()
        return True
    except Exception:
        return False


def search_similar_products(query_vector, brand: str | None = None,
                            gender: str | None = None,
                            top_k: int = 50) -> list:
    qv = np.asarray(query_vector, dtype=np.float32).reshape(-1)
    # The index stores unit vectors; normalise the query so cosine distance is
    # comparable and the squared-L2 conversion in SQL stays valid.
    n = float(np.linalg.norm(qv))
    if n > 0:
        qv = qv / n

    from callable_faiss import _resolve_brand
    canonical = _resolve_brand(brand) if brand else None

    params = {
        "query_embedding": qv.tolist(),
        "match_count": max(top_k * _OVERFETCH, top_k),
    }
    if canonical:
        params["filter_source"] = canonical
    if gender:
        params["filter_gender"] = gender

    try:
        rows = get_supa().rpc("match_products", params).execute().data or []
    except Exception as e:
        print(f"pgvector search failed ({type(e).__name__}: {str(e)[:90]}) - falling back to FAISS")
        from callable_faiss import search_similar_products as faiss_search
        return faiss_search(query_vector, brand=brand, gender=gender, top_k=top_k)

    if canonical and not rows:
        # Same behaviour as the FAISS path: an unknown brand searches everything.
        print(f"No '{canonical}' products - falling back to full catalog")
        params.pop("filter_source", None)
        try:
            rows = get_supa().rpc("match_products", params).execute().data or []
        except Exception:
            rows = []

    # Collapse multiple images of one product to its closest match.
    best: dict = {}
    for r in rows:
        key = (r.get("source"), r.get("product_id") or r.get("url", ""))
        d = float(r.get("distance", 0.0))
        if key not in best or d < best[key]["distance"]:
            best[key] = {
                "source":   r.get("source"),
                "id":       r.get("product_id"),
                "title":    r.get("title"),
                "color":    r.get("color"),
                "price":    r.get("price"),
                "image":    r.get("image"),
                "url":      r.get("url"),
                "gender":   r.get("resolved_gender"),
                "distance": d,
            }
    return sorted(best.values(), key=lambda x: x["distance"])[:top_k]
