"""One-off: generate 320px thumbs for every icon that predates thumbnail support.

Usage (from server/):  python backfill_icon_thumbs.py [--force]

Reads each icon from local disk when present, otherwise from the Storage CDN,
and uploads icons/thumb/<name>. Existing thumbs are skipped unless --force.
"""
import os
import sys
import requests

from db import get_supa
from paths import ICON_OUTPUTS_DIR
from storage_utils import public_url, thumb_url, upload_thumb

FORCE = "--force" in sys.argv


def _local_icon(icon_path: str, name: str) -> str | None:
    for cand in (icon_path, os.path.join(ICON_OUTPUTS_DIR, name)):
        if cand and os.path.isfile(cand):
            return cand
    return None


def main() -> None:
    rows = get_supa().table("closet_items").select("id, icon_path").not_.is_("icon_path", "null").execute().data or []
    names = sorted({r["icon_path"].replace("\\", "/").split("/")[-1] for r in rows if r.get("icon_path")})
    print(f"{len(names)} distinct icons")

    done = skipped = failed = 0
    for i, name in enumerate(names, 1):
        if not FORCE:
            try:
                if requests.head(thumb_url(name), timeout=20).status_code == 200:
                    skipped += 1
                    continue
            except Exception:
                pass

        src = None
        row = next((r for r in rows if r["icon_path"] and r["icon_path"].endswith(name)), None)
        local = _local_icon(row["icon_path"] if row else None, name)
        if local:
            src = local
        else:
            try:
                r = requests.get(public_url(f"icons/{name}"), timeout=60)
                if r.status_code == 200:
                    src = r.content
            except Exception:
                pass
        if src is None:
            failed += 1
            print(f"  [{i}/{len(names)}] no source for {name[:60]}")
            continue

        if upload_thumb(src, name):
            done += 1
            print(f"  [{i}/{len(names)}] ok {name[:60]}")
        else:
            failed += 1

    print(f"\ndone={done} skipped={skipped} failed={failed}")


if __name__ == "__main__":
    main()
