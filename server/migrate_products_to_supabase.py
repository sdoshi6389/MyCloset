"""
One-time migration: copy all products from local PostgreSQL brand databases
into a single Supabase 'products' table.

Run once from the server/ directory:
    python migrate_products_to_supabase.py

The Supabase table must exist first — run this SQL in the Supabase SQL editor:

    CREATE TABLE IF NOT EXISTS products (
        id            BIGSERIAL PRIMARY KEY,
        original_id   TEXT UNIQUE,          -- "{dbname}::{row_id}" dedup key
        title         TEXT,
        price         TEXT,
        color         TEXT,
        url           TEXT,
        image         TEXT,
        combined_embedding FLOAT8[],
        brand         TEXT,
        created_at    TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_products_brand ON products(brand);
"""

import psycopg2
from db import get_supa

# ── Local PG config ────────────────────────────────────────────────────────────
PG_USER     = "postgres"
PG_PASSWORD = "#Sohildoshi123"
PG_HOST     = "localhost"
PG_PORT     = "5432"

# ── DB name → canonical brand ──────────────────────────────────────────────────
DB_TO_BRAND = {
    "gymshark_mens_full":       "gymshark",
    "gymshark_womens_full":     "gymshark",
    "hollister_mens_full":      "hollister",
    "hollister_womens_full":    "hollister",
    "essentials_mens":          "essentials",
    "essentials_women":         "essentials",
    "hm_women_products":        "h&m",
    "cottonon_men_products":    "cotton on",
    "cottonon_women_products":  "cotton on",
    "abercrombie_men_products": "abercrombie",
    "abercrombie_women_products":"abercrombie",
    "alo_men_products":         "alo",
    "alo_women_products":       "alo",
}

BATCH_SIZE = 50  # rows per Supabase upsert (keep small to avoid timeouts)


def migrate():
    supa = get_supa()
    total_inserted = 0

    for dbname, brand in DB_TO_BRAND.items():
        print(f"\n📦 Migrating {dbname} → brand='{brand}'")
        try:
            conn = psycopg2.connect(
                dbname=dbname, user=PG_USER, password=PG_PASSWORD,
                host=PG_HOST, port=PG_PORT
            )
            cur = conn.cursor()
            cur.execute("""
                SELECT id, title, price, color, url, image, combined_embedding
                FROM products
                WHERE combined_embedding IS NOT NULL
            """)
            rows = cur.fetchall()
            cur.close()
            conn.close()
        except Exception as e:
            print(f"  ⚠️  Could not connect to {dbname}: {e}")
            continue

        print(f"  Found {len(rows)} rows with embeddings")

        # Batch upsert into Supabase
        batch = []
        inserted = 0
        for row in rows:
            orig_id = f"{dbname}::{row[0]}"
            batch.append({
                "original_id":        orig_id,
                "title":              row[1],
                "price":              row[2],
                "color":              row[3],
                "url":                row[4],
                "image":              row[5],
                "combined_embedding": list(row[6]) if row[6] else None,
                "brand":              brand,
            })

            if len(batch) >= BATCH_SIZE:
                supa.table("products").upsert(
                    batch, on_conflict="original_id"
                ).execute()
                inserted += len(batch)
                print(f"  … {inserted}/{len(rows)}")
                batch = []

        if batch:
            supa.table("products").upsert(
                batch, on_conflict="original_id"
            ).execute()
            inserted += len(batch)

        print(f"  ✅ {inserted} rows upserted for '{brand}'")
        total_inserted += inserted

    print(f"\n🎉 Migration complete — {total_inserted} total rows in Supabase 'products'")


if __name__ == "__main__":
    migrate()
