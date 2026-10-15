-- Migration 011: what a garment cost.
--
-- Additive only: every column is nullable, so nothing that reads closet_items
-- today needs to change and an item with no price simply has none.
--
-- Money is stored in cents as an integer rather than a float, because a float
-- cannot hold 19.99 exactly and a closet total is a sum of hundreds of them.
-- Everything is assumed to be USD for now; a currency column can follow if that
-- stops being true, and nothing here would need rewriting.

ALTER TABLE closet_items
  ADD COLUMN IF NOT EXISTS price_cents  INTEGER,
  ADD COLUMN IF NOT EXISTS purchased_on DATE,
  ADD COLUMN IF NOT EXISTS retailer     TEXT;

-- Spend over a period is the question these answer, and it is always scoped to
-- one person.
CREATE INDEX IF NOT EXISTS closet_items_purchased_idx
  ON closet_items (user_id, purchased_on DESC);

COMMENT ON COLUMN closet_items.price_cents  IS 'Purchase price in USD cents. NULL when unknown.';
COMMENT ON COLUMN closet_items.purchased_on IS 'When it was bought, which is not when it was uploaded.';
COMMENT ON COLUMN closet_items.retailer     IS 'Where it came from; filled by receipt import.';
