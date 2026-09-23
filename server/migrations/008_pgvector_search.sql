-- Migration 008: move catalog similarity search into Postgres (pgvector).
--
-- Until now every query loaded ~207k vectors into the app process and ran an
-- exact faiss.IndexFlatL2 scan over all of them. That costs ~0.9 GB resident,
-- makes boot wait on a full download, and grows linearly with the catalog.
--
-- product_image_embeddings already exists but holds only (source_table,
-- product_id, image_url, embedding) — no brand/gender/title — so searching it
-- would mean joining back across 77 product tables. This table denormalises the
-- few fields search needs so one HNSW index answers the whole query.
--
-- Run in the Supabase SQL editor. Safe to re-run.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS product_vectors (
    id              BIGSERIAL PRIMARY KEY,
    source          TEXT NOT NULL,          -- brand key, e.g. 'abercrombie'
    product_id      TEXT NOT NULL,          -- id within its source table
    source_table    TEXT,                   -- provenance, nullable
    title           TEXT,
    color           TEXT,
    price           TEXT,
    image           TEXT,
    url             TEXT,
    -- Gender as the app resolves it (explicit field -> brand -> title regex),
    -- precomputed so SQL can filter exactly the way Python used to.
    resolved_gender TEXT,
    embedding       vector(512) NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE (source, product_id, image)
);

-- Vector ANN index. Without this Postgres sequentially scans every row, which
-- at catalog scale is slower than the in-memory scan it replaces.
-- Vectors are L2-normalised, so cosine and L2 rank identically.
CREATE INDEX IF NOT EXISTS product_vectors_embedding_hnsw
    ON product_vectors USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS product_vectors_source_idx ON product_vectors (source);
CREATE INDEX IF NOT EXISTS product_vectors_gender_idx ON product_vectors (resolved_gender);


-- Returns rows ordered by similarity, cheapest filters pushed down.
--
-- distance is returned as SQUARED L2 so it is numerically identical to what
-- faiss.IndexFlatL2 produced: for unit vectors  L2^2 = 2 * cosine_distance.
-- The scorer relies on that scale (1 - distance/2), so it must not drift.
CREATE OR REPLACE FUNCTION match_products(
    query_embedding vector(512),
    match_count     int  DEFAULT 200,
    filter_source   text DEFAULT NULL,
    filter_gender   text DEFAULT NULL
)
RETURNS TABLE (
    source          text,
    product_id      text,
    title           text,
    color           text,
    price           text,
    image           text,
    url             text,
    resolved_gender text,
    distance        double precision
)
LANGUAGE sql STABLE PARALLEL SAFE
AS $$
    SELECT pv.source,
           pv.product_id,
           pv.title,
           pv.color,
           pv.price,
           pv.image,
           pv.url,
           pv.resolved_gender,
           (pv.embedding <=> query_embedding) * 2 AS distance
    FROM product_vectors pv
    WHERE (filter_source IS NULL OR pv.source = filter_source)
      -- NULL gender means "unisex / unknown", which the app always kept.
      AND (filter_gender IS NULL
           OR pv.resolved_gender IS NULL
           OR pv.resolved_gender = filter_gender)
    ORDER BY pv.embedding <=> query_embedding
    LIMIT match_count;
$$;

GRANT EXECUTE ON FUNCTION match_products(vector(512), int, text, text) TO anon, authenticated, service_role;
