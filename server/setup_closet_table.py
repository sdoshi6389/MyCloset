import psycopg2

# === Database Config ===
DB_NAME = "closet_app"
DB_USER = "postgres"
DB_PASSWORD = "#Sohildoshi123"
DB_HOST = "localhost"
DB_PORT = "5432"

def clean_and_alter_closet_table():
    try:
        conn = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        cur = conn.cursor()

        # 🔍 Step 1: Show how many duplicate (user_id, filename) combinations exist
        print("🔎 Checking for duplicates...")
        cur.execute("""
            SELECT user_id, filename, COUNT(*)
            FROM closet_items
            GROUP BY user_id, filename
            HAVING COUNT(*) > 1;
        """)
        duplicates = cur.fetchall()
        if duplicates:
            print(f"⚠️ Found {len(duplicates)} duplicate entries. Cleaning...")

            # 🧹 Step 2: Remove all but the latest per (user_id, filename)
            cur.execute("""
                DELETE FROM closet_items
                WHERE id NOT IN (
                    SELECT MAX(id)
                    FROM closet_items
                    GROUP BY user_id, filename
                );
            """)
            print("✅ Duplicate cleanup complete.")
        else:
            print("✅ No duplicates found.")

        # 🛠️ Step 3: Add required columns if missing
        cur.execute("""
            ALTER TABLE closet_items
            ADD COLUMN IF NOT EXISTS tag_text TEXT,
            ADD COLUMN IF NOT EXISTS brand TEXT,
            ADD COLUMN IF NOT EXISTS size TEXT,
            ADD COLUMN IF NOT EXISTS vector_embedding FLOAT8[],
            ADD COLUMN IF NOT EXISTS matched_brand TEXT,
            ADD COLUMN IF NOT EXISTS matched_title TEXT,
            ADD COLUMN IF NOT EXISTS icon_path TEXT,
            ADD COLUMN IF NOT EXISTS caption TEXT,
            ADD COLUMN IF NOT EXISTS type TEXT,
            ADD COLUMN IF NOT EXISTS color TEXT,
            ADD COLUMN IF NOT EXISTS style TEXT,
            ADD COLUMN IF NOT EXISTS season TEXT,
            ADD COLUMN IF NOT EXISTS fabric TEXT,
            ADD COLUMN IF NOT EXISTS vibe TEXT,
            ADD COLUMN IF NOT EXISTS gender TEXT,
            ADD COLUMN IF NOT EXISTS keywords TEXT;
        """)
        print("🧩 Ensured columns: tag_text, brand, size, vector embedding")

        # 🔐 Step 4: Add unique constraint
        cur.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'closet_items_user_filename_key'
                ) THEN
                    ALTER TABLE closet_items
                    ADD CONSTRAINT closet_items_user_filename_key UNIQUE (user_id, filename);
                END IF;
            END$$;
        """)
        print("🔒 UNIQUE constraint on (user_id, filename) ensured.")

        conn.commit()
        cur.close()
        conn.close()
        print("✅ Done updating closet_items table.")

    except Exception as e:
        print(f"❌ Error during table cleanup or modification: {e}")

if __name__ == "__main__":
    clean_and_alter_closet_table()
