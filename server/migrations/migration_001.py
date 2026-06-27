"""
Migration 001: Add categories, outfits, outfit_items, outfit_ratings, outfit_feedback.
Safe to run multiple times (uses IF NOT EXISTS / ADD COLUMN IF NOT EXISTS).
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import get_db

SQL = """
-- ── categories ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS categories (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    is_default  BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, name)
);

-- Seed default categories (user_id NULL = global defaults)
INSERT INTO categories (user_id, name, is_default) VALUES
    (NULL, 'Tops',       TRUE),
    (NULL, 'Bottoms',    TRUE),
    (NULL, 'Outerwear',  TRUE),
    (NULL, 'Innerwear',  TRUE),
    (NULL, 'Accessories',TRUE),
    (NULL, 'Shoes',      TRUE)
ON CONFLICT DO NOTHING;

-- ── closet_items additions ──────────────────────────────────────────────────
ALTER TABLE closet_items ADD COLUMN IF NOT EXISTS category      TEXT;
ALTER TABLE closet_items ADD COLUMN IF NOT EXISTS tags          TEXT;
ALTER TABLE closet_items ADD COLUMN IF NOT EXISTS matched_product_id INTEGER;
ALTER TABLE closet_items ADD COLUMN IF NOT EXISTS emoticon_path TEXT;
ALTER TABLE closet_items ADD COLUMN IF NOT EXISTS created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP;

-- ── outfits ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS outfits (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
    name        TEXT NOT NULL DEFAULT 'My Outfit',
    occasion    TEXT,
    notes       TEXT,
    tags        TEXT,
    rating      SMALLINT CHECK (rating BETWEEN 1 AND 5),
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ── outfit_items ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS outfit_items (
    id              SERIAL PRIMARY KEY,
    outfit_id       INTEGER REFERENCES outfits(id) ON DELETE CASCADE,
    closet_item_id  INTEGER REFERENCES closet_items(id) ON DELETE CASCADE,
    slot            TEXT,
    UNIQUE (outfit_id, closet_item_id)
);

-- ── outfit_ratings ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS outfit_ratings (
    id          SERIAL PRIMARY KEY,
    outfit_id   INTEGER REFERENCES outfits(id) ON DELETE CASCADE,
    user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
    rating      SMALLINT CHECK (rating BETWEEN 1 AND 5),
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (outfit_id, user_id)
);

-- ── outfit_feedback ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS outfit_feedback (
    id          SERIAL PRIMARY KEY,
    outfit_id   INTEGER REFERENCES outfits(id) ON DELETE CASCADE,
    user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
    feedback    TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

def run():
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(SQL)
        conn.commit()
        print("✅ Migration 001 complete: categories, outfits, outfit_items, ratings, feedback")
    except Exception as e:
        conn.rollback()
        print(f"❌ Migration 001 failed: {e}")
        raise
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    run()
