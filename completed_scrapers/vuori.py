"""Vuori scraper — uses Algolia Storefront API via browser context."""
import sys, os, json, re
sys.path.insert(0, os.path.dirname(__file__))
from db_insert import ensure_table, insert_products
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

TABLE = "products_vuori"
BASE = "https://vuoriclothing.com"
ALGOLIA_URL = "https://p2mlbkgfds-dsn.algolia.net/1/indexes/*/queries"
ALGOLIA_APP_ID = "P2MLBKGFDS"
ALGOLIA_API_KEY = "7825c979763a41aae103633f760004f1"
HITS_PER_PAGE = 48

CATEGORIES = [
    ("womens",      "Women's"),
    ("mens",        "Men's"),
    ("accessories", "Accessories"),
]

ALGOLIA_FILTERS_BASE = (
    "(requires_shipping:false OR online_inventory_available:true OR tags:back-in-stock-enabled "
    "OR tags:coming-soon) AND NOT tags:findify-remove AND collections:{collection}"
)

ALGOLIA_ATTRS = [
    "objectID","title","handle","image","variants_min_price","product_type",
    "variants","tags","named_tags","return_policy","taxonomy_tier_1",
    "taxonomy_tier_2","taxonomy_tier_4","taxonomy_tier_5","description"
]

def p(*args):
    try:
        print(*args, flush=True)
    except UnicodeEncodeError:
        print(*(str(a).encode("ascii", "replace").decode() for a in args), flush=True)


def fetch_algolia_page(page, collection, page_num):
    """Fetch one page from Algolia via browser context."""
    body = {
        "requests": [{
            "indexName": "us_products",
            "analyticsTags": ["collection_view_query"],
            "attributesToRetrieve": ALGOLIA_ATTRS,
            "clickAnalytics": False,
            "distinct": True,
            "filters": ALGOLIA_FILTERS_BASE.replace("{collection}", collection),
            "hitsPerPage": HITS_PER_PAGE,
            "page": page_num,
            "userToken": "scraper"
        }]
    }
    result = page.evaluate(f"""
        async () => {{
            const resp = await fetch({json.dumps(ALGOLIA_URL)}, {{
                method: 'POST',
                headers: {{
                    'Content-Type': 'application/json',
                    'X-Algolia-Application-Id': {json.dumps(ALGOLIA_APP_ID)},
                    'X-Algolia-API-Key': {json.dumps(ALGOLIA_API_KEY)},
                }},
                body: {json.dumps(json.dumps(body))},
            }});
            if (!resp.ok) return {{error: 'HTTP ' + resp.status}};
            return await resp.json();
        }}
    """)
    if not isinstance(result, dict) or 'error' in result:
        p(f"  Algolia error: {result}")
        return [], 0, 0
    try:
        res = result['results'][0]
        hits = res.get('hits', [])
        nb_hits = res.get('nbHits', 0)
        nb_pages = res.get('nbPages', 0)
        return hits, nb_hits, nb_pages
    except (KeyError, IndexError) as e:
        p(f"  Parse error: {e}")
        return [], 0, 0


def hits_to_products(hits, collection):
    out = []
    for hit in hits:
        handle = hit.get('handle', '')
        title = hit.get('title', '').strip()
        if not title or not handle:
            continue
        url = f"{BASE}/products/{handle}"
        # Price: variants_min_price (appears to be in cents based on typical Shopify)
        price_raw = hit.get('variants_min_price', 0) or 0
        # Vuori prices are like 68.0 (dollars), not cents
        price = f"${price_raw:.2f}" if price_raw else ''
        # Color from named_tags
        named_tags = hit.get('named_tags', {}) or {}
        color = named_tags.get('color-group', '') or ''
        if isinstance(color, list):
            color = color[0] if color else ''
        # Image
        image = hit.get('image', '') or ''
        if image and not image.startswith('http'):
            image = 'https:' + image if image.startswith('//') else image
        out.append({'title': title, 'price': price, 'color': color, 'url': url, 'image': image})
    return out


def scrape_collection(page, collection, label):
    p(f"\n=== {label} ({collection}) ===")
    # Fetch page 0 to get total
    hits, nb_hits, nb_pages = fetch_algolia_page(page, collection, 0)
    if not hits:
        p(f"  No results")
        return []
    p(f"  Total: {nb_hits} products, {nb_pages} pages")

    all_products = []
    batch = hits_to_products(hits, collection)
    all_products.extend(batch)
    p(f"  Page 0: {len(batch)} products")

    for pg in range(1, nb_pages):
        hits, _, _ = fetch_algolia_page(page, collection, pg)
        if not hits:
            p(f"  Page {pg}: empty — stopping")
            break
        batch = hits_to_products(hits, collection)
        all_products.extend(batch)
        p(f"  Page {pg}: {len(batch)} products (total {len(all_products)})")
        page.wait_for_timeout(200)

    return all_products


def main():
    ensure_table(TABLE)
    total_ins = 0
    total_skip = 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            locale="en-US", viewport={"width": 1280, "height": 900},
        )
        page = ctx.new_page()
        Stealth().apply_stealth_sync(page)

        p("Loading homepage to establish session...")
        page.goto(BASE, timeout=60000)
        page.wait_for_timeout(5000)

        for collection, label in CATEGORIES:
            products = scrape_collection(page, collection, label)
            if products:
                ins, skip = insert_products(TABLE, products)
                total_ins += ins
                total_skip += skip
                p(f"  DB: {ins} inserted, {skip} skipped")

        browser.close()

    p(f"\n{'='*50}")
    p(f"DONE! Total: {total_ins} inserted, {total_skip} skipped (duplicates)")


if __name__ == "__main__":
    main()
