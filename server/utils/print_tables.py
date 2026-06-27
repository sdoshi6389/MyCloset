"""
Print a summary of every products_* table in Supabase.

Run from the server/ directory:
    python utils/print_tables.py

Optional flags:
    --table products_gymshark_mens   only show one table
    --rows 5                         print N sample rows per table (default 0)
"""

import os
import sys
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests as _requests
from db import get_supa
from config import SUPABASE_URL, SUPABASE_SERVICE_KEY
from postgrest.exceptions import APIError as _APIError


def _discover_tables() -> list[str]:
    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    }
    res = _requests.get(f"{SUPABASE_URL}/rest/v1/", headers=headers, timeout=10)
    paths = res.json().get("paths", {})
    return sorted(p.strip("/") for p in paths if p.strip("/").startswith("products_"))


def _ensure_column(table: str) -> bool:
    """Call ensure_brand_table RPC to add combined_embedding if missing. Returns True on success."""
    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
    }
    try:
        r = _requests.post(
            f"{SUPABASE_URL}/rest/v1/rpc/ensure_brand_table",
            json={"tbl": table},
            headers=headers,
            timeout=10,
        )
        if r.ok:
            print(f"  [auto] added combined_embedding column to {table}")
            return True
        print(f"  [warn] ensure_brand_table({table}): {r.text}")
        return False
    except Exception as exc:
        print(f"  [warn] ensure_brand_table error for {table}: {exc}")
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--table", help="Only show this table")
    parser.add_argument("--rows",  type=int, default=0, help="Sample rows to print per table")
    args = parser.parse_args()

    supa = get_supa()

    if args.table:
        tables = [args.table]
    else:
        tables = _discover_tables()

    print(f"\nFound {len(tables)} products_* tables\n")
    print(f"  {'table':<35} {'rows':>6}  {'w/ emb':>6}  {'missing':>7}  {'done':>5}")
    print(f"  {'-'*35} {'-'*6}  {'-'*6}  {'-'*7}  {'-'*5}")

    total_rows = 0
    total_with = 0

    for table in tables:
        total_res = supa.table(table).select("*", count="exact").limit(0).execute()
        total     = total_res.count or 0

        emb_col_ok = True
        try:
            emb_res  = supa.table(table).select("*", count="exact").not_.is_("combined_embedding", "null").limit(0).execute()
            with_emb = emb_res.count or 0
        except _APIError as e:
            if e.code == "42703":
                emb_col_ok = _ensure_column(table)
                try:
                    emb_res  = supa.table(table).select("*", count="exact").not_.is_("combined_embedding", "null").limit(0).execute()
                    with_emb = emb_res.count or 0
                except Exception:
                    with_emb = 0
                    emb_col_ok = False
            else:
                raise

        missing = total - with_emb
        pct     = f"{with_emb/total*100:.0f}%" if total else "—"

        print(f"  {table:<35} {total:>6}  {with_emb:>6}  {missing:>7}  {pct:>5}")

        if args.rows > 0 and total > 0:
            select_cols = "id, title, price, image, combined_embedding" if emb_col_ok else "id, title, price, image"
            rows = supa.table(table).select(select_cols).limit(args.rows).execute().data or []
            for r in rows:
                emb = r.get("combined_embedding")
                emb_str = f"[{len(emb)}d]" if emb else "None"
                print(f"      id={r['id']}  {str(r.get('title',''))[:45]!r:<47}  emb={emb_str}")
            print()

        total_rows += total
        total_with += with_emb

    total_missing = total_rows - total_with
    total_pct     = f"{total_with/total_rows*100:.1f}%" if total_rows else "—"
    print(f"\n  {'TOTAL':<35} {total_rows:>6}  {total_with:>6}  {total_missing:>7}  {total_pct:>5}")


if __name__ == "__main__":
    main()
