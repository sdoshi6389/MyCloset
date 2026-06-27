"""Carhartt scraper — SAP Hybris API via browser-context fetch, one row per color."""
import sys, os, json
sys.path.insert(0, os.path.dirname(__file__))
from db_insert import ensure_table, insert_products
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

TABLE = "products_carhartt"
BASE = "https://www.carhartt.com"
API = "https://api-c4prd1.carhartt.com"
PAGE_SIZE = 100

# (url_category_code, hybris_category_code)
CATEGORIES = [
    ("men", "men"),
    ("womens", "womens"),
]

def p(*args):
    try:
        print(*args, flush=True)
    except UnicodeEncodeError:
        print(*(str(a).encode("ascii", "replace").decode() for a in args), flush=True)


def fetch_page(page, category_code, current_page):
    url = (
        f"{API}/ws/v2/carhartt/products/search"
        f"?query=%3Arelevance%3AallCategories%3A{category_code}"
        f"&fields=FULL&pageSize={PAGE_SIZE}&currentPage={current_page}"
        f"&lang=en&curr=USD&countryIsoCode=US"
    )
    result = page.evaluate(f"""
        async () => {{
            try {{
                const r = await fetch({json.dumps(url)}, {{
                    headers: {{
                        'Accept': 'application/json',
                        'Origin': 'https://www.carhartt.com',
                        'Referer': 'https://www.carhartt.com/',
                    }}
                }});
                if (!r.ok) return {{error: 'HTTP ' + r.status}};
                return await r.json();
            }} catch(e) {{
                return {{error: e.message}};
            }}
        }}
    """)
    if not isinstance(result, dict) or 'error' in result:
        p(f"  Page {current_page} error: {result}")
        return [], 0
    pagination = result.get('pagination', {})
    total_pages = pagination.get('totalPages', 0)
    products = result.get('products', [])
    return products, total_pages


def parse_product(prod):
    title = (prod.get('name') or '').strip()
    if not title:
        return []

    url_path = (prod.get('url') or '').strip()
    if not url_path:
        return []

    current_color_code = (prod.get('colorCode') or '').strip()
    color_options = prod.get('colorOptions') or []

    # Find human-readable color name for the current color
    color_name = current_color_code
    for opt in color_options:
        if opt.get('colorCode') == current_color_code:
            color_name = opt.get('colorName') or current_color_code
            break

    # Price: use lowest selling price
    price = ''
    price_range = prod.get('priceRange') or {}
    min_price = price_range.get('minPrice') or {}
    price_val = min_price.get('value')
    if price_val is not None:
        try:
            price = f"${float(price_val):.2f}"
        except (TypeError, ValueError):
            price = str(price_val)
    else:
        # Fallback to MSRP
        msrp = prod.get('msrpRange') or {}
        msrp_min = msrp.get('minPrice') or {}
        price = msrp_min.get('formattedValue', '')

    # Image
    images = prod.get('images') or []
    image = images[0].get('url', '') if images else ''

    # Full URL
    product_url = BASE + url_path if url_path.startswith('/') else url_path

    return [{'title': title, 'price': price, 'color': color_name, 'url': product_url, 'image': image}]


def scrape_category(pg, category_label, category_code):
    p(f"\n[{category_label}] Starting category '{category_code}'...")
    total_ins = 0
    total_skip = 0
    total_fetched = 0

    # Get first page to find total pages
    products, total_pages = fetch_page(pg, category_code, 0)
    if not products:
        p(f"  No products returned for category '{category_code}'")
        return 0, 0

    p(f"  Total pages: {total_pages}")

    rows = []
    for prod in products:
        rows.extend(parse_product(prod))
    total_fetched += len(products)

    ins, skip = insert_products(TABLE, rows)
    total_ins += ins
    total_skip += skip
    p(f"  Page 0: {len(products)} products -> {len(rows)} rows -> {ins} inserted, {skip} skipped")

    for pg_num in range(1, total_pages):
        products, _ = fetch_page(pg, category_code, pg_num)
        if not products:
            p(f"  Page {pg_num}: no products, stopping")
            break
        rows = []
        for prod in products:
            rows.extend(parse_product(prod))
        total_fetched += len(products)
        ins, skip = insert_products(TABLE, rows)
        total_ins += ins
        total_skip += skip
        p(f"  Page {pg_num}: {len(products)} products -> {len(rows)} rows -> {ins} inserted, {skip} skipped")
        pg.wait_for_timeout(300)

    p(f"  [{category_label}] Done: {total_fetched} fetched, {total_ins} inserted, {total_skip} skipped")
    return total_ins, total_skip


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

        p("Loading Carhartt homepage to establish session...")
        pg.goto(BASE, timeout=60000)
        pg.wait_for_timeout(5000)

        for label, code in CATEGORIES:
            ins, skip = scrape_category(pg, label, code)
            grand_ins += ins
            grand_skip += skip

        browser.close()

    p(f"\n{'='*50}")
    p(f"DONE! Total: {grand_ins} inserted, {grand_skip} skipped")


if __name__ == "__main__":
    main()
