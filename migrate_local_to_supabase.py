"""
Migrate all user-data tables from local PostgreSQL → Supabase via REST API.

Steps:
  1. Run supabase_schema.sql in Supabase SQL Editor first (one-time)
  2. Then run:  python migrate_local_to_supabase.py
"""

import json
import os
import urllib.request
import urllib.error
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# ── Local PostgreSQL (source) ─────────────────────────────────
LOCAL = dict(
    dbname="closet_app",
    user="postgres",
    password=os.environ["PG_PASSWORD"],
    host="localhost",
    port="5432",
)

# ── Supabase REST API ─────────────────────────────────────────
SUPABASE_URL = os.environ["SUPABASE_URL"]
SERVICE_KEY  = os.environ["SUPABASE_KEY"]

BASE_HEADERS = {
    "apikey":        SERVICE_KEY,
    "Authorization": f"Bearer {SERVICE_KEY}",
    "Content-Type":  "application/json",
    "Prefer":        "return=minimal",
}

BATCH_SIZE = 200

# FK-safe insertion order
TABLES = [
    "users",
    "friend_requests",
    "friends",
    "categories",
    "closet_items",
    "outfits",
    "outfit_items",
    "outfit_ratings",
    "outfit_feedback",
    "circles",
    "circle_members",
    "circle_closet_permissions",
    "posts",
    "post_images",
    "post_likes",
    "post_comments",
]

# Tables with composite PKs (no `id` column) — need special delete filter
COMPOSITE_PK_TABLES = {
    "friends":                   "user_id",
    "circle_members":            "circle_id",
    "circle_closet_permissions": "circle_id",
    "post_likes":                "post_id",
}


def rest(method: str, path: str, body=None, extra_headers=None):
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    data = json.dumps(body, default=str).encode() if body is not None else None
    headers = {**BASE_HEADERS, **(extra_headers or {})}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            content = resp.read()
            return json.loads(content) if content else {}
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} on {method} {path}: {e.read().decode()}")


def clear_table(table: str):
    filter_col = COMPOSITE_PK_TABLES.get(table, "id")
    path = f"{table}?{filter_col}=gte.0"
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    req = urllib.request.Request(url, headers=BASE_HEADERS, method="DELETE")
    try:
        with urllib.request.urlopen(req):
            pass
    except urllib.error.HTTPError as e:
        if e.code != 404:
            body = e.read().decode()
            print(f"    (clear warning for {table}: HTTP {e.code} {body})")


def rows_to_dicts(cur, rows) -> list:
    cols = [d[0] for d in cur.description]
    result = []
    for row in rows:
        record = {}
        for col, val in zip(cols, row):
            if isinstance(val, list):
                record[col] = val           # FLOAT8[] → JSON array
            elif val is None:
                record[col] = None
            else:
                record[col] = val
        result.append(record)
    return result


def migrate_table(src_cur, table: str) -> int:
    src_cur.execute(f'SELECT * FROM "{table}"')
    rows = src_cur.fetchall()

    if not rows:
        print(f"  {table}: 0 rows")
        return 0

    dicts = rows_to_dicts(src_cur, rows)

    clear_table(table)

    for i in range(0, len(dicts), BATCH_SIZE):
        batch = dicts[i : i + BATCH_SIZE]
        rest("POST", table, batch, {"Prefer": "resolution=merge-duplicates,return=minimal"})
        pct = min(i + BATCH_SIZE, len(dicts))
        print(f"\r  {table}: {pct}/{len(dicts)} rows...", end="", flush=True)

    print(f"\r  {table}: {len(dicts)} rows migrated    ")
    return len(dicts)


def main():
    print("Connecting to local PostgreSQL...")
    src_conn = psycopg2.connect(**LOCAL)
    src_cur = src_conn.cursor()

    print(f"Migrating to Supabase ({SUPABASE_URL})...\n")
    print("NOTE: Assumes you already ran supabase_schema.sql in the SQL Editor.\n")

    total = 0
    for table in TABLES:
        try:
            total += migrate_table(src_cur, table)
        except Exception as e:
            print(f"\n  {table}: FAILED — {e}")

    src_cur.close()
    src_conn.close()

    print(f"\nDone! {total} rows migrated to Supabase.")


if __name__ == "__main__":
    main()
