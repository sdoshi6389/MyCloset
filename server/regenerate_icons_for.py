"""Regenerate the icon for specific closet items, reusing their stored caption.

Usage (from server/):
    python regenerate_icons_for.py --user 5 --match "tank top"          # list only
    python regenerate_icons_for.py --user 5 --match "tank top" --apply
    python regenerate_icons_for.py --user 5 --match "tank top" --apply --limit 2

Only the image is redone -- the caption, brand and tags already on the row are
reused, so there is no second vision call. One gpt-image-1 edit per item, which
is why this lists and stops unless given --apply.
"""
import os
import sys

from closet import _ensure_local_file, UPLOAD_FOLDER
from db import get_supa
from paths import ICON_OUTPUTS_DIR
from replicate_icon_clothing import (build_icon_prompt, generate_icon_via_gpt,
                                     icon_stem_for)
from storage_utils import upload_icon


def _arg(flag, default=None):
    for i, a in enumerate(sys.argv):
        if a == flag and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


USER = int(_arg("--user", "0") or 0)
MATCH = (_arg("--match") or "").lower()
LIMIT = int(_arg("--limit", "0") or 0)
APPLY = "--apply" in sys.argv


def main() -> None:
    if not USER or not MATCH:
        print("give --user <id> and --match <text>")
        return

    supa = get_supa()
    rows = (supa.table("closet_items")
            .select("id, filename, type, subcategory, caption, matched_title, icon_path")
            .eq("user_id", USER).execute().data) or []
    hits = [r for r in rows
            if MATCH in " ".join(str(r.get(k) or "") for k in
                                 ("type", "subcategory", "caption", "matched_title")).lower()]
    if LIMIT:
        hits = hits[:LIMIT]

    print(f"{len(hits)} item(s) match {MATCH!r}")
    for r in hits:
        print(f"   {r['filename']:<20} {str(r.get('matched_title') or r.get('caption'))[:46]}")
    if not hits:
        return
    print(f"\none gpt-image-1 edit each, about ${0.07 * len(hits):.2f} in total")
    if not APPLY:
        print("listing only; pass --apply to regenerate")
        return

    ok = 0
    for r in hits:
        caption = (r.get("caption") or r.get("matched_title")
                   or r["filename"].rsplit(".", 1)[0].replace("_", " "))
        path = _ensure_local_file(USER, r["filename"])
        if not path:
            print(f"  {r['filename']}: no source photo, skipped")
            continue
        is_temp = not path.startswith(os.path.join(UPLOAD_FOLDER, str(USER)))
        try:
            stem = icon_stem_for(USER, r["filename"])
            icon = generate_icon_via_gpt(build_icon_prompt(caption), path,
                                         ICON_OUTPUTS_DIR, icon_stem=stem)
            if not icon:
                print(f"  {r['filename']}: generation returned nothing")
                continue
            upload_icon(icon, os.path.basename(icon))
            supa.table("closet_items").update({"icon_path": icon}) \
                .eq("id", r["id"]).execute()
            print(f"  {r['filename']} -> {os.path.basename(icon)}")
            ok += 1
        except Exception as e:
            print(f"  {r['filename']}: {type(e).__name__}: {e}")
        finally:
            if is_temp and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass

    print(f"\nregenerated {ok} of {len(hits)}")
    if ok:
        print("Icons are cached for a day; hard refresh to see them.")


if __name__ == "__main__":
    main()
