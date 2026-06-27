"""Aritzia scraper — uses Algolia search API via browser-context fetch.
Algolia returns deduplicated products, each with selectableColors[] containing
all color variants. Expands to one row per (product, color) for Supabase.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
import json, urllib.parse

from db_insert import insert_products, ensure_table

TABLE    = "products_aritzia"
BASE     = "https://www.aritzia.com"
IMG_BASE = "https://assets.aritzia.com/image/upload/c_crop,ar_1920:2623,g_south/q_auto,f_auto,dpr_auto"

ALGOLIA_APP = "SONLJM8OH6"
ALGOLIA_KEY = "1455bca7c6c33e746a0f38beb28422e6"
INDEX       = "production_ecommerce_aritzia__Aritzia_US__products__en_US"
HITS_PER_PAGE = 100

# Product-type categories — covers all clothing types; overlaps are fine
# (duplicates silently skipped by Supabase ON CONFLICT)
CATEGORIES = [
    "dresses",
    "tops",
    "pants",
    "sweaters",
    "shorts",
    "skirts",
    "jeans",
    "coats-jackets",
    "jackets",
    "accessories",
    "womens-workout-clothes",
    "sweatsuit-sets",
    "knitwear",
    "sweatshirts",
    "leggings-and-bike-shorts",
    "suits",
]

ALGOLIA_HEADERS = json.dumps({
    "x-algolia-application-id": ALGOLIA_APP,
    "x-algolia-api-key": ALGOLIA_KEY,
    "content-type": "application/json",
})


def p(*args):
    try:
        print(*args, flush=True)
    except UnicodeEncodeError:
        print(*(str(a).encode("ascii", "replace").decode() for a in args), flush=True)


def title_from_slug(slug):
    """Extract product title from Algolia slug like 'the-lodge-pant%E2%84%A2/118495.html'."""
    name_part = slug.rsplit("/", 1)[0]           # 'the-lodge-pant%E2%84%A2'
    decoded   = urllib.parse.unquote(name_part)   # 'the-lodge-pant™'
    return decoded.replace("-", " ").title()       # 'The Lodge Pant™'


def get_price(color):
    """Return current price string from selectableColors entry."""
    prices_list = color.get("prices") or []
    # prefer sale price
    for src in ("usd-sale-prices", "usd-list-prices"):
        for p_obj in prices_list:
            if p_obj.get("source") == src:
                vals = p_obj.get("prices") or []
                if vals:
                    return f"${float(vals[0]):.2f}"
    return ""


def get_image(color):
    """Return primary model image URL for a selectableColors entry."""
    color_ids = color.get("colorIds") or {}
    # Find the base colorId key (no '_N' suffix)
    for cid, images in color_ids.items():
        if "_" not in cid and images:
            # prefer '_on_a' (front-facing model shot)
            front = next((img for img in images if img.endswith("_on_a")), images[0])
            return f"{IMG_BASE}/{front}"
    return ""


def get_color_id(color):
    """Return the primary colorId (pure digits, no _N suffix)."""
    for cid in (color.get("colorIds") or {}):
        if "_" not in cid:
            return cid
    return ""


def parse_hits(hits):
    rows = []
    for hit in hits:
        slug = hit.get("slug") or ""
        title = (hit.get("c_displayName") or hit.get("name") or "").strip()
        if not title and slug:
            title = title_from_slug(slug)

        master_id = hit.get("masterId") or ""

        for color in hit.get("selectableColors") or []:
            color_name = (color.get("value") or "").strip().title()
            price      = get_price(color)
            image      = get_image(color)
            color_id   = get_color_id(color)

            url = f"{BASE}/us/en/product/{slug}?color={color_id}" if slug else ""

            if not title or not url:
                continue

            rows.append({
                "title": title,
                "color": color_name,
                "price": price,
                "image": image,
                "url":   url,
            })
    return rows


def search_page(page, category, pg):
    body = json.dumps({
        "query": "",
        "hitsPerPage": HITS_PER_PAGE,
        "page": pg,
        "filters": f"categories:{category}",
        "attributesToRetrieve": [
            "name", "c_displayName", "masterId", "slug",
            "selectableColors", "price", "onSale",
        ],
    })
    result = page.evaluate(f"""
        async () => {{
            const r = await fetch(
                'https://search-0.aritzia.com/1/indexes/{INDEX}/query',
                {{
                    method: 'POST',
                    headers: {ALGOLIA_HEADERS},
                    body: {json.dumps(body)},
                }}
            );
            return await r.json();
        }}
    """)
    return result


def scrape_category(page, category):
    p(f"\n  [{category}] fetching page 0 for count...")
    data0 = search_page(page, category, 0)
    nb_hits  = int(data0.get("nbHits")  or 0)
    nb_pages = int(data0.get("nbPages") or 1)
    p(f"  [{category}] {nb_hits} products, {nb_pages} pages")

    inserted = skipped = 0

    for pg in range(nb_pages):
        data = search_page(page, category, pg) if pg > 0 else data0
        hits = data.get("hits") or []
        rows = parse_hits(hits)
        if rows:
            ins, skip = insert_products(TABLE, rows)
            inserted += ins
            skipped  += skip
        p(f"    page {pg+1}/{nb_pages}: {len(hits)} hits → {len(rows)} rows → "
          f"{ins if rows else 0} inserted, {skip if rows else 0} skipped")

    return inserted, skipped


def main():
    p(f"Aritzia scraper → table: {TABLE}")
    ensure_table(TABLE)

    total_ins = total_skip = 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.new_page()
        Stealth().apply_stealth_sync(page)

        p("Loading Aritzia homepage...")
        page.goto(BASE + "/us/en", timeout=60000)
        page.wait_for_timeout(5000)

        for cat in CATEGORIES:
            ins, skip = scrape_category(page, cat)
            total_ins  += ins
            total_skip += skip
            p(f"  [{cat}] total: {ins} inserted, {skip} skipped")

        browser.close()

    p(f"\n{'='*60}")
    p(f"DONE! {total_ins} inserted, {total_skip} skipped")


if __name__ == "__main__":
    main()
