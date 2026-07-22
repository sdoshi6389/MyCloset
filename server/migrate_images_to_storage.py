"""One-time migration: upload existing local closet images (originals + icons)
to Supabase Storage so the deployed app can serve them via the /static and
/icons redirects.

Run LOCALLY from the server/ directory, where uploaded_closets/ and icon_outputs/
live and server/.env is loaded:

    cd server
    ../myenv/Scripts/python.exe migrate_images_to_storage.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import get_supa
from storage_utils import upload_file, ensure_bucket, BUCKET

ensure_bucket()
supa = get_supa()

rows = (supa.table("closet_items")
        .select("user_id, filename, filepath, icon_path")
        .execute().data or [])
print(f"Migrating {len(rows)} closet items to bucket '{BUCKET}'…")

ok_img = miss_img = ok_icon = miss_icon = 0
for r in rows:
    uid, fn = r.get("user_id"), r.get("filename")
    fp, ip = r.get("filepath"), r.get("icon_path")

    # Original photo → {user_id}/{filename}
    local = fp if (fp and os.path.isfile(fp)) else (
        os.path.join("uploaded_closets", str(uid), fn) if fn else None)
    if fn and local and os.path.isfile(local):
        if upload_file(local, f"{uid}/{fn}"):
            ok_img += 1
        else:
            miss_img += 1
    elif fn:
        miss_img += 1
        print(f"  ⚠️  missing local original for {uid}/{fn}")

    # Icon → icons/{basename}
    if ip and os.path.isfile(ip):
        if upload_file(ip, f"icons/{os.path.basename(ip)}"):
            ok_icon += 1
        else:
            miss_icon += 1
    elif ip:
        miss_icon += 1
        print(f"  ⚠️  missing local icon file: {ip}")

print(f"\n✅ Done. Originals: {ok_img} uploaded, {miss_img} missing/failed. "
      f"Icons: {ok_icon} uploaded, {miss_icon} missing/failed.")
