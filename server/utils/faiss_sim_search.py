import psycopg2
import faiss
import numpy as np

# === PostgreSQL Config ===
PG_USER = "postgres"
PG_PASSWORD = "#Sohildoshi123"
PG_HOST = "localhost"
PG_PORT = "5432"

# === Closet DB Info ===
CLOSET_DB = "closet_images"
CLOSET_TABLE = "image_metadata"

# === Number of Neighbors to Return ===
TOP_K = 5

# === Brand Databases to Search ===
BRAND_DBS = [
    {"dbname": "gymshark_mens_full", "table": "products"},
    {"dbname": "gymshark_womens_full", "table": "products"},
    {"dbname": "hollister_mens_full", "table": "products"},
    {"dbname": "hollister_womens_full", "table": "products"}, 
    {"dbname": "essentials_mens", "table": "products"},
    {"dbname": "essentials_women", "table": "products"},
    {"dbname": "hm_women_products", "table": "products"},
    {"dbname": "cottonon_men_products", "table": "products"},
    {"dbname": "cottonon_women_products", "table": "products"},
    {"dbname": "abercrombie_men_products", "table": "products"},
    {"dbname": "abercrombie_women_products", "table": "products"},
    {"dbname": "alo_men_products", "table": "products"},
    {"dbname": "alo_women_products", "table": "products"}
]

# === Load All Brand Embeddings ===
def load_all_brand_embeddings():
    all_embeddings = []
    all_metadata = []

    for brand in BRAND_DBS:
        dbname = brand["dbname"]
        table = brand["table"]
        print(f"📦 Loading embeddings from: {dbname}.{table}")

        try:
            conn = psycopg2.connect(dbname=dbname, user=PG_USER, password=PG_PASSWORD, host=PG_HOST, port=PG_PORT)
            cur = conn.cursor()
            cur.execute(f"""
                SELECT id, title, price, color, url, image, combined_embedding
                FROM {table}
                WHERE combined_embedding IS NOT NULL;
            """)
            rows = cur.fetchall()
            cur.close()
            conn.close()

            for row in rows:
                _id, title, price, color, url, image_url, embedding = row
                all_embeddings.append(np.array(embedding, dtype=np.float32))
                all_metadata.append({
                    "id": _id,
                    "title": title,
                    "price": price,
                    "color": color,
                    "url": url,
                    "image": image_url,
                    "source": dbname
                })

        except Exception as e:
            print(f"❌ Failed to load from {dbname}: {e}")

    if not all_embeddings:
        raise ValueError("❌ No embeddings found from any brand databases.")
    return np.stack(all_embeddings), all_metadata

# === Load Query Vector from Closet DB ===
def load_query_vector(filename):
    conn = psycopg2.connect(dbname=CLOSET_DB, user=PG_USER, password=PG_PASSWORD, host=PG_HOST, port=PG_PORT)
    cur = conn.cursor()
    cur.execute(f"""
        SELECT vector_embedding FROM {CLOSET_TABLE}
        WHERE filename = %s AND vector_embedding IS NOT NULL
        LIMIT 1;
    """, (filename,))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        raise ValueError(f"❌ No embedding found for file: {filename}")
    return np.array(row[0], dtype=np.float32)

# === Build FAISS Index ===
def build_faiss_index(vectors):
    dim = vectors.shape[1]
    index = faiss.IndexFlatL2(dim)
    index.add(vectors)
    return index

# === Perform FAISS Search ===
def search_faiss(query_vector, index, metadata):
    query_vector = query_vector.reshape(1, -1)
    distances, indices = index.search(query_vector, TOP_K)
    results = []
    for dist, idx in zip(distances[0], indices[0]):
        item = metadata[idx]
        item["distance"] = float(dist)
        results.append(item)
    return results

# === MAIN ===
if __name__ == "__main__":
    # Replace with your actual closet image filename
    test_filename = "IMG_5096.HEIC"

    print("📦 Loading brand embeddings...")
    all_vectors, all_metadata = load_all_brand_embeddings()

    print(f"🧠 Loading query vector for: {test_filename}")
    query_vec = load_query_vector(test_filename)

    print("⚙️ Building FAISS index...")
    index = build_faiss_index(all_vectors)

    print("🔍 Running FAISS similarity search...")
    results = search_faiss(query_vec, index, all_metadata)

    print("\n🎯 Top Matches:")
    for r in results:
        print(f"- {r['title']} | 💲 {r['price']} | 🎨 {r['color']} | 🏷️ {r['source']}")
        print(f"  🔗 {r['url']}")
        print(f"  📉 Distance: {r['distance']:.4f}\n")
