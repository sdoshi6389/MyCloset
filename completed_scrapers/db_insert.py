"""Shared Supabase insert helper — uses direct REST (bypasses upsert_brand_products
RPC which has a persistent schema permission error on this project)."""
import os, json, requests
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client
from collections import defaultdict

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

_client = None
_url_constraint_cache = {}  # table -> True/False


def get_client():
    global _client
    if _client is None:
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


def _headers(extra=None):
    h = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    if extra:
        h.update(extra)
    return h


def ensure_table(table):
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/{table}",
        headers=_headers(),
        params={"limit": "0"},
        timeout=15,
    )
    if r.status_code not in (200, 206):
        raise RuntimeError(
            f"Table '{table}' not found in Supabase (HTTP {r.status_code}). "
            f"Add it to supabase_brand_schema.sql and run it in the SQL Editor."
        )


def _insert_one_by_one(table, batch):
    """Individual inserts; counts conflict errors as skipped."""
    supa = get_client()
    inserted = skip = 0
    for row in batch:
        try:
            supa.table(table).insert([row]).execute()
            inserted += 1
        except Exception:
            skip += 1
    return inserted, skip


def _insert_batch(table, batch):
    """
    Try batch insert with on_conflict=url (fast, accurate for tables that have a
    url unique constraint). Falls back to one-by-one inserts for tables that don't.
    """
    global _url_constraint_cache
    headers = _headers({
        "Prefer": "resolution=ignore-duplicates,return=representation,count=exact"
    })

    use_url = _url_constraint_cache.get(table, True)

    if use_url:
        resp = requests.post(
            f"{SUPABASE_URL}/rest/v1/{table}?on_conflict=url",
            headers=headers,
            json=batch,
            timeout=60,
        )
        if resp.status_code in (200, 201):
            _url_constraint_cache[table] = True
            inserted = len(resp.json())
            return inserted, len(batch) - inserted
        elif resp.status_code == 400 and "42P10" in resp.text:
            _url_constraint_cache[table] = False  # no url constraint — use fallback
        elif resp.status_code == 409:
            pass  # non-url conflict — use fallback
        else:
            print(f"  DB error: {resp.status_code} {resp.text[:200]}", flush=True)
            return 0, len(batch)

    return _insert_one_by_one(table, batch)


def insert_products(table, rows, batch_size=500):
    if not rows:
        return 0, 0

    clean = [
        {
            "title": r.get("title") or "",
            "price": r.get("price") or "",
            "color": r.get("color") or "",
            "url":   r.get("url")   or "",
            "image": r.get("image") or "",
        }
        for r in rows
    ]

    total_ins = total_skip = 0
    for i in range(0, len(clean), batch_size):
        ins, skip = _insert_batch(table, clean[i : i + batch_size])
        total_ins  += ins
        total_skip += skip

    supa = get_client()

    # Store images[] for scrapers that supply it (alo, gymshark, h&m).
    img_rows = [
        (r.get("url"), r.get("images"))
        for r in rows
        if r.get("url") and r.get("images") is not None
    ]
    if img_rows:
        for url, images in img_rows:
            try:
                supa.table(table).update({"images": images}).eq("url", url).execute()
            except Exception as e:
                print(f"  images update error: {e}", flush=True)

    # Store gender for scrapers that supply it (gymshark, h&m).
    gender_rows = [
        (r.get("url"), r.get("gender"))
        for r in rows
        if r.get("url") and r.get("gender")
    ]
    if gender_rows:
        by_gender = defaultdict(list)
        for url, g in gender_rows:
            by_gender[g].append(url)
        for g_val, urls in by_gender.items():
            for i in range(0, len(urls), batch_size):
                try:
                    supa.table(table).update({"gender": g_val}).in_(
                        "url", urls[i : i + batch_size]
                    ).execute()
                except Exception as e:
                    print(f"  gender update error: {e}", flush=True)

    return total_ins, total_skip
