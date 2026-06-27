"""Closet business logic — separated from Flask routes."""
from db import get_supa


def get_closet_items(user_id):
    supa = get_supa()
    result = supa.table("closet_items").select(
        "id, filename, filepath, tag_text, brand, size, category, tags, "
        "matched_brand, matched_title, icon_path, caption, type, color, style, season, "
        "fabric, vibe, keywords, emoticon_path, created_at"
    ).eq("user_id", user_id).order("id").execute()

    items = []
    for item in result.data:
        item["url"] = f"/static/{user_id}/{item['filename']}"
        items.append(item)
    return items


def get_categories(user_id):
    supa = get_supa()
    result = supa.table("categories").select("id, name, is_default").or_(
        f"user_id.is.null,user_id.eq.{user_id}"
    ).order("is_default", desc=True).order("name").execute()
    return [{"id": r["id"], "name": r["name"], "is_default": r["is_default"]} for r in result.data]


def add_category(user_id, name):
    supa = get_supa()
    try:
        result = supa.table("categories").insert({
            "user_id": user_id,
            "name": name,
            "is_default": False,
        }).execute()
        row = result.data[0] if result.data else None
        if row:
            return {"id": row["id"], "name": row["name"]}
        return None
    except Exception as e:
        err = str(e)
        if "23505" in err or "unique" in err.lower():
            return None
        raise


def update_closet_item_category(user_id, item_id, category):
    get_supa().table("closet_items").update({"category": category}).eq("id", item_id).eq("user_id", user_id).execute()
