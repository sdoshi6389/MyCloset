-- ============================================================
-- MyCloset — full schema for Supabase
-- Paste this into: Supabase Dashboard → SQL Editor → New query
-- Run it once. All statements are idempotent (IF NOT EXISTS).
-- ============================================================

-- ── users ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id              SERIAL PRIMARY KEY,
    email           TEXT UNIQUE NOT NULL,
    password        TEXT NOT NULL,
    last_seen       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status_caption  TEXT DEFAULT ''
);

-- ── friend_requests ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS friend_requests (
    id          SERIAL PRIMARY KEY,
    sender_id   INTEGER REFERENCES users(id) ON DELETE CASCADE,
    receiver_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    status      TEXT CHECK (status IN ('pending', 'accepted', 'rejected')) NOT NULL DEFAULT 'pending',
    timestamp   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ── friends ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS friends (
    user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
    friend_id   INTEGER REFERENCES users(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, friend_id)
);

-- ── categories ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS categories (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    is_default  BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, name)
);

INSERT INTO categories (user_id, name, is_default) VALUES
    (NULL, 'Tops',        TRUE),
    (NULL, 'Bottoms',     TRUE),
    (NULL, 'Outerwear',   TRUE),
    (NULL, 'Innerwear',   TRUE),
    (NULL, 'Accessories', TRUE),
    (NULL, 'Shoes',       TRUE)
ON CONFLICT DO NOTHING;

-- ── closet_items ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS closet_items (
    id                  SERIAL PRIMARY KEY,
    user_id             INTEGER REFERENCES users(id) ON DELETE CASCADE,
    filename            TEXT,
    filepath            TEXT,
    tag_text            TEXT,
    brand               TEXT,
    size                TEXT,
    vector_embedding    FLOAT8[],
    matched_brand       TEXT,
    matched_title       TEXT,
    icon_path           TEXT,
    caption             TEXT,
    type                TEXT,
    color               TEXT,
    style               TEXT,
    season              TEXT,
    fabric              TEXT,
    vibe                TEXT,
    gender              TEXT,
    keywords            TEXT,
    category            TEXT,
    tags                TEXT,
    matched_product_id  INTEGER,
    emoticon_path       TEXT,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    uploaded_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, filename)
);

-- ── outfits ──────────────────────────────────────────────────
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

-- ── outfit_items ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS outfit_items (
    id              SERIAL PRIMARY KEY,
    outfit_id       INTEGER REFERENCES outfits(id) ON DELETE CASCADE,
    closet_item_id  INTEGER REFERENCES closet_items(id) ON DELETE CASCADE,
    slot            TEXT,
    UNIQUE (outfit_id, closet_item_id)
);

-- ── outfit_ratings ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS outfit_ratings (
    id          SERIAL PRIMARY KEY,
    outfit_id   INTEGER REFERENCES outfits(id) ON DELETE CASCADE,
    user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
    rating      SMALLINT CHECK (rating BETWEEN 1 AND 5),
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (outfit_id, user_id)
);

-- ── outfit_feedback ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS outfit_feedback (
    id          SERIAL PRIMARY KEY,
    outfit_id   INTEGER REFERENCES outfits(id) ON DELETE CASCADE,
    user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
    feedback    TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ── circles ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS circles (
    id          SERIAL PRIMARY KEY,
    owner_id    INTEGER REFERENCES users(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    description TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ── circle_members ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS circle_members (
    circle_id   INTEGER REFERENCES circles(id) ON DELETE CASCADE,
    user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
    role        TEXT DEFAULT 'member' CHECK (role IN ('owner', 'admin', 'member')),
    joined_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (circle_id, user_id)
);

-- ── circle_closet_permissions ────────────────────────────────
CREATE TABLE IF NOT EXISTS circle_closet_permissions (
    circle_id   INTEGER REFERENCES circles(id) ON DELETE CASCADE,
    user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
    can_view    BOOLEAN DEFAULT TRUE,
    can_edit    BOOLEAN DEFAULT FALSE,
    PRIMARY KEY (circle_id, user_id)
);

-- ── posts ────────────────────────────────────────────────────
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

-- ── post_images ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS post_images (
    id          SERIAL PRIMARY KEY,
    post_id     INTEGER REFERENCES posts(id) ON DELETE CASCADE,
    image_path  TEXT NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ── post_likes ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS post_likes (
    post_id     INTEGER REFERENCES posts(id) ON DELETE CASCADE,
    user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (post_id, user_id)
);

-- ── post_comments ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS post_comments (
    id          SERIAL PRIMARY KEY,
    post_id     INTEGER REFERENCES posts(id) ON DELETE CASCADE,
    user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
    body        TEXT NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
