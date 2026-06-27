"""Shared Supabase insert helper used by all scrapers.

Requires the upsert_brand_products() function to be installed in Supabase once.
SQL is in supabase_brand_schema.sql.
"""
import os
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

_client = None


def get_client():
    global _client
    if _client is None:
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


def ensure_table(table):
    """
    Create the brand product table + unique index if they don't exist.
    Calling with an empty products list is a no-op for data but will
    create the table structure if missing.
    """
    get_client().rpc("upsert_brand_products", {"table_name": table, "products": []}).execute()


def insert_products(table, rows, batch_size=500):
    """
    Insert rows into table via the upsert_brand_products() Postgres function.
    Duplicates are silently skipped (ON CONFLICT DO NOTHING inside the function).
    Table is auto-created if it doesn't exist.
    Returns (inserted, skipped).
    """
    if not rows:
        return 0, 0

    supa = get_client()

    clean = [
        {
            "title": r.get("title") or "",
            "price": r.get("price") or "",
            "color": r.get("color") or "",
            "url":   r.get("url")   or "",
            "image": r.get("image") or "",
        }
        for r in rows
    ]

    total_inserted = 0
    for i in range(0, len(clean), batch_size):
        batch = clean[i : i + batch_size]
        try:
            result = supa.rpc(
                "upsert_brand_products",
                {"table_name": table, "products": batch},
            ).execute()
            total_inserted += result.data or 0
        except Exception as e:
            print(f"  DB error (batch {i // batch_size + 1}): {e}", flush=True)

    skipped = len(clean) - total_inserted
    return total_inserted, skipped
