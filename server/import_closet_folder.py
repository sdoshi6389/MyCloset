"""Import a folder of photos into one account's closet.

Usage (from server/):
    python import_closet_folder.py --user 5 --folder "C:\\path\\to\\photos" --limit 5
    python import_closet_folder.py --user 5 --folder "C:\\path\\to\\photos"

Runs the same path an upload takes -- normalise, row, Storage, tag OCR, GPT
metadata and icon, CLIP embedding -- rather than writing rows directly, so an
imported item is indistinguishable from an uploaded one.

Each item costs a GPT-4o vision call and a gpt-image-1 edit, so --limit exists
to try a handful before committing to the whole folder. Already-imported
filenames are skipped, which makes a second run a resume rather than a repeat.
"""
import os
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from werkzeug.utils import secure_filename

from closet import UPLOAD_FOLDER, _normalise_photo, _finish_upload
from db import get_supa

EXTS = (".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp")


def _arg(flag, default=None):
    for i, a in enumerate(sys.argv):
        if a == flag and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


USER = int(_arg("--user", "0") or 0)
FOLDER = _arg("--folder")
LIMIT = int(_arg("--limit", "0") or 0)
WORKERS = int(_arg("--workers", "4") or 4)


def _warm() -> None:
    """Load the shared models before the pool starts.

    Four workers racing into a cold model loader is how some of them end up
    silently skipping tag OCR: the loader marks itself tried before it has
    finished, so whoever arrives second sees no model and moves on.
    """
    t = time.time()
    try:
        from callable_embedding import encode_text
        encode_text("warmup")
        print(f"  CLIP warm in {time.time() - t:.1f}s")
    except Exception as e:
        print(f"  CLIP warm failed: {e}")
    t = time.time()
    try:
        from ocr_utils import _ensure_ocr_models
        ok = _ensure_ocr_models()
        print(f"  tag OCR {'warm' if ok else 'unavailable'} in {time.time() - t:.1f}s")
    except Exception as e:
        print(f"  tag OCR warm failed: {e}")


def _one(src: str, user_id: int) -> tuple[str, str, str]:
    """(source name, stored name, status)."""
    base = os.path.basename(src)
    name = secure_filename(base).lower()
    folder = os.path.join(UPLOAD_FOLDER, str(user_id))
    os.makedirs(folder, exist_ok=True)
    dest = os.path.join(folder, name)
    try:
        shutil.copyfile(src, dest)
    except Exception as e:
        return base, "", f"copy failed: {e}"

    try:
        dest, name = _normalise_photo(dest, name)
    except Exception as e:
        return base, name, f"normalise failed: {e}"

    try:
        row = (get_supa().table("closet_items").upsert({
            "user_id": user_id, "filename": name, "filepath": dest,
        }, on_conflict="user_id,filename").execute().data or [None])[0]
        if not row:
            return base, name, "upsert returned nothing"
    except Exception as e:
        return base, name, f"upsert failed: {e}"

    try:
        _finish_upload(dest, name, user_id, bool(row.get("icon_path")), False)
    except Exception as e:
        return base, name, f"pipeline failed: {type(e).__name__}: {e}"
    return base, name, "ok"


def main() -> None:
    if not USER or not FOLDER:
        print("give --user <id> and --folder <path>")
        return
    if not os.path.isdir(FOLDER):
        print(f"no folder at {FOLDER}")
        return

    files = sorted(os.path.join(FOLDER, f) for f in os.listdir(FOLDER)
                   if f.lower().endswith(EXTS))
    supa = get_supa()
    have = {r["filename"] for r in
            ((supa.table("closet_items").select("filename")
              .eq("user_id", USER).execute().data) or [])}

    todo = []
    for src in files:
        name = secure_filename(os.path.basename(src)).lower()
        stem = os.path.splitext(name)[0]
        if name in have or f"{stem}.jpg" in have or f"{stem}.png" in have:
            continue
        todo.append(src)

    print(f"{len(files)} photos in the folder, {len(have)} already in the closet, "
          f"{len(todo)} to import")
    if LIMIT:
        todo = todo[:LIMIT]
        print(f"  --limit {LIMIT}: doing {len(todo)} of them")
    if not todo:
        print("nothing to do")
        return

    print(f"warming models before {WORKERS} workers start:")
    _warm()

    t0 = time.time()
    done, failed = 0, []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {ex.submit(_one, src, USER): src for src in todo}
        for fut in as_completed(futures):
            base, name, status = fut.result()
            done += 1
            if status != "ok":
                failed.append((base, status))
            rate = (time.time() - t0) / done
            left = (len(todo) - done) * rate
            print(f"  [{done:>3}/{len(todo)}] {base[:28]:<28} -> {name[:28]:<28} "
                  f"{status[:40]:<40} ~{left / 60:.0f}m left", flush=True)

    print(f"\nimported {done - len(failed)} of {len(todo)} "
          f"in {(time.time() - t0) / 60:.1f} min")
    if failed:
        print("failures:")
        for base, why in failed:
            print(f"   {base}: {why}")


if __name__ == "__main__":
    main()
