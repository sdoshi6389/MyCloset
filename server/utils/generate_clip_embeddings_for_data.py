"""
Reads a scraped product CSV, generates CLIP embeddings, and upserts into
the Supabase 'products_{brand}' table.

Each brand gets its own table (e.g. products_alo_mens, products_gymshark_womens).
Create the table once in the Supabase SQL editor before running:

    CREATE TABLE IF NOT EXISTS products_alo_mens (
        id                 BIGSERIAL PRIMARY KEY,
        original_id        TEXT UNIQUE,
        title              TEXT,
        price              TEXT,
        color              TEXT,
        url                TEXT,
        image              TEXT,
        combined_embedding FLOAT8[],
        created_at         TIMESTAMPTZ DEFAULT NOW()
    );

Usage (standalone):
    Edit CSV_FILE and BRAND below, then:
        python utils/generate_clip_embeddings_for_data.py

Usage (imported by a scraper):
    from utils.generate_clip_embeddings_for_data import process_csv
    process_csv("output.csv", brand="alo_mens")
"""

import os
import sys

# Allow running directly from the utils/ folder or importing from server/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
from db import get_supa
from utils.clip_embedder import generate_embedding

# ── Configure when running standalone ─────────────────────────────────────────
CSV_FILE = "alo_men_products.csv"   # path relative to server/
BRAND    = "alo_mens"               # must match the products_{brand} table name

BATCH_SIZE = 20   # rows per Supabase upsert


def process_csv(csv_path: str, brand: str) -> None:
    """
    Read a product CSV, generate CLIP embeddings for every row, and upsert
    into the Supabase table products_{brand}.

    Rows that already exist (same original_id) are updated in place.
    """
    supa       = get_supa()
    table_name = f"products_{brand}"

    df = pd.read_csv(csv_path)
    print(f"Loaded {len(df)} rows from {csv_path}  →  table: {table_name}")

    batch   = []
    skipped = 0
    saved   = 0

    for idx, row in df.iterrows():
        title     = str(row.get("title", "")).strip()
        price     = str(row.get("price", "")).strip()
        color     = str(row.get("color", "")).strip()
        url       = str(row.get("url", "")).strip()
        image_url = str(row.get("image", "")).strip()

        if not image_url.startswith("http"):
            print(f"  ⚠️  row {idx}: no image URL — skipping")
            skipped += 1
            continue

        embedding = generate_embedding(title, image_url)
        if embedding is None:
            skipped += 1
            continue

        batch.append({
            "original_id":        f"{brand}::{title}::{image_url}",
            "title":              title,
            "price":              price,
            "color":              color,
            "url":                url,
            "image":              image_url,
            "combined_embedding": embedding,
        })

        if len(batch) >= BATCH_SIZE:
            supa.table(table_name).upsert(batch, on_conflict="original_id").execute()
            saved += len(batch)
            batch  = []
            print(f"  … {saved} saved so far")

    if batch:
        supa.table(table_name).upsert(batch, on_conflict="original_id").execute()
        saved += len(batch)

    print(f"\nDone — {saved} upserted, {skipped} skipped  (brand='{brand}')")


if __name__ == "__main__":
    csv_path = os.path.join(os.path.dirname(__file__), "..", CSV_FILE)
    process_csv(os.path.abspath(csv_path), BRAND)
