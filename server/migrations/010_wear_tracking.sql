-- Migration 010: wear tracking and the weekly outfit log.
--
-- Additive only: new columns carry defaults and the new table is separate, so
-- nothing that reads closet_items today needs to change.

-- ── Per-item wear state ──────────────────────────────────────────────────────
ALTER TABLE closet_items
  ADD COLUMN IF NOT EXISTS wear_count  INTEGER     NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS in_laundry  BOOLEAN     NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS last_worn   DATE;

-- Recommendation queries filter and sort on these two constantly.
CREATE INDEX IF NOT EXISTS closet_items_laundry_idx
  ON closet_items (user_id, in_laundry);
CREATE INDEX IF NOT EXISTS closet_items_last_worn_idx
  ON closet_items (user_id, last_worn DESC);

-- ── What was worn, on which day ──────────────────────────────────────────────
-- A day holds at most one entry per user, so logging the same day twice updates
-- rather than duplicating. outfit_id is nullable: someone can log a day from
-- loose items without having saved it as an outfit first.
CREATE TABLE IF NOT EXISTS outfit_wears (
    id         BIGSERIAL PRIMARY KEY,
    user_id    BIGINT  NOT NULL,
    outfit_id  BIGINT,
    worn_on    DATE    NOT NULL,
    note       TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (user_id, worn_on)
);

CREATE INDEX IF NOT EXISTS outfit_wears_user_day_idx
  ON outfit_wears (user_id, worn_on DESC);

-- The pieces that made up that day, captured at the time. Kept separate from
-- outfit_items so editing or deleting a saved outfit later does not rewrite
-- what you actually wore last Tuesday.
CREATE TABLE IF NOT EXISTS outfit_wear_items (
    id             BIGSERIAL PRIMARY KEY,
    wear_id        BIGINT NOT NULL REFERENCES outfit_wears(id) ON DELETE CASCADE,
    closet_item_id BIGINT,
    slot           TEXT,
    UNIQUE (wear_id, slot)
);

CREATE INDEX IF NOT EXISTS outfit_wear_items_wear_idx
  ON outfit_wear_items (wear_id);

NOTIFY pgrst, 'reload schema';
