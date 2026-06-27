import os
import psycopg2
import psycopg2.extras

# === PostgreSQL Credentials ===
PG_USER = "postgres"
PG_PASSWORD = "#Sohildoshi123"
PG_HOST = "localhost"
PG_PORT = "5432"
DB_NAME = "closet_images"
IMAGE_FOLDER = "downloaded_images"
TABLE_NAME = "image_metadata"

# === Connect to default DB and create target DB if needed ===
def create_database_if_not_exists():
    conn = psycopg2.connect(dbname="postgres", user=PG_USER, password=PG_PASSWORD, host=PG_HOST, port=PG_PORT)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,))
    if not cur.fetchone():
        print(f"🛠️ Creating database: {DB_NAME}")
        cur.execute(f"CREATE DATABASE {DB_NAME}")
    else:
        print(f"✅ Database '{DB_NAME}' already exists")
    cur.close()
    conn.close()

# === Connect to target DB ===
def get_connection():
    return psycopg2.connect(dbname=DB_NAME, user=PG_USER, password=PG_PASSWORD, host=PG_HOST, port=PG_PORT)

# === Create table and unique index ===
def create_table_if_not_exists(conn):
    with conn.cursor() as cur:
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
                id SERIAL PRIMARY KEY,
                filename TEXT NOT NULL,
                filepath TEXT NOT NULL,
                vector_embedding FLOAT8[],
                UNIQUE (filename, filepath)
            );
        """)
        # Create explicit unique index (in case table was made before)
        cur.execute(f"""
            CREATE UNIQUE INDEX IF NOT EXISTS uniq_file ON {TABLE_NAME} (filename, filepath);
        """)
        conn.commit()
        print(f"🛠️ Table '{TABLE_NAME}' checked/created")

# === Optional full wipe
def clear_database():
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT COUNT(*) FROM {TABLE_NAME};")
        before = cur.fetchone()[0]
        cur.execute(f"DELETE FROM {TABLE_NAME};")
        cur.execute(f"ALTER SEQUENCE {TABLE_NAME}_id_seq RESTART WITH 1;")
        conn.commit()
        cur.execute(f"SELECT COUNT(*) FROM {TABLE_NAME};")
        after = cur.fetchone()[0]
        print(f"🧹 Cleared {before} rows → {after} remain")
    finally:
        cur.close()
        conn.close()


# === Insert normalized absolute image paths with deduping
def insert_images(conn):
    inserted = 0
    skipped = 0
    with conn.cursor() as cur:
        for dirpath, _, filenames in os.walk(IMAGE_FOLDER):
            for filename in filenames:
                if filename.lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.heic')):
                    abs_path = os.path.abspath(os.path.join(dirpath, filename))
                    normalized_path = abs_path   # .lower().replace("\\", "/")

                    cur.execute(f"""
                        INSERT INTO {TABLE_NAME} (filename, filepath)
                        VALUES (%s, %s)
                        ON CONFLICT (filename, filepath) DO NOTHING
                        RETURNING id;
                    """, (filename, normalized_path))

                    if cur.fetchone():
                        inserted += 1
                        print(f"✅ Inserted: {filename}")
                    else:
                        skipped += 1
                        print(f"⏭️ Skipped duplicate: {filename}")

        conn.commit()
        print(f"\n📦 Insert complete: {inserted} inserted, {skipped} skipped.")

# === Print all rows
def print_table_rows():
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT id, filename, filepath, vector_embedding FROM {TABLE_NAME} ORDER BY id ASC;")
        rows = cur.fetchall()

        print(f"\n📄 Showing {len(rows)} rows from '{TABLE_NAME}':\n" + "-"*100)
        for id, filename, filepath, embedding in rows:
            print(f"🆔 {id} | 📄 {filename}\n📂 {filepath}")
            if embedding:
                print(f"🔢 Embedding preview: {embedding[:5]} ...\n")
            else:
                print(f"⚠️ No embedding available\n")

# === Main runner ===
def main():
    create_database_if_not_exists()
    with get_connection() as conn:
        create_table_if_not_exists(conn)
        #clear_database()
        insert_images(conn)

    print_table_rows()
    print("🎉 Done!")

if __name__ == "__main__":
    main()
