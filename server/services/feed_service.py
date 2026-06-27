"""Feed / post logic."""
import os
from db import get_supa

POST_IMAGES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "post_images")
os.makedirs(POST_IMAGES_DIR, exist_ok=True)


def create_post(user_id, caption, visibility="friends", outfit_id=None, circle_id=None):
    supa = get_supa()
    result = supa.table("posts").insert({
        "user_id": user_id,
        "caption": caption,
        "visibility": visibility,
        "outfit_id": outfit_id,
        "circle_id": circle_id,
    }).execute()
    return result.data[0]["id"]


def attach_image_to_post(post_id, image_path):
    get_supa().table("post_images").insert({
        "post_id": post_id,
        "image_path": image_path,
    }).execute()


def get_feed(user_id, limit=30, offset=0):
    """
    Returns posts visible to user_id:
    - own posts (any visibility)
    - friends' posts (visibility = 'friends' or 'public')
    - circle posts where user is a member (visibility = 'circle')
    - public posts
    """
    supa = get_supa()

    _COLS = "id, user_id, caption, visibility, outfit_id, circle_id, created_at"

    # Own posts
    own = supa.table("posts").select(_COLS).eq("user_id", user_id).execute().data

    # Public posts (not own)
    public = supa.table("posts").select(_COLS).eq("visibility", "public").neq("user_id", user_id).execute().data

    # Friends' posts (friends + public visibility)
    friend_ids_res = supa.table("friends").select("friend_id").eq("user_id", user_id).execute().data
    friend_ids = [r["friend_id"] for r in friend_ids_res]
    friends_posts = []
    if friend_ids:
        friends_posts = supa.table("posts").select(_COLS).in_("user_id", friend_ids).in_("visibility", ["friends", "public"]).execute().data

    # Circle posts (where user is a member)
    circle_ids_res = supa.table("circle_members").select("circle_id").eq("user_id", user_id).execute().data
    circle_ids = [r["circle_id"] for r in circle_ids_res]
    circle_posts = []
    if circle_ids:
        circle_posts = supa.table("posts").select(_COLS).in_("circle_id", circle_ids).eq("visibility", "circle").neq("user_id", user_id).execute().data

    # Merge and deduplicate
    seen = set()
    merged = []
    for p in own + public + friends_posts + circle_posts:
        if p["id"] not in seen:
            seen.add(p["id"])
            merged.append(p)

    # Sort by created_at desc, apply pagination
    merged.sort(key=lambda p: p.get("created_at") or "", reverse=True)
    page = merged[offset:offset + limit]

    # Bulk-fetch author emails
    author_ids = list({p["user_id"] for p in page})
    users_map = {}
    if author_ids:
        users_res = supa.table("users").select("id, email").in_("id", author_ids).execute().data
        users_map = {u["id"]: u["email"] for u in users_res}

    posts = []
    for p in page:
        post_id = p["id"]

        images_res = supa.table("post_images").select("image_path").eq("post_id", post_id).order("id").execute().data
        images = [r["image_path"] for r in images_res]

        likes_res = supa.table("post_likes").select("user_id", count="exact").eq("post_id", post_id).execute()
        like_count = likes_res.count or 0

        liked_res = supa.table("post_likes").select("user_id").eq("post_id", post_id).eq("user_id", user_id).execute().data
        liked = len(liked_res) > 0

        posts.append({
            "id":         post_id,
            "user_id":    p["user_id"],
            "user_email": users_map.get(p["user_id"], ""),
            "caption":    p["caption"],
            "visibility": p["visibility"],
            "outfit_id":  p["outfit_id"],
            "circle_id":  p["circle_id"],
            "created_at": p["created_at"],
            "images":     images,
            "like_count": like_count,
            "liked":      liked,
        })

    return posts


def toggle_like(post_id, user_id):
    supa = get_supa()
    existing = supa.table("post_likes").select("user_id").eq("post_id", post_id).eq("user_id", user_id).execute().data
    if existing:
        supa.table("post_likes").delete().eq("post_id", post_id).eq("user_id", user_id).execute()
        return False
    else:
        supa.table("post_likes").insert({"post_id": post_id, "user_id": user_id}).execute()
        return True


def delete_post(post_id, user_id):
    result = get_supa().table("posts").delete().eq("id", post_id).eq("user_id", user_id).execute()
    return len(result.data) > 0
