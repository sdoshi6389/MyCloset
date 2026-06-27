"""Circles and circle membership logic."""
from db import get_supa


def create_circle(owner_id, name, description=None):
    supa = get_supa()
    result = supa.table("circles").insert({
        "owner_id": owner_id,
        "name": name,
        "description": description,
    }).execute()
    circle_id = result.data[0]["id"]

    supa.table("circle_members").upsert({
        "circle_id": circle_id,
        "user_id": owner_id,
        "role": "owner",
    }, on_conflict="circle_id,user_id", ignore_duplicates=True).execute()

    return circle_id


def get_user_circles(user_id):
    supa = get_supa()
    memberships = supa.table("circle_members").select(
        "circle_id, role, circles(id, name, description, owner_id, created_at)"
    ).eq("user_id", user_id).execute().data

    circle_ids = [m.get("circles", {}).get("id") for m in memberships if m.get("circles")]

    # Bulk count members for all circles
    count_map = {}
    if circle_ids:
        all_members = supa.table("circle_members").select("circle_id").in_("circle_id", circle_ids).execute().data
        for m in all_members:
            cid = m["circle_id"]
            count_map[cid] = count_map.get(cid, 0) + 1

    circles = []
    for row in memberships:
        c = row.get("circles") or {}
        if not c:
            continue
        circles.append({
            "id":           c["id"],
            "name":         c["name"],
            "description":  c["description"],
            "owner_id":     c["owner_id"],
            "role":         row["role"],
            "created_at":   c["created_at"],
            "member_count": count_map.get(c["id"], 0),
        })
    return circles


def get_circle_members(circle_id):
    supa = get_supa()
    result = supa.table("circle_members").select(
        "user_id, role, joined_at, users(id, email)"
    ).eq("circle_id", circle_id).order("joined_at").execute()

    members = []
    for row in result.data:
        user = row.get("users") or {}
        members.append({
            "id":        user.get("id"),
            "email":     user.get("email"),
            "role":      row["role"],
            "joined_at": row["joined_at"],
        })
    return members


def add_member(circle_id, user_id, added_by_user_id):
    get_supa().table("circle_members").upsert({
        "circle_id": circle_id,
        "user_id": user_id,
        "role": "member",
    }, on_conflict="circle_id,user_id", ignore_duplicates=True).execute()


def remove_member(circle_id, user_id, removed_by_user_id):
    get_supa().table("circle_members").delete().eq("circle_id", circle_id).eq("user_id", user_id).neq("role", "owner").execute()


def delete_circle(circle_id, owner_id):
    result = get_supa().table("circles").delete().eq("id", circle_id).eq("owner_id", owner_id).execute()
    return len(result.data) > 0


def is_member(circle_id, user_id):
    result = get_supa().table("circle_members").select("user_id").eq("circle_id", circle_id).eq("user_id", user_id).execute()
    return len(result.data) > 0
