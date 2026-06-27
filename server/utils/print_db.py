import psycopg2

# === PostgreSQL Config ===
PG_USER = "postgres"
PG_PASSWORD = "#Sohildoshi123"
PG_HOST = "localhost"
PG_PORT = "5432"
DB_NAME = "closet_images"  # Change this to inspect other databases

def print_database_contents():
    conn = psycopg2.connect(
        dbname=DB_NAME,
        user=PG_USER,
        password=PG_PASSWORD,
        host=PG_HOST,
        port=PG_PORT
    )
    cur = conn.cursor()

    # Get all user-defined tables
    cur.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE';
    """)
    tables = cur.fetchall()

    if not tables:
        print(f"⚠️ No tables found in database '{DB_NAME}'")
        return

    print(f"📦 Database: {DB_NAME} | Tables: {[t[0] for t in tables]}\n" + "="*80)

    for (table_name,) in tables:
        print(f"\n📄 Table: {table_name}")
        print("-" * 80)

        # Get column names
        cur.execute(f"SELECT * FROM {table_name} LIMIT 0;")
        colnames = [desc[0] for desc in cur.description]

        # Fetch rows
        cur.execute(f"SELECT * FROM {table_name};")
        rows = cur.fetchall()

        print(f"🧾 Columns: {colnames}")
        print(f"📊 Rows: {len(rows)}")

        for row in rows:
            print("→", dict(zip(colnames, row)))
        print("-" * 80)

    cur.close()
    conn.close()

if __name__ == "__main__":
    print_database_contents()
