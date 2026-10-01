"""One-off: give each item its own icon again, where several items share one.

Icons used to be named after the first 60 characters of the generation prompt.
Every prompt opens with the same instruction and the caption that identifies the
garment falls past that cut, so items generated this way all wrote to a single
file and overwrote each other. Naming is fixed going forward; this repairs the
items that already collided.

Usage (from server/):
    python repair_shared_icons.py              # list what is affected, change nothing
    python repair_shared_icons.py --apply      # regenerate those icons
    python repair_shared_icons.py --apply --user 5
    python repair_shared_icons.py --apply --id 81 --id 82

Only items whose icon file is shared with another item are touched; everything
else is left alone. Each repaired item costs one gpt-image-1 edit call, so the
dry run prints the count before anything is spent.
"""
import os
import sys
from collections import defaultdict

from db import get_supa
from paths import ICON_OUTPUTS_DIR
from replicate_icon_clothing import (build_icon_prompt, generate_icon_via_gpt,
                                     icon_stem_for)
from storage_utils import upload_icon

APPLY = "--apply" in sys.argv


def _arg_values(flag: str) -> list[str]:
    out = []
    for i, a in enumerate(sys.argv):
        if a == flag and i + 1 < len(sys.argv):
            out.append(sys.argv[i + 1])
    return out


ONLY_USERS = {int(v) for v in _arg_values("--user")}
ONLY_IDS = {int(v) for v in _arg_values("--id")}


def _basename(path: str) -> str:
    return path.replace("\\", "/").split("/")[-1]


def _local_photo(user_id: int, filename: str) -> tuple[str | None, bool]:
    """(path, is_temp). Falls back to the Storage copy on a deployed box."""
    from closet import _ensure_local_file, UPLOAD_FOLDER
    path = _ensure_local_file(user_id, filename)
    if not path:
        return None, False
    is_temp = not path.startswith(os.path.join(UPLOAD_FOLDER, str(user_id)))
    return path, is_temp


def main() -> None:
    supa = get_supa()
    rows = (supa.table("closet_items")
            .select("id, user_id, filename, icon_path, caption, matched_title")
            .not_.is_("icon_path", "null").execute().data) or []

    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r.get("icon_path"):
            groups[_basename(r["icon_path"])].append(r)

    shared = {name: items for name, items in groups.items() if len(items) > 1}
    affected = [r for items in shared.values() for r in items]
    if ONLY_USERS:
        affected = [r for r in affected if r["user_id"] in ONLY_USERS]
    if ONLY_IDS:
        affected = [r for r in affected if r["id"] in ONLY_IDS]

    print(f"{len(rows)} items with an icon, {len(shared)} icon files shared by "
          f"more than one item")
    for name, items in sorted(shared.items(), key=lambda kv: -len(kv[1])):
        print(f"\n  {name}")
        for r in items:
            mark = "  <- will repair" if r in affected else ""
            label = r.get("matched_title") or r.get("caption") or ""
            print(f"     user {r['user_id']}  id {r['id']:<5} "
                  f"{r['filename'][:32]:<32} {str(label)[:40]}{mark}")

    if not affected:
        print("\nnothing to repair")
        return

    print(f"\n{len(affected)} item(s) to regenerate — one gpt-image-1 edit call each")
    if not APPLY:
        print("dry run; pass --apply to actually regenerate")
        return

    ok = failed = 0
    for r in affected:
        uid, fn = r["user_id"], r["filename"]
        caption = (r.get("caption") or r.get("matched_title")
                   or fn.rsplit(".", 1)[0].replace("_", " ").strip() or "clothing item")
        photo, is_temp = _local_photo(uid, fn)
        if not photo:
            print(f"  id {r['id']}: no source photo, skipped")
            failed += 1
            continue
        try:
            stem = icon_stem_for(uid, fn)
            icon_path = generate_icon_via_gpt(build_icon_prompt(caption), photo,
                                              ICON_OUTPUTS_DIR, icon_stem=stem)
            if not icon_path:
                print(f"  id {r['id']}: generation returned nothing, skipped")
                failed += 1
                continue
            upload_icon(icon_path, _basename(icon_path))
            supa.table("closet_items").update({"icon_path": icon_path}) \
                .eq("id", r["id"]).execute()
            print(f"  id {r['id']} {fn} -> {_basename(icon_path)}")
            ok += 1
        except Exception as e:
            print(f"  id {r['id']}: {type(e).__name__}: {e}")
            failed += 1
        finally:
            if is_temp and photo and os.path.exists(photo):
                try:
                    os.remove(photo)
                except OSError:
                    pass

    print(f"\nrepaired {ok}, failed {failed}")
    if ok:
        print("Icons are cached for a day, so a hard refresh (Ctrl+Shift+R) "
              "shows them straight away.")


if __name__ == "__main__":
    main()
