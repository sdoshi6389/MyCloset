"""Tidy the brand column: one spelling per brand, and no label scraps.

Usage (from server/):
    python backfill_brands.py --user 5          # show what would change
    python backfill_brands.py --user 5 --apply
    python backfill_brands.py --all --apply

Costs nothing: it re-reads what is already stored rather than asking GPT again.
A size spotted in the brand column or in the tag text is moved to the size
column instead of being thrown away.
"""
import sys
from collections import Counter

from db import get_supa
from garment_text import clean_brand, normalise_size


def _arg(flag, default=None):
    for i, a in enumerate(sys.argv):
        if a == flag and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


USER = int(_arg("--user", "0") or 0)
ALL = "--all" in sys.argv
APPLY = "--apply" in sys.argv


def main() -> None:
    if not USER and not ALL:
        print("give --user <id> or --all")
        return

    supa = get_supa()
    q = supa.table("closet_items").select("id, user_id, filename, brand, size, tag_text")
    if not ALL:
        q = q.eq("user_id", USER)
    rows = q.execute().data or []
    print(f"{len(rows)} items\n")

    changes, sized, cleared = [], [], []
    for r in rows:
        old = r.get("brand")
        new = clean_brand(old)
        patch = {}
        if new != old:
            patch["brand"] = new
            (cleared if new is None else changes).append((r, old, new))
        # A size sitting in the brand column, or legible in the tag, belongs in
        # the size column -- it was being discarded either way.
        if not r.get("size"):
            size = normalise_size(old) or normalise_size(r.get("tag_text"))
            if size:
                patch["size"] = size
                sized.append((r, size))
        if patch and APPLY:
            supa.table("closet_items").update(patch).eq("id", r["id"]).execute()

    print(f"respelled {len(changes)}:")
    for r, old, new in changes[:30]:
        print(f"   {r['filename']:<20} {old!r} -> {new!r}")
    print(f"\ndropped as not a brand {len(cleared)}:")
    for r, old, _ in cleared[:30]:
        print(f"   {r['filename']:<20} {old!r}")
    print(f"\nsize recovered {len(sized)}:")
    for r, size in sized[:30]:
        print(f"   {r['filename']:<20} -> {size!r}")

    before = Counter((r.get("brand") or "(none)") for r in rows)
    after = Counter((clean_brand(r.get("brand")) or "(none)") for r in rows)
    print(f"\ndistinct brand values: {len(before)} -> {len(after)}")
    print(f"items with no brand:   {before['(none)'] + before.get('Unknown', 0)} "
          f"-> {after['(none)']}")

    if not APPLY:
        print("\ndry run; pass --apply to write")


if __name__ == "__main__":
    main()
