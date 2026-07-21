"""Add catalog_data, nudge_x, nudge_y to outfit_items; allow NULL closet_item_id for catalog pieces."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import get_db

SQL = """
ALTER TABLE outfit_items ADD COLUMN IF NOT EXISTS catalog_data JSONB;
ALTER TABLE outfit_items ADD COLUMN IF NOT EXISTS nudge_x SMALLINT DEFAULT 0;
ALTER TABLE outfit_items ADD COLUMN IF NOT EXISTS nudge_y SMALLINT DEFAULT 0;
ALTER TABLE outfit_items ALTER COLUMN closet_item_id DROP NOT NULL;
"""

def run():
    conn = get_db()
    cur  = conn.cursor()
    try:
        cur.execute(SQL)
        conn.commit()
        print("✅ Migration 006 complete: outfit_items catalog_data/nudge columns added")
    except Exception as e:
        conn.rollback()
        print(f"❌ Migration 006 failed: {e}")
        raise
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    run()
