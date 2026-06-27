"""Outfit CRUD and slot management."""
from db import get_supa


def create_outfit(user_id, name, occasion=None, tags=None, notes=None, is_private=False):
    supa = get_supa()
    result = supa.table("outfits").insert({
        "user_id":    user_id,
        "name":       name,
        "occasion":   occasion,
        "tags":       tags,
        "notes":      notes,
        "is_private": bool(is_private),
    }).execute()
    return result.data[0]["id"]


def save_outfit_items(outfit_id, slot_item_pairs):
    """slot_item_pairs: list of (slot, closet_item_id)"""
    supa = get_supa()
    supa.table("outfit_items").delete().eq("outfit_id", outfit_id).execute()

    rows = [
        {"outfit_id": outfit_id, "closet_item_id": closet_item_id, "slot": slot}
        for slot, closet_item_id in slot_item_pairs
        if closet_item_id is not None
    ]
    if rows:
        supa.table("outfit_items").upsert(
            rows, on_conflict="outfit_id,closet_item_id,slot", ignore_duplicates=True
        ).execute()


def _fetch_outfit_items(supa, outfit_ids: list) -> dict:
    """Returns {outfit_id: [item, ...]} with closet item details."""
    if not outfit_ids:
        return {}
    oi_res = supa.table("outfit_items").select(
        "outfit_id, slot, closet_item_id, "
        "closet_items(id, filename, brand, icon_path, category, user_id)"
    ).in_("outfit_id", outfit_ids).execute()

    by_outfit: dict = {}
    for r in oi_res.data:
        ci = r.get("closet_items") or {}
        by_outfit.setdefault(r["outfit_id"], []).append({
            "slot":           r["slot"],
            "closet_item_id": r["closet_item_id"],
            "filename":       ci.get("filename"),
            "brand":          ci.get("brand"),
            "icon_path":      ci.get("icon_path"),
            "category":       ci.get("category"),
            "owner_user_id":  ci.get("user_id"),
        })
    return by_outfit


def get_outfits(user_id):
    supa = get_supa()
    outfits_res = supa.table("outfits").select(
        "id, name, occasion, tags, notes, rating, is_private, created_at, updated_at"
    ).eq("user_id", user_id).order("created_at", desc=True).execute()

    outfit_ids     = [o["id"] for o in outfits_res.data]
    items_by_outfit = _fetch_outfit_items(supa, outfit_ids)

    return [
        {
            "id":         o["id"],
            "name":       o["name"],
            "occasion":   o["occasion"],
            "tags":       o["tags"],
            "notes":      o["notes"],
            "rating":     o["rating"],
            "is_private": o.get("is_private", False),
            "is_mine":    True,
            "owner_email":   None,
            "owner_initial": None,
            "created_at": o["created_at"],
            "updated_at": o["updated_at"],
            "items":      items_by_outfit.get(o["id"], []),
        }
        for o in outfits_res.data
    ]


def get_circle_outfits(user_id, circle_id):
    """Returns all non-private circle-member outfits plus the caller's own outfits."""
    from services.circles_service import is_member
    supa = get_supa()

    if not is_member(circle_id, user_id):
        return []

    members_res = supa.table("circle_members").select("user_id").eq("circle_id", circle_id).execute()
    member_ids  = [r["user_id"] for r in members_res.data]
    if not member_ids:
        return []

    users_res  = supa.table("users").select("id, email").in_("id", member_ids).execute()
    users_map  = {u["id"]: u["email"] for u in users_res.data}

    outfits_res = supa.table("outfits").select(
        "id, name, occasion, tags, notes, rating, is_private, created_at, updated_at, user_id"
    ).in_("user_id", member_ids).order("created_at", desc=True).execute()

    # Own outfits always visible; others' only if not private
    outfits_data = [
        o for o in outfits_res.data
        if o["user_id"] == user_id or not o.get("is_private", False)
    ]

    items_by_outfit = _fetch_outfit_items(supa, [o["id"] for o in outfits_data])

    return [
        {
            "id":            o["id"],
            "name":          o["name"],
            "occasion":      o["occasion"],
            "tags":          o["tags"],
            "notes":         o["notes"],
            "rating":        o["rating"],
            "is_private":    o.get("is_private", False),
            "is_mine":       o["user_id"] == user_id,
            "owner_id":      o["user_id"],
            "owner_email":   users_map.get(o["user_id"], ""),
            "owner_initial": (users_map.get(o["user_id"], "") or "?")[0].upper(),
            "created_at":    o["created_at"],
            "updated_at":    o["updated_at"],
            "items":         items_by_outfit.get(o["id"], []),
        }
        for o in outfits_data
    ]


def delete_outfit(outfit_id, user_id):
    result = get_supa().table("outfits").delete().eq("id", outfit_id).eq("user_id", user_id).execute()
    return len(result.data) > 0


def rate_outfit(outfit_id, user_id, rating):
    supa = get_supa()
    supa.table("outfit_ratings").upsert({
        "outfit_id": outfit_id,
        "user_id":   user_id,
        "rating":    rating,
    }, on_conflict="outfit_id,user_id").execute()

    all_ratings = supa.table("outfit_ratings").select("rating").eq("outfit_id", outfit_id).execute()
    ratings = [r["rating"] for r in all_ratings.data if r["rating"] is not None]
    avg = round(sum(ratings) / len(ratings)) if ratings else None
    supa.table("outfits").update({"rating": avg}).eq("id", outfit_id).execute()


def add_feedback(outfit_id, user_id, feedback):
    get_supa().table("outfit_feedback").insert({
        "outfit_id": outfit_id,
        "user_id":   user_id,
        "feedback":  feedback,
    }).execute()
