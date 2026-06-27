"""
Migration 002: Add circles, circle_members, circle_closet_permissions,
posts, post_images, post_likes.
Safe to run multiple times.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import get_db

SQL = """
-- ── circles ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS circles (
    id          SERIAL PRIMARY KEY,
    owner_id    INTEGER REFERENCES users(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    description TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ── circle_members ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS circle_members (
    circle_id   INTEGER REFERENCES circles(id) ON DELETE CASCADE,
    user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
    role        TEXT DEFAULT 'member' CHECK (role IN ('owner', 'admin', 'member')),
    joined_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (circle_id, user_id)
);

-- ── circle_closet_permissions ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS circle_closet_permissions (
    circle_id   INTEGER REFERENCES circles(id) ON DELETE CASCADE,
    user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
    can_view    BOOLEAN DEFAULT TRUE,
    can_edit    BOOLEAN DEFAULT FALSE,
    PRIMARY KEY (circle_id, user_id)
);

-- ── posts ────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS posts (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
    outfit_id   INTEGER REFERENCES outfits(id) ON DELETE SET NULL,
    caption     TEXT,
    visibility  TEXT DEFAULT 'friends' CHECK (visibility IN ('private','friends','circle','public')),
    circle_id   INTEGER REFERENCES circles(id) ON DELETE SET NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ── post_images ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS post_images (
    id          SERIAL PRIMARY KEY,
    post_id     INTEGER REFERENCES posts(id) ON DELETE CASCADE,
    image_path  TEXT NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ── post_likes ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS post_likes (
    post_id     INTEGER REFERENCES posts(id) ON DELETE CASCADE,
    user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (post_id, user_id)
);

-- ── post_comments ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS post_comments (
    id          SERIAL PRIMARY KEY,
    post_id     INTEGER REFERENCES posts(id) ON DELETE CASCADE,
    user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
    body        TEXT NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

def run():
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(SQL)
        conn.commit()
        print("✅ Migration 002 complete: circles, posts, likes, comments")
    except Exception as e:
        conn.rollback()
        print(f"❌ Migration 002 failed: {e}")
        raise
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    run()
