import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

DB_NAME = "closet_app"
DB_USER = "postgres"
DB_PASSWORD = "#Sohildoshi123"
DB_HOST = "localhost"
DB_PORT = "5432"

def create_database_if_missing():
    try:
        conn = psycopg2.connect(
            dbname="postgres",
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()

        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,))
        exists = cur.fetchone()

        if not exists:
            cur.execute(f"CREATE DATABASE {DB_NAME}")
            print(f"🛠️ Created database: {DB_NAME}")
        else:
            print(f"✅ Database '{DB_NAME}' already exists")

        cur.close()
        conn.close()

    except Exception as e:
        print(f"❌ Error creating database: {e}")

def create_users_table_and_social_features():
    try:
        conn = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        cur = conn.cursor()

        # === USERS TABLE ===
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            );
        """)

        # === UPGRADE users TABLE ===
        cur.execute("""
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ADD COLUMN IF NOT EXISTS status_caption TEXT DEFAULT '';
        """)

        # === FRIEND REQUESTS TABLE ===
        cur.execute("""
            CREATE TABLE IF NOT EXISTS friend_requests (
                id SERIAL PRIMARY KEY,
                sender_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                receiver_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                status TEXT CHECK (status IN ('pending', 'accepted', 'rejected')) NOT NULL DEFAULT 'pending',
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # === FRIENDS TABLE ===
        cur.execute("""
            CREATE TABLE IF NOT EXISTS friends (
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                friend_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                PRIMARY KEY (user_id, friend_id)
            );
        """)

        conn.commit()
        cur.close()
        conn.close()
        print("✅ All tables and upgrades are ready!")

    except Exception as e:
        print(f"❌ Error creating or modifying tables: {e}")

if __name__ == "__main__":
    create_database_if_missing()
    create_users_table_and_social_features()
