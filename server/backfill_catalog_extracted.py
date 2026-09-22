"""One-off: push locally-extracted catalog icons to Storage and repoint the cache.

Extractions used to be written only to this machine's catalog_extracted/ folder,
so deployed containers 404'd on them and saved outfits showed broken images.

Usage (from server/):  python backfill_catalog_extracted.py
"""
import os

from bg_remove import CACHE_DIR
from db import get_supa
from storage_utils import upload_bytes, public_url


def main() -> None:
    supa = get_supa()
    rows = supa.table("catalog_icon_cache").select("cache_key, icon_path").execute().data or []
    print(f"{len(rows)} cache rows")

    uploaded = repointed = skipped = missing = 0
    for i, r in enumerate(rows, 1):
        p = r.get("icon_path") or ""
        if p.startswith("http"):
            skipped += 1
            continue

        name = p.replace("\\", "/").split("/")[-1]
        local = p if os.path.isfile(p) else os.path.join(CACHE_DIR, name)
        if not os.path.isfile(local):
            missing += 1
            continue

        with open(local, "rb") as f:
            url = upload_bytes(f.read(), f"catalog_extracted/{name}", "image/png")
        if not url:
            continue
        uploaded += 1

        try:
            supa.table("catalog_icon_cache").update({"icon_path": url}).eq(
                "cache_key", r["cache_key"]).execute()
            repointed += 1
        except Exception as e:
            print(f"  repoint failed for {name[:40]}: {e}")

        if i % 10 == 0:
            print(f"  [{i}/{len(rows)}] uploaded={uploaded} repointed={repointed}")

    # Any extracted file on disk with no cache row still needs to exist in Storage,
    # because saved outfits reference it by filename via /catalog_extracted/<name>.
    orphans = 0
    known = {(r.get("icon_path") or "").replace("\\", "/").split("/")[-1] for r in rows}
    for fn in os.listdir(CACHE_DIR) if os.path.isdir(CACHE_DIR) else []:
        if not fn.lower().endswith(".png") or fn in known:
            continue
        with open(os.path.join(CACHE_DIR, fn), "rb") as f:
            if upload_bytes(f.read(), f"catalog_extracted/{fn}", "image/png"):
                orphans += 1

    print(f"\nuploaded={uploaded} repointed={repointed} skipped(already url)={skipped} "
          f"missing_locally={missing} orphan_files_uploaded={orphans}")


if __name__ == "__main__":
    main()
