"""Express scraper — GraphQL CategoryQuery, one row per color per product."""
import sys, os, json, math
sys.path.insert(0, os.path.dirname(__file__))
from db_insert import ensure_table, insert_products
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

TABLE = "products_express"
BASE = "https://www.express.com"

# (display_name, category_id, url_slug)
CATEGORIES = [
    ("men",   "cat5050346", "mens-clothing"),
    ("women", "cat5050343", "womens-clothing"),
]

IMAGE_BASE = "https://images.express.com/is/image/expressfashion"
PAGE_SIZE = 56


def p(*args):
    try:
        print(*args, flush=True)
    except UnicodeEncodeError:
        print(*(str(a).encode("ascii", "replace").decode() for a in args), flush=True)


def parse_products(cat_data):
    """Expand each product by colors → one row per color."""
    rows = []
    for prod in cat_data.get('products', []):
        title = (prod.get('name') or '').strip()
        pid = prod.get('productId', '')
        product_url = prod.get('productURL', '')
        url = f"{BASE}{product_url}" if product_url.startswith('/') else product_url
        # Price: prefer salePrice if present
        list_price = prod.get('listPrice') or ''
        sale_price = prod.get('salePrice') or ''
        price = sale_price if sale_price and sale_price != list_price else list_price

        if not title or not pid:
            continue

        colors = prod.get('colors') or []
        if not colors:
            # No color info — one row with empty color
            image = prod.get('productImage', '')
            rows.append({'title': title, 'price': price, 'color': '', 'url': url, 'image': image})
        else:
            seen_colors = set()
            for c in colors:
                color_name = (c.get('color') or '').strip().title()
                if not color_name or color_name in seen_colors:
                    continue
                seen_colors.add(color_name)
                # Build image URL from imageSet (prefer _f001 front view)
                image_set = c.get('imageSet') or []
                img_code = next((s for s in image_set if '_f001' in s), image_set[0] if image_set else '')
                image = f"{IMAGE_BASE}/{img_code}" if img_code else prod.get('productImage', '')
                rows.append({'title': title, 'price': price, 'color': color_name, 'url': url, 'image': image})
    return rows


def scrape_category(page, gender, cat_id, slug):
    """Scrape all pages of a category and return rows."""
    all_rows = []
    total_pages = None
    pg = 1

    while True:
        url = f"{BASE}/{slug}/{cat_id}" if pg == 1 else f"{BASE}/{slug}/{cat_id}/page/{pg}"
        p(f"  Page {pg}: {url}")

        response_holder = [None]

        def on_response(resp):
            if 'express.com/graphql' in resp.url and resp.status == 200:
                try:
                    body = resp.text()
                    if '"getUnbxdCategory"' in body:
                        response_holder[0] = body
                except Exception:
                    pass

        page.on("response", on_response)
        page.goto(url, timeout=60000)
        page.wait_for_timeout(8000)
        page.remove_listener("response", on_response)

        if not response_holder[0]:
            p(f"  No CategoryQuery response — stopping")
            break

        data = json.loads(response_holder[0])
        cat_data = data.get('data', {}).get('getUnbxdCategory', {})
        pag = cat_data.get('pagination', {})
        products = cat_data.get('products', [])

        if total_pages is None:
            total_count = pag.get('totalProductCount', 0)
            total_pages = math.ceil(total_count / PAGE_SIZE) if total_count else 1
            p(f"  Total products: {total_count}, pages: {total_pages}")

        rows = parse_products(cat_data)
        all_rows.extend(rows)
        p(f"  {len(products)} products, {len(rows)} color rows")

        if pg >= total_pages or len(products) < PAGE_SIZE:
            break
        pg += 1
        page.wait_for_timeout(500)

    return all_rows


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

        p("Loading homepage for session...")
        page.goto(BASE, timeout=60000)
        page.wait_for_timeout(6000)

        for gender, cat_id, slug in CATEGORIES:
            p(f"\n=== {gender.upper()} ({cat_id}) ===")
            rows = scrape_category(page, gender, cat_id, slug)
            p(f"  Total rows: {len(rows)}")
            ins, skip = insert_products(TABLE, rows)
            total_ins += ins
            total_skip += skip
            p(f"  Inserted: {ins}, Skipped: {skip}")

        browser.close()

    p(f"\n{'='*50}")
    p(f"DONE! {total_ins} inserted, {total_skip} skipped")


if __name__ == "__main__":
    main()
