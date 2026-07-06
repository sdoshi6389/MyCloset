"""
Migration 003: Add occasion, formality_score to closet_items.
GPT-4o vision analysis already generates both fields but they were never
persisted. Safe to run multiple times.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from config import DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_SSLMODE

SQL = """
ALTER TABLE closet_items ADD COLUMN IF NOT EXISTS occasion        TEXT;
ALTER TABLE closet_items ADD COLUMN IF NOT EXISTS formality_score SMALLINT CHECK (formality_score BETWEEN 1 AND 10);
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
        print("✅ Migration 003 complete: closet_items.occasion, closet_items.formality_score")
    except Exception as e:
        conn.rollback()
        print(f"❌ Migration 003 failed: {e}")
        raise
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    run()
