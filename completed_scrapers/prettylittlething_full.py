"""PrettyLittleThing — full scrape by categoryTaxonomy to bypass 10k Algolia limit."""
import sys, os, json
sys.path.insert(0, os.path.dirname(__file__))
from db_insert import ensure_table, insert_products
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

TABLE = "products_prettylittlething"
BASE = "https://www.prettylittlething.com"
ALGOLIA_APP_ID = "PBL6WQH9VL"
ALGOLIA_API_KEY = "aca5366ccc1a1abd3118258c97c7322f"
ALGOLIA_INDEX = "prettylittlething-dbz-prod"
ALGOLIA_URL = f"https://{ALGOLIA_APP_ID}-dsn.algolia.net/1/indexes/*/queries"
HITS_PER_PAGE = 100

# All 43 categoryTaxonomy values (sorted largest first to catch big ones early)
CATEGORIES = [
    "Dresses", "Tops", "Skirts", "Trousers", "Jackets & Coats", "Swimwear",
    "T-Shirts", "Accessories", "Shorts", "Knitwear", "Jeans", "Joggers",
    "Shirts", "Playsuits", "Jumpsuits", "Hoodies & Sweatshirts", "Beachwear",
    "Co-ords", "Shoes", "Heels", "Boots", "Lingerie", "Leggings", "Nightwear",
    "Flats", "Sunglasses", "Skin", "Face", "Lips", "Beauty Tools", "Sandals",
    "Tailoring", "Free Gifts", "Fragrance", "Jumpers & Cardigans", "Brows",
    "Eyes", "Gloves & Scarves", "Hair Styling", "Hair Styling Tools", "Hats",
    "Lashes", "Suncare & Tanning",
]


def p(*args):
    try:
        print(*args, flush=True)
    except UnicodeEncodeError:
        print(*(str(a).encode("ascii", "replace").decode() for a in args), flush=True)


def fetch_page(page, category, pg_num):
    body = json.dumps({
        "requests": [{
            "indexName": ALGOLIA_INDEX,
            "params": "&".join([
                f"hitsPerPage={HITS_PER_PAGE}",
                f"page={pg_num}",
                "distinct=true",
                "facetFilters=" + json.dumps([
                    ["brand:prettylittlething"],
                    [f"categoryTaxonomy:{category}"],
                ]),
            ])
        }]
    })
    result = page.evaluate(f"""
        async () => {{
            const r = await fetch({json.dumps(ALGOLIA_URL)}, {{
                method: "POST",
                headers: {{
                    "Content-Type": "application/json",
                    "x-algolia-application-id": "{ALGOLIA_APP_ID}",
                    "x-algolia-api-key": "{ALGOLIA_API_KEY}",
                }},
                body: {json.dumps(body)}
            }});
            return await r.json();
        }}
    """)
    if 'results' not in result:
        p(f"    Page {pg_num} error: {str(result)[:200]}")
        return [], 0
    res0 = result['results'][0]
    return res0.get('hits', []), res0.get('nbPages', 0)


def parse_hits(hits):
    out = []
    for h in hits:
        name = (h.get('name') or '').strip()
        slug = (h.get('slug') or '').strip()
        if not name or not slug:
            continue
        color = (h.get('colourFacet') or h.get('colour') or '').strip()
        price_raw = h.get('price')
        try:
            price = f"${float(price_raw):.2f}" if price_raw is not None else ''
        except (ValueError, TypeError):
            price = ''
        images = h.get('images') or []
        image = images[0] if images else ''
        url = f"{BASE}/{slug}.html"
        out.append({'title': name, 'price': price, 'color': color, 'url': url, 'image': image})
    return out


def main():
    ensure_table(TABLE)
    grand_ins = 0
    grand_skip = 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            locale="en-US", viewport={"width": 1280, "height": 900},
        )
        pg = ctx.new_page()
        Stealth().apply_stealth_sync(pg)

        p("Loading homepage to establish session...")
        pg.goto(BASE, timeout=60000)
        pg.wait_for_timeout(4000)

        for cat_idx, category in enumerate(CATEGORIES):
            p(f"\n[{cat_idx+1}/{len(CATEGORIES)}] Category: {category!r}")
            cat_ins = 0
            cat_skip = 0
            page_num = 0
            nb_pages = None

            while True:
                hits, nb = fetch_page(pg, category, page_num)
                if nb_pages is None:
                    nb_pages = nb
                if not hits:
                    break
                products = parse_hits(hits)
                ins, skip = insert_products(TABLE, products)
                cat_ins += ins
                cat_skip += skip
                if page_num == 0:
                    p(f"  Pages: {nb_pages}, first page: {len(hits)} hits")
                page_num += 1
                if page_num >= nb_pages:
                    break
                pg.wait_for_timeout(100)

            p(f"  Done: {cat_ins} inserted, {cat_skip} skipped")
            grand_ins += cat_ins
            grand_skip += cat_skip

        browser.close()

    p(f"\n{'='*50}")
    p(f"DONE! {grand_ins} new inserted, {grand_skip} skipped (duplicates)")


if __name__ == "__main__":
    main()
