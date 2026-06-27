-- ============================================================
-- MyCloset — brand product tables for Supabase
-- Paste into: Supabase Dashboard → SQL Editor → New query → Run
-- Unique index on (title, color, image) prevents duplicate products.
-- ============================================================

-- ── Helper function (run ONCE) ───────────────────────────────
-- Handles table auto-creation AND batch insert with ON CONFLICT DO NOTHING.
-- Used by all scrapers via: supabase.rpc("upsert_brand_products", {...})
CREATE OR REPLACE FUNCTION upsert_brand_products(table_name TEXT, products JSONB)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    inserted_count INTEGER := 0;
    product        JSONB;
    rows_affected  INTEGER;
BEGIN
    EXECUTE format('
        CREATE TABLE IF NOT EXISTS %I (
            id    SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            price TEXT DEFAULT '''',
            color TEXT DEFAULT '''',
            url   TEXT DEFAULT '''',
            image TEXT DEFAULT ''''
        )', table_name);

    EXECUTE format('
        CREATE UNIQUE INDEX IF NOT EXISTS %I
        ON %I (title, COALESCE(color,''''), COALESCE(image,''''))',
        table_name || '_uniq',
        table_name);

    FOR product IN SELECT * FROM jsonb_array_elements(products)
    LOOP
        EXECUTE format('
            INSERT INTO %I (title, price, color, url, image)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT DO NOTHING',
            table_name
        )
        USING
            COALESCE(product->>'title', ''),
            COALESCE(product->>'price', ''),
            COALESCE(product->>'color', ''),
            COALESCE(product->>'url',   ''),
            COALESCE(product->>'image', '');

        GET DIAGNOSTICS rows_affected = ROW_COUNT;
        inserted_count := inserted_count + rows_affected;
    END LOOP;

    RETURN inserted_count;
END;
$$;
-- ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS products_gymshark_mens          (id SERIAL PRIMARY KEY, title TEXT NOT NULL, price TEXT, color TEXT, url TEXT, image TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS products_gymshark_mens_uniq          ON products_gymshark_mens          (title, COALESCE(color,''), COALESCE(image,''));

CREATE TABLE IF NOT EXISTS products_gymshark_womens         (id SERIAL PRIMARY KEY, title TEXT NOT NULL, price TEXT, color TEXT, url TEXT, image TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS products_gymshark_womens_uniq         ON products_gymshark_womens         (title, COALESCE(color,''), COALESCE(image,''));

CREATE TABLE IF NOT EXISTS products_hollister_mens          (id SERIAL PRIMARY KEY, title TEXT NOT NULL, price TEXT, color TEXT, url TEXT, image TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS products_hollister_mens_uniq          ON products_hollister_mens          (title, COALESCE(color,''), COALESCE(image,''));

CREATE TABLE IF NOT EXISTS products_hollister_womens        (id SERIAL PRIMARY KEY, title TEXT NOT NULL, price TEXT, color TEXT, url TEXT, image TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS products_hollister_womens_uniq        ON products_hollister_womens        (title, COALESCE(color,''), COALESCE(image,''));

CREATE TABLE IF NOT EXISTS products_essentials_mens         (id SERIAL PRIMARY KEY, title TEXT NOT NULL, price TEXT, color TEXT, url TEXT, image TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS products_essentials_mens_uniq         ON products_essentials_mens         (title, COALESCE(color,''), COALESCE(image,''));

CREATE TABLE IF NOT EXISTS products_essentials_womens       (id SERIAL PRIMARY KEY, title TEXT NOT NULL, price TEXT, color TEXT, url TEXT, image TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS products_essentials_womens_uniq       ON products_essentials_womens       (title, COALESCE(color,''), COALESCE(image,''));

CREATE TABLE IF NOT EXISTS products_hm_womens               (id SERIAL PRIMARY KEY, title TEXT NOT NULL, price TEXT, color TEXT, url TEXT, image TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS products_hm_womens_uniq               ON products_hm_womens               (title, COALESCE(color,''), COALESCE(image,''));

CREATE TABLE IF NOT EXISTS products_hm_mens                 (id SERIAL PRIMARY KEY, title TEXT NOT NULL, price TEXT, color TEXT, url TEXT, image TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS products_hm_mens_uniq                 ON products_hm_mens                 (title, COALESCE(color,''), COALESCE(image,''));

CREATE TABLE IF NOT EXISTS products_cottonon_mens           (id SERIAL PRIMARY KEY, title TEXT NOT NULL, price TEXT, color TEXT, url TEXT, image TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS products_cottonon_mens_uniq           ON products_cottonon_mens           (title, COALESCE(color,''), COALESCE(image,''));

CREATE TABLE IF NOT EXISTS products_cottonon_womens         (id SERIAL PRIMARY KEY, title TEXT NOT NULL, price TEXT, color TEXT, url TEXT, image TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS products_cottonon_womens_uniq         ON products_cottonon_womens         (title, COALESCE(color,''), COALESCE(image,''));

CREATE TABLE IF NOT EXISTS products_abercrombie_mens        (id SERIAL PRIMARY KEY, title TEXT NOT NULL, price TEXT, color TEXT, url TEXT, image TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS products_abercrombie_mens_uniq        ON products_abercrombie_mens        (title, COALESCE(color,''), COALESCE(image,''));

CREATE TABLE IF NOT EXISTS products_abercrombie_womens      (id SERIAL PRIMARY KEY, title TEXT NOT NULL, price TEXT, color TEXT, url TEXT, image TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS products_abercrombie_womens_uniq      ON products_abercrombie_womens      (title, COALESCE(color,''), COALESCE(image,''));

CREATE TABLE IF NOT EXISTS products_alo_mens                (id SERIAL PRIMARY KEY, title TEXT NOT NULL, price TEXT, color TEXT, url TEXT, image TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS products_alo_mens_uniq                ON products_alo_mens                (title, COALESCE(color,''), COALESCE(image,''));

CREATE TABLE IF NOT EXISTS products_alo_womens              (id SERIAL PRIMARY KEY, title TEXT NOT NULL, price TEXT, color TEXT, url TEXT, image TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS products_alo_womens_uniq              ON products_alo_womens              (title, COALESCE(color,''), COALESCE(image,''));

CREATE TABLE IF NOT EXISTS products_forever21_mens          (id SERIAL PRIMARY KEY, title TEXT NOT NULL, price TEXT, color TEXT, url TEXT, image TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS products_forever21_mens_uniq          ON products_forever21_mens          (title, COALESCE(color,''), COALESCE(image,''));

CREATE TABLE IF NOT EXISTS products_forever21_womens        (id SERIAL PRIMARY KEY, title TEXT NOT NULL, price TEXT, color TEXT, url TEXT, image TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS products_forever21_womens_uniq        ON products_forever21_womens        (title, COALESCE(color,''), COALESCE(image,''));

CREATE TABLE IF NOT EXISTS products_brandy_melville         (id SERIAL PRIMARY KEY, title TEXT NOT NULL, price TEXT, color TEXT, url TEXT, image TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS products_brandy_melville_uniq         ON products_brandy_melville         (title, COALESCE(color,''), COALESCE(image,''));

CREATE TABLE IF NOT EXISTS products_zara_mens               (id SERIAL PRIMARY KEY, title TEXT NOT NULL, price TEXT, color TEXT, url TEXT, image TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS products_zara_mens_uniq               ON products_zara_mens               (title, COALESCE(color,''), COALESCE(image,''));

CREATE TABLE IF NOT EXISTS products_zara_womens             (id SERIAL PRIMARY KEY, title TEXT NOT NULL, price TEXT, color TEXT, url TEXT, image TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS products_zara_womens_uniq             ON products_zara_womens             (title, COALESCE(color,''), COALESCE(image,''));

CREATE TABLE IF NOT EXISTS products_aritzia                 (id SERIAL PRIMARY KEY, title TEXT NOT NULL, price TEXT, color TEXT, url TEXT, image TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS products_aritzia_uniq                 ON products_aritzia                 (title, COALESCE(color,''), COALESCE(image,''));

CREATE TABLE IF NOT EXISTS products_urban_outfitters_womens (id SERIAL PRIMARY KEY, title TEXT NOT NULL, price TEXT, color TEXT, url TEXT, image TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS products_urban_outfitters_womens_uniq ON products_urban_outfitters_womens (title, COALESCE(color,''), COALESCE(image,''));

CREATE TABLE IF NOT EXISTS products_princesspolly           (id SERIAL PRIMARY KEY, title TEXT NOT NULL, price TEXT, color TEXT, url TEXT, image TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS products_princesspolly_uniq           ON products_princesspolly           (title, COALESCE(color,''), COALESCE(image,''));

CREATE TABLE IF NOT EXISTS products_boohooman               (id SERIAL PRIMARY KEY, title TEXT NOT NULL, price TEXT, color TEXT, url TEXT, image TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS products_boohooman_uniq               ON products_boohooman               (title, COALESCE(color,''), COALESCE(image,''));

CREATE TABLE IF NOT EXISTS products_nike_mens               (id SERIAL PRIMARY KEY, title TEXT NOT NULL, price TEXT, color TEXT, url TEXT, image TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS products_nike_mens_uniq               ON products_nike_mens               (title, COALESCE(color,''), COALESCE(image,''));

CREATE TABLE IF NOT EXISTS products_nike_womens             (id SERIAL PRIMARY KEY, title TEXT NOT NULL, price TEXT, color TEXT, url TEXT, image TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS products_nike_womens_uniq             ON products_nike_womens             (title, COALESCE(color,''), COALESCE(image,''));

CREATE TABLE IF NOT EXISTS products_uniqlo_womens           (id SERIAL PRIMARY KEY, title TEXT NOT NULL, price TEXT, color TEXT, url TEXT, image TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS products_uniqlo_womens_uniq           ON products_uniqlo_womens           (title, COALESCE(color,''), COALESCE(image,''));

CREATE TABLE IF NOT EXISTS products_uniqlo_mens             (id SERIAL PRIMARY KEY, title TEXT NOT NULL, price TEXT, color TEXT, url TEXT, image TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS products_uniqlo_mens_uniq             ON products_uniqlo_mens             (title, COALESCE(color,''), COALESCE(image,''));
