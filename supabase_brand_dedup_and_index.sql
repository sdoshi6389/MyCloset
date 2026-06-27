-- Deduplicate existing rows and add unique index on (title, color, image)
-- to all brand product tables. Safe to re-run.

DO $$
DECLARE
  t TEXT;
  tables TEXT[] := ARRAY[
    'products_gymshark_mens','products_gymshark_womens',
    'products_hollister_mens','products_hollister_womens',
    'products_essentials_mens','products_essentials_womens',
    'products_hm_womens','products_hm_mens',
    'products_cottonon_mens','products_cottonon_womens',
    'products_abercrombie_mens','products_abercrombie_womens',
    'products_alo_mens','products_alo_womens',
    'products_forever21_mens','products_forever21_womens',
    'products_brandy_melville',
    'products_zara_mens','products_zara_womens',
    'products_aritzia','products_urban_outfitters_womens',
    'products_princesspolly','products_boohooman',
    'products_nike_mens','products_nike_womens'
  ];
BEGIN
  FOREACH t IN ARRAY tables LOOP
    -- Step 1: remove duplicate rows, keep highest id per (title, color, image)
    EXECUTE format(
      'DELETE FROM %I WHERE id NOT IN (
         SELECT MAX(id) FROM %I
         GROUP BY title, COALESCE(color, ''''), COALESCE(image, '''')
       )',
      t, t
    );

    -- Step 2: add unique index (skip if already exists)
    EXECUTE format(
      'CREATE UNIQUE INDEX IF NOT EXISTS %I ON %I
       (title, COALESCE(color, ''''), COALESCE(image, ''''))',
      t || '_uniq', t
    );

    RAISE NOTICE 'Done: %', t;
  END LOOP;
END$$;
