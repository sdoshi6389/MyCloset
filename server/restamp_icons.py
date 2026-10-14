"""Give every stored icon a name that depends on its pixels.

Usage (from server/):
    python restamp_icons.py --user 5
    python restamp_icons.py --user 5 --apply

Icons are served with a day-long cache and used to keep their filename when
regenerated, so a corrected icon stayed invisible to anyone holding the old one.
Once a name carries a hash of its bytes, a changed icon is a different URL and
no cache can serve the wrong thing.

Costs nothing: it re-publishes the pixels already stored, from the local copy
where there is one and from Storage otherwise. Old objects are left in place --
nothing points at them, and deleting them is a separate decision.
"""
import hashlib
import os
import re
import sys

import requests

from db import get_supa
from paths import ICON_OUTPUTS_DIR
from storage_utils import icon_urls, upload_icon


def _arg(flag, default=None):
    for i, a in enumerate(sys.argv):
        if a == flag and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


USER = int(_arg("--user", "0") or 0)
APPLY = "--apply" in sys.argv


def _local_copy(icon_path: str) -> str | None:
    for cand in (icon_path, os.path.join(ICON_OUTPUTS_DIR, os.path.basename(icon_path or ""))):
        if cand and os.path.isfile(cand):
            return cand
    return None


def main() -> None:
    if not USER:
        print("give --user <id>")
        return

    supa = get_supa()
    rows = (supa.table("closet_items").select("id, filename, icon_path")
            .eq("user_id", USER).not_.is_("icon_path", "null").execute().data) or []
    print(f"{len(rows)} items with an icon\n")

    done = skipped = failed = 0
    for r in rows:
        icon = r["icon_path"] or ""
        base = os.path.basename(icon.replace("\\", "/"))
        stem_only, ext_only = os.path.splitext(base)
        if re.search(r"\.v[0-9a-f]{8}$", stem_only):
            skipped += 1
            continue

        src = _local_copy(icon)
        data = None
        if src:
            data = open(src, "rb").read()
        else:
            full, _ = icon_urls(icon)
            if full:
                try:
                    resp = requests.get(full, timeout=60)
                    if resp.status_code == 200:
                        data = resp.content
                except Exception as e:
                    print(f"  {r['filename']}: fetch failed: {e}")
        if not data:
            print(f"  {r['filename']}: no pixels anywhere, skipped")
            failed += 1
            continue

        # Strip a failed "~" stamp from the earlier run before adding a good one.
        stem = re.sub(r"[.~]v?[0-9a-f]{8}$", "", stem_only)
        ext = ext_only
        new_base = f"{stem}.v{hashlib.sha1(data).hexdigest()[:8]}{ext}"
        new_local = os.path.join(ICON_OUTPUTS_DIR, new_base)

        if not APPLY:
            print(f"  {r['filename']:<18} {base} -> {new_base}")
            done += 1
            continue

        try:
            with open(new_local, "wb") as f:
                f.write(data)
            # Point the row at the new name only once both objects are really
            # there. The first run updated regardless, so a rejected key left
            # the item pointing at nothing and its icon vanished.
            full_url, thumb_url_ = upload_icon(new_local, new_base)
            if not (full_url and thumb_url_):
                print(f"  {r['filename']}: upload did not land, row left alone")
                failed += 1
                continue
            supa.table("closet_items").update({"icon_path": new_local}) \
                .eq("id", r["id"]).execute()
            print(f"  {r['filename']:<18} -> {new_base}")
            done += 1
        except Exception as e:
            print(f"  {r['filename']}: {type(e).__name__}: {e}")
            failed += 1

    print(f"\n{'restamped' if APPLY else 'would restamp'} {done}, "
          f"already stamped {skipped}, failed {failed}")
    if not APPLY:
        print("dry run; pass --apply to publish")


if __name__ == "__main__":
    main()
