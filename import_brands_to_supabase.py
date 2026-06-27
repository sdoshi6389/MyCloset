"""
Import all brand CSVs into Supabase via REST API.

Run:
    python import_brands_to_supabase.py

Creates brand product tables if they don't exist, then inserts all rows.
Safe to re-run — clears and reloads each table.
"""

import csv
import json
import os
import urllib.request
import urllib.error
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

SUPABASE_URL = os.environ["SUPABASE_URL"]
SERVICE_KEY  = os.environ["SUPABASE_KEY"]

BASE_HEADERS = {
    "apikey":        SERVICE_KEY,
    "Authorization": f"Bearer {SERVICE_KEY}",
    "Content-Type":  "application/json",
    "Prefer":        "return=minimal",
}

BATCH_SIZE = 200

CSV_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "completed_csv_files_from_scrapers")
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

FILE_TO_TABLE = {
    "gymshark_mens_full.csv":           "products_gymshark_mens",
    "gymshark_womens_full.csv":         "products_gymshark_womens",
    "hollister_mens_full.csv":          "products_hollister_mens",
    "hollister_womens_full.csv":        "products_hollister_womens",
    "essentials_mens.csv":              "products_essentials_mens",
    "essentials_women.csv":             "products_essentials_womens",
    "hm_women_products.csv":            "products_hm_womens",
    "hm_men_products.csv":              "products_hm_mens",
    "cottonon_men_products.csv":        "products_cottonon_mens",
    "cottonon_women_products.csv":      "products_cottonon_womens",
    "abercrombie_men_products.csv":     "products_abercrombie_mens",
    "abercrombie_women_products.csv":   "products_abercrombie_womens",
    "alo_men_products.csv":             "products_alo_mens",
    "alo_women_products.csv":           "products_alo_womens",
    "forever21_men_products.csv":       "products_forever21_mens",
    "forever21_women_products.csv":     "products_forever21_womens",
    "brandy_melville_all_products.csv": "products_brandy_melville",
    "zara_men.csv":                     "products_zara_mens",
    "zara_women.csv":                   "products_zara_womens",
    "aritzia.csv":                      "products_aritzia",
    "urban_outfitters_women.csv":       "products_urban_outfitters_womens",
    "princesspolly.csv":                "products_princesspolly",
    "boohooman.csv":                    "products_boohooman",
    "nike_men.csv":                     "products_nike_mens",
    "nike_women.csv":                   "products_nike_womens",
}


def fetch_existing_keys(table: str) -> set:
    """Fetch all (title, color, image) combos already in the table."""
    existing = set()
    offset = 0
    page = 1000  # Stay within PostgREST's default max-rows
    while True:
        url = f"{SUPABASE_URL}/rest/v1/{table}?select=title,color,image"
        req = urllib.request.Request(url, headers={
            **BASE_HEADERS,
            "Range": f"{offset}-{offset + page - 1}",
        }, method="GET")
        try:
            with urllib.request.urlopen(req) as resp:
                rows = json.loads(resp.read())
                # Content-Range: "start-end/total" lets us detect the real end
                content_range = resp.headers.get("Content-Range", "")
        except urllib.error.HTTPError as e:
            if e.code == 416:   # range not satisfiable = no more rows
                break
            raise RuntimeError(f"GET {table} failed HTTP {e.code}: {e.read().decode()}")
        if not rows:
            break
        for r in rows:
            existing.add((r["title"], r["color"] or "", r["image"] or ""))
        # Use Content-Range to detect end precisely; fall back to row-count heuristic
        done = False
        try:
            range_part, total_str = content_range.rsplit("/", 1)
            if total_str != "*":
                end_idx = int(range_part.split("-")[1])
                done = (end_idx + 1) >= int(total_str)
                offset = end_idx + 1
            else:
                done = len(rows) < page
                offset += len(rows)
        except (ValueError, IndexError, AttributeError):
            done = len(rows) < page
            offset += page
        if done:
            break
    return existing


def ensure_brand_table(table: str):
    """Create the table (if missing) and add combined_embedding column (if missing) via RPC."""
    url = f"{SUPABASE_URL}/rest/v1/rpc/ensure_brand_table"
    data = json.dumps({"tbl": table}).encode()
    req = urllib.request.Request(url, data=data, headers={
        **BASE_HEADERS,
        "Content-Type": "application/json",
    }, method="POST")
    try:
        with urllib.request.urlopen(req):
            pass
    except urllib.error.HTTPError as e:
        print(f"  Warning: ensure_brand_table({table}) failed: {e.read().decode()}")


def rest_insert(table: str, rows: list):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    data = json.dumps(rows).encode()
    req = urllib.request.Request(url, data=data, headers={
        **BASE_HEADERS, "Prefer": "return=minimal"
    }, method="POST")
    try:
        with urllib.request.urlopen(req):
            pass
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"INSERT failed HTTP {e.code}: {e.read().decode()}")


def find_csv(filename: str) -> str | None:
    for directory in [CSV_DIR, ROOT_DIR]:
        path = os.path.join(directory, filename)
        if os.path.exists(path):
            return path
    return None


def load_csv(csv_path: str) -> list:
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            title = row.get("title", "").strip()
            if not title:
                continue
            rows.append({
                "title": title,
                "price": row.get("price", "").strip() or None,
                "color": row.get("color", "").strip() or None,
                "url":   row.get("url",   "").strip() or None,
                "image": row.get("image", "").strip() or None,
            })
    return rows


def import_table(csv_path: str, table: str) -> tuple:
    """Returns (inserted, skipped)."""
    rows = load_csv(csv_path)
    if not rows:
        return 0, 0

    existing = fetch_existing_keys(table)

    # Filter against Supabase AND deduplicate within the CSV itself.
    # Some CSVs have rows that share the same (title, color, image) key —
    # e.g. scraper placeholder images shared across many failed products.
    seen = set()
    new_rows = []
    for r in rows:
        key = (r["title"], r["color"] or "", r["image"] or "")
        if key not in existing and key not in seen:
            seen.add(key)
            new_rows.append(r)

    skipped = len(rows) - len(new_rows)
    if not new_rows:
        return 0, skipped

    for i in range(0, len(new_rows), BATCH_SIZE):
        batch = new_rows[i : i + BATCH_SIZE]
        rest_insert(table, batch)
        print(f"\r    {min(i + BATCH_SIZE, len(new_rows))}/{len(new_rows)} inserting...", end="", flush=True)
    print()
    return len(new_rows), skipped


def main():
    seen_tables = set()
    total_rows = 0
    total_tables = 0

    for filename, table in FILE_TO_TABLE.items():
        if table in seen_tables:
            continue

        csv_path = find_csv(filename)
        if not csv_path:
            print(f"  SKIP  {filename} (not found)")
            continue

        seen_tables.add(table)
        ensure_brand_table(table)
        print(f"  {filename} → {table}")
        try:
            inserted, skipped = import_table(csv_path, table)
            total_rows += inserted
            total_tables += 1
            print(f"  OK  {inserted} new rows inserted, {skipped} duplicates skipped")
        except Exception as e:
            print(f"  FAILED: {e}")

    print(f"\nDone! {total_rows} rows across {total_tables} brand tables imported.")


if __name__ == "__main__":
    main()
