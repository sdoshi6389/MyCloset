"""Archive one account's closet, then empty it.

Usage (from server/):
    python archive_and_wipe_closet.py --user 5              # archive only, change nothing
    python archive_and_wipe_closet.py --user 5 --wipe       # archive, then delete

The archive is the point: closet rows, saved outfits and wear history go to a
timestamped JSON file, and the original photos move to a sibling folder rather
than being removed. Storage objects are left alone -- nothing references them
once the rows are gone, and keeping them means a wrong call here is recoverable.
"""
import json
import os
import shutil
import sys
from datetime import datetime, timezone

from db import get_supa

ARCHIVE_ROOT = "closet_archives"
UPLOAD_FOLDER = "uploaded_closets"


def _arg(flag, default=None):
    for i, a in enumerate(sys.argv):
        if a == flag and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


USER = int(_arg("--user", "0") or 0)
WIPE = "--wipe" in sys.argv


def main() -> None:
    if not USER:
        print("give --user <id>")
        return

    supa = get_supa()
    who = (supa.table("users").select("id, email").eq("id", USER)
           .execute().data or [None])[0]
    if not who:
        print(f"no account with id {USER}")
        return
    print(f"account {USER}  {who.get('email')}")

    items = (supa.table("closet_items").select("*").eq("user_id", USER)
             .execute().data) or []
    outfits = (supa.table("outfits").select("*").eq("user_id", USER)
               .execute().data) or []
    outfit_ids = [o["id"] for o in outfits]
    outfit_items = []
    if outfit_ids:
        outfit_items = (supa.table("outfit_items").select("*")
                        .in_("outfit_id", outfit_ids).execute().data) or []

    wears, wear_items = [], []
    try:
        wears = (supa.table("outfit_wears").select("*").eq("user_id", USER)
                 .execute().data) or []
        wear_ids = [w["id"] for w in wears]
        if wear_ids:
            wear_items = (supa.table("outfit_wear_items").select("*")
                          .in_("wear_id", wear_ids).execute().data) or []
    except Exception as e:
        print(f"  (wear tables unreadable: {type(e).__name__})")

    print(f"  closet_items {len(items)}   outfits {len(outfits)} "
          f"({len(outfit_items)} links)   wears {len(wears)} ({len(wear_items)} links)")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    os.makedirs(ARCHIVE_ROOT, exist_ok=True)
    out = os.path.join(ARCHIVE_ROOT, f"user{USER}-{stamp}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({
            "archived_at": stamp,
            "user": who,
            "closet_items": items,
            "outfits": outfits,
            "outfit_items": outfit_items,
            "outfit_wears": wears,
            "outfit_wear_items": wear_items,
        }, f, indent=1, default=str)
    print(f"  rows -> {out}  ({os.path.getsize(out) / 1e6:.1f} MB)")

    photos = os.path.join(UPLOAD_FOLDER, str(USER))
    moved = os.path.join(ARCHIVE_ROOT, f"user{USER}-{stamp}-photos")
    if os.path.isdir(photos) and os.listdir(photos):
        n = len(os.listdir(photos))
        size = sum(os.path.getsize(os.path.join(photos, f))
                   for f in os.listdir(photos)) / 1e6
        if WIPE:
            shutil.move(photos, moved)
            os.makedirs(photos, exist_ok=True)
            print(f"  photos -> {moved}  ({n} files, {size:.0f} MB)")
        else:
            print(f"  photos would move to {moved}  ({n} files, {size:.0f} MB)")

    if not WIPE:
        print("\ndry run; pass --wipe to delete after archiving")
        return

    # Children first: nothing here cascades, so the order matters.
    if wear_items:
        supa.table("outfit_wear_items").delete() \
            .in_("wear_id", [w["id"] for w in wears]).execute()
    if wears:
        supa.table("outfit_wears").delete().eq("user_id", USER).execute()
    if outfit_items:
        supa.table("outfit_items").delete().in_("outfit_id", outfit_ids).execute()
    if outfits:
        supa.table("outfits").delete().eq("user_id", USER).execute()
    if items:
        supa.table("closet_items").delete().eq("user_id", USER).execute()

    left = len((supa.table("closet_items").select("id").eq("user_id", USER)
                .execute().data) or [])
    print(f"\nwiped. closet_items remaining for user {USER}: {left}")
    print("Storage objects were left in place; nothing points at them now.")


if __name__ == "__main__":
    main()
