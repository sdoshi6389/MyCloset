-- Migration 007: Create missing recommendation/analytics tables + fix outfits.is_private
-- Run once in the Supabase SQL editor.

-- ── recommendation_logs ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS recommendation_logs (
    id                 BIGSERIAL PRIMARY KEY,
    recommendation_id  TEXT NOT NULL,
    user_id            INTEGER REFERENCES users(id) ON DELETE CASCADE,
    slot               TEXT,
    outfit_ctx         JSONB,
    candidate_item_id  TEXT,
    candidate_source   TEXT,
    rank               INTEGER,
    final_score        FLOAT,
    score_breakdown    JSONB,
    context            JSONB,
    was_clicked        BOOLEAN DEFAULT FALSE,
    was_added          BOOLEAN DEFAULT FALSE,
    was_saved          BOOLEAN DEFAULT FALSE,
    was_rejected       BOOLEAN DEFAULT FALSE,
    created_at         TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_rec_logs_user   ON recommendation_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_rec_logs_rec_id ON recommendation_logs(recommendation_id);

-- ── user_events ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS user_events (
    id                 BIGSERIAL PRIMARY KEY,
    user_id            INTEGER REFERENCES users(id) ON DELETE CASCADE,
    event_type         TEXT NOT NULL,
    item_id            TEXT,
    outfit_id          INTEGER,
    recommendation_id  TEXT,
    context            JSONB,
    created_at         TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_user_events_user ON user_events(user_id);
CREATE INDEX IF NOT EXISTS idx_user_events_type ON user_events(event_type);

-- ── recommendation_feedback ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS recommendation_feedback (
    id         BIGSERIAL PRIMARY KEY,
    user_id    INTEGER REFERENCES users(id) ON DELETE CASCADE,
    item_id    INTEGER,
    slot       TEXT,
    signal     TEXT CHECK (signal IN ('accept', 'reject', 'ignore')),
    outfit_ctx JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_rec_feedback_user ON recommendation_feedback(user_id);

-- ── user_profiles ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id            INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    vibe_weights       JSONB,
    color_palette      JSONB,
    formality_center   FLOAT DEFAULT 5.0,
    formality_std      FLOAT DEFAULT 2.0,
    style_vector       JSONB,
    pref_vector        JSONB,
    disliked_embedding JSONB,
    updated_at         TIMESTAMPTZ DEFAULT NOW()
);

-- ── catalog_icon_cache ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS catalog_icon_cache (
    id         BIGSERIAL PRIMARY KEY,
    cache_key  TEXT UNIQUE NOT NULL,
    image_url  TEXT,
    slot       TEXT,
    icon_path  TEXT,
    step_used  INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_catalog_icon_cache_key ON catalog_icon_cache(cache_key);

-- ── outfits.is_private (missing column) ──────────────────────────────────────
ALTER TABLE outfits ADD COLUMN IF NOT EXISTS is_private BOOLEAN DEFAULT FALSE;

-- ── outfit_items.scale (item resize factor from the builder canvas) ──────────
ALTER TABLE outfit_items ADD COLUMN IF NOT EXISTS scale FLOAT DEFAULT 1.0;

-- ── post_images: allow storing Supabase CDN URLs ─────────────────────────────
-- image_path may now be a full https:// URL (Supabase CDN) or a local filename
-- No schema change needed — the column is already TEXT
