"""
Migration 005: Multi-image FAISS pipeline (Alo phase).

  1. Add images TEXT[] column to products_alo_womens and products_alo_mens.
     Existing rows get an empty array; the alo scraper will back-fill on next run.
  2. Create product_image_embeddings table — one row per (product, image_url),
     holding the 512-dim CLIP embedding for that specific photo.

Safe to run multiple times (IF NOT EXISTS / ADD COLUMN IF NOT EXISTS).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from config import DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_SSLMODE

SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

DO $$
DECLARE
    tbl TEXT;
BEGIN
    FOR tbl IN
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name LIKE 'products_%'
        ORDER BY table_name
    LOOP
        EXECUTE format(
            'ALTER TABLE %I ADD COLUMN IF NOT EXISTS images TEXT[] DEFAULT %L',
            tbl,
            '{}'
        );
    END LOOP;
END;
$$;

CREATE TABLE IF NOT EXISTS product_image_embeddings (
    id           BIGSERIAL PRIMARY KEY,
    source_table TEXT      NOT NULL,
    product_id   BIGINT    NOT NULL,
    image_url    TEXT      NOT NULL,
    embedding    vector(512),
    created_at   TIMESTAMPTZ DEFAULT now(),
    UNIQUE (source_table, image_url)
);

CREATE INDEX IF NOT EXISTS pie_source_table_idx
    ON product_image_embeddings (source_table);
CREATE INDEX IF NOT EXISTS pie_product_id_idx
    ON product_image_embeddings (source_table, product_id);
"""


def run():
    conn = psycopg2.connect(
        dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD,
        host=DB_HOST, port=DB_PORT, sslmode=DB_SSLMODE,
    )
    cur = conn.cursor()
    try:
        cur.execute(SQL)
        conn.commit()
        print("Migration 005 complete: images[] on alo tables + product_image_embeddings")
    except Exception as e:
        conn.rollback()
        print(f"Migration 005 failed: {e}")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    run()
