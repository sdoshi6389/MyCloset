"""
Pull combined_embedding from local PostgreSQL brand databases and upload
them to Supabase (clearing + re-inserting each table with clip_embedding).

Brands that only have CSVs (no local PG) are skipped — they need CLIP
embeddings generated separately.

Run with:
  python import_embeddings_to_supabase.py
"""

import json
import os
import urllib.request
import urllib.error
import psycopg2
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# ── Supabase config ───────────────────────────────────────────────────────────
SUPABASE_URL = os.environ["LEGACY_EMBEDDINGS_SUPABASE_URL"]
SERVICE_KEY = os.environ["LEGACY_EMBEDDINGS_SERVICE_KEY"]

HEADERS = {
    "apikey": SERVICE_KEY,
    "Authorization": f"Bearer {SERVICE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=minimal",
}

# ── Local PostgreSQL config ───────────────────────────────────────────────────
PG = dict(user="postgres", password=os.environ["PG_PASSWORD"], host="localhost", port="5432")

# ── Mapping: local DB name -> Supabase table name ────────────────────────────
DB_TO_TABLE = {
    "gymshark_mens_full":       "products_gymshark_mens",
    "gymshark_womens_full":     "products_gymshark_womens",
    "hollister_mens_full":      "products_hollister_mens",
    "hollister_womens_full":    "products_hollister_womens",
    "essentials_mens":          "products_essentials_mens",
    "essentials_women":         "products_essentials_womens",
    "hm_women_products":        "products_hm_womens",
    "cottonon_men_products":    "products_cottonon_mens",
    "cottonon_women_products":  "products_cottonon_womens",
    "abercrombie_men_products": "products_abercrombie_mens",
    "abercrombie_women_products": "products_abercrombie_womens",
    "alo_men_products":         "products_alo_mens",
    "alo_women_products":       "products_alo_womens",
}

# Use small batches — each row has a 512-float embedding (~10KB JSON each)
BATCH_SIZE = 25


def sb_delete(table: str):
    """Delete all rows from a Supabase table."""
    url = f"{SUPABASE_URL}/rest/v1/{table}?id=neq.00000000-0000-0000-0000-000000000000"
    req = urllib.request.Request(url, headers=HEADERS, method="DELETE")
    try:
        with urllib.request.urlopen(req):
            pass
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        if e.code != 404:
            raise RuntimeError(f"DELETE failed {e.code}: {body}")


def sb_insert(table: str, rows: list):
    """Insert a batch of rows into a Supabase table."""
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    data = json.dumps(rows).encode()
    req = urllib.request.Request(url, data=data, headers=HEADERS, method="POST")
    try:
        with urllib.request.urlopen(req):
            pass
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"INSERT failed {e.code}: {e.read().decode()}")


def fetch_local(dbname: str) -> list:
    """Fetch all rows (with embeddings) from a local brand DB."""
    conn = psycopg2.connect(dbname=dbname, **PG)
    cur = conn.cursor()
    cur.execute("""
        SELECT title, price, color, url, image, combined_embedding
        FROM products
        WHERE combined_embedding IS NOT NULL
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def import_brand(dbname: str, table: str) -> int:
    print(f"  Fetching from local PG '{dbname}'...")
    local_rows = fetch_local(dbname)
    if not local_rows:
        print("  No rows with embeddings — skipping")
        return 0

    print(f"  {len(local_rows)} rows fetched. Clearing Supabase table...")
    sb_delete(table)

    print(f"  Uploading with embeddings...")
    payload = []
    for title, price, color, url, image, emb in local_rows:
        if not title or not title.strip():
            continue
        payload.append({
            "title":          title.strip(),
            "price":          (price or "").strip() or None,
            "color":          (color or "").strip() or None,
            "url":            (url   or "").strip() or None,
            "image":          (image or "").strip() or None,
            "clip_embedding": list(emb),   # float8[] -> plain Python list
        })

    total = len(payload)
    for i in range(0, total, BATCH_SIZE):
        batch = payload[i : i + BATCH_SIZE]
        sb_insert(table, batch)
        done = min(i + BATCH_SIZE, total)
        print(f"\r    {done}/{total} rows...", end="", flush=True)

    print()
    return total


def main():
    grand_total = 0
    for dbname, table in DB_TO_TABLE.items():
        print(f"\n[{dbname}] -> [{table}]")
        try:
            n = import_brand(dbname, table)
            grand_total += n
            print(f"  OK: {n} rows with embeddings")
        except Exception as e:
            print(f"  FAILED: {e}")

    print(f"\nDone! {grand_total} rows uploaded across {len(DB_TO_TABLE)} tables.")


if __name__ == "__main__":
    main()
