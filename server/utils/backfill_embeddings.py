"""
Backfill CLIP embeddings for all products in Supabase that are missing them.

Discovers every products_* table, checks which ones have a combined_embedding
column, generates CLIP embeddings for rows that are missing one, and updates
them in place.

Rows that were already attempted (embedding_tried = TRUE) are skipped so
re-running the script never wastes time on products with bad image URLs.

Run from the server/ directory:
    python utils/backfill_embeddings.py

Optional flags:
    --table products_gymshark_mens   only process one table
    --limit 100                      stop after N rows (for testing)
    --sql-only                       just print ALTER TABLE SQL, don't backfill
    --retry                          re-attempt previously skipped rows too
"""

import os
import sys
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests as _requests
from db import get_supa
from config import SUPABASE_URL, SUPABASE_SERVICE_KEY

PAGE  = 500   # rows fetched per Supabase query
BATCH = 20    # rows updated per Supabase upsert


# ── Schema discovery ───────────────────────────────────────────────────────────

def _fetch_schema() -> dict:
    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    }
    res = _requests.get(f"{SUPABASE_URL}/rest/v1/", headers=headers, timeout=10)
    res.raise_for_status()
    return res.json()


def _discover_tables(schema: dict) -> list[str]:
    paths = schema.get("paths", {})
    return sorted(p.strip("/") for p in paths if p.strip("/").startswith("products_"))


def _table_has_col(schema: dict, table: str, col: str) -> bool:
    defs = schema.get("definitions", {})
    props = defs.get(table, {}).get("properties", {})
    return col in props


# ── Backfill ───────────────────────────────────────────────────────────────────

def backfill_table(
    supa, table: str, limit: int | None, has_tried_col: bool, retry: bool
) -> tuple[int, int]:
    """Returns (updated, skipped)."""
    from utils.clip_embedder import generate_embedding

    print(f"\n📦 {table}")
    updated = 0
    skipped = 0
    offset  = 0

    while True:
        q = (
            supa.table(table)
            .select("id, title, image")
            .is_("combined_embedding", "null")
        )
        if has_tried_col and not retry:
            q = q.eq("embedding_tried", False)
        res = q.range(offset, offset + PAGE - 1).execute()
        rows = res.data or []
        if not rows:
            break

        batch_updates = []
        skip_ids      = []

        for row in rows:
            if limit is not None and updated >= limit:
                break

            title = row.get("title") or ""
            image = row.get("image") or ""

            if not image.startswith("http"):
                skip_ids.append(row["id"])
                skipped += 1
                continue

            emb = generate_embedding(title, image)
            if emb is None:
                skip_ids.append(row["id"])
                skipped += 1
                continue

            batch_updates.append({"id": row["id"], "combined_embedding": emb})
            updated += 1

            if len(batch_updates) >= BATCH:
                _flush(supa, table, batch_updates)
                batch_updates = []
                print(f"  … {updated} updated so far")

        if batch_updates:
            _flush(supa, table, batch_updates)

        # Mark skipped rows so future runs don't re-attempt them
        if has_tried_col and skip_ids:
            _flush_tried(supa, table, skip_ids)

        if limit is not None and updated >= limit:
            break
        if len(rows) < PAGE:
            break

        # When embedding_tried is tracked, processed rows disappear from the
        # query on the next iteration, so always restart from offset 0.
        # Without the column, rows stay NULL and we advance the offset normally.
        offset = 0 if has_tried_col else offset + PAGE

    print(f"  ✅ {updated} updated, {skipped} skipped")
    return updated, skipped


def _flush(supa, table: str, batch: list) -> None:
    for item in batch:
        supa.table(table).update(
            {"combined_embedding": item["combined_embedding"]}
        ).eq("id", item["id"]).execute()


def _flush_tried(supa, table: str, ids: list) -> None:
    for sid in ids:
        supa.table(table).update({"embedding_tried": True}).eq("id", sid).execute()


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--table",    help="Only process this table")
    parser.add_argument("--limit",    type=int, help="Stop after N rows per table (testing)")
    parser.add_argument("--sql-only", action="store_true", help="Print ALTER TABLE SQL and exit")
    parser.add_argument("--retry",    action="store_true", help="Re-attempt previously skipped rows")
    args = parser.parse_args()

    print("Fetching Supabase schema…")
    schema = _fetch_schema()

    if args.table:
        tables = [args.table]
    else:
        tables = _discover_tables(schema)
        print(f"Found {len(tables)} products_* tables\n")

    ready      = [t for t in tables if _table_has_col(schema, t, "combined_embedding")]
    needs_col  = [t for t in tables if not _table_has_col(schema, t, "combined_embedding")]
    tried_cols = {t for t in tables if _table_has_col(schema, t, "embedding_tried")}

    if needs_col:
        print("⚠️  The following tables are missing the combined_embedding column.")
        print("    Run this SQL in the Supabase SQL editor, then re-run this script:\n")
        for t in needs_col:
            print(f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS combined_embedding FLOAT8[];")
            print(f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS embedding_tried BOOLEAN NOT NULL DEFAULT FALSE;")
        print()

    if args.sql_only:
        return

    if not ready:
        print("No tables ready to backfill (all missing the column). Run the SQL above first.")
        return

    print(f"Tables ready to backfill: {ready}\n")
    if args.retry:
        print("  --retry: will re-attempt all previously skipped rows\n")

    supa = get_supa()

    total_updated = 0
    total_skipped = 0

    for table in ready:
        u, s = backfill_table(
            supa, table, args.limit,
            has_tried_col=table in tried_cols,
            retry=args.retry,
        )
        total_updated += u
        total_skipped += s

    print(f"\n🎉 Done — {total_updated} embeddings generated, {total_skipped} skipped")


if __name__ == "__main__":
    main()
