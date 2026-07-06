"""
Migration 004: Add subcategory and layering_role to closet_items.
GPT-4o vision analysis already generates both fields but they were never
persisted. Safe to run multiple times (ADD COLUMN IF NOT EXISTS).
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from config import DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_SSLMODE

SQL = """
ALTER TABLE closet_items ADD COLUMN IF NOT EXISTS subcategory   TEXT;
ALTER TABLE closet_items ADD COLUMN IF NOT EXISTS layering_role TEXT;
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
        print("✅ Migration 004 complete: closet_items.subcategory, closet_items.layering_role")
    except Exception as e:
        conn.rollback()
        print(f"❌ Migration 004 failed: {e}")
        raise
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    run()
