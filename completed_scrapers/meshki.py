"""Meshki scraper — Shopify products.json via browser context."""
import sys, os, json
sys.path.insert(0, os.path.dirname(__file__))
from db_insert import ensure_table, insert_products
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

TABLE = "products_meshki"
BASE = "https://www.meshki.com.au"
LIMIT = 250

def p(*args):
    try:
        print(*args, flush=True)
    except UnicodeEncodeError:
        print(*(str(a).encode("ascii", "replace").decode() for a in args), flush=True)


def fetch_page(page, pg):
    url = f"{BASE}/collections/all/products.json?limit={LIMIT}&page={pg}"
    result = page.evaluate(f"""
        async () => {{
            const resp = await fetch({json.dumps(url)}, {{
                headers: {{'Accept': 'application/json'}}
            }});
            if (!resp.ok) return {{error: 'HTTP ' + resp.status}};
            return await resp.json();
        }}
    """)
    if not isinstance(result, dict) or 'error' in result:
        p(f"  Page {pg} error: {result}")
        return []
    return result.get('products', [])


def parse_products(raw_products):
    out = []
    for prod in raw_products:
        full_title = (prod.get('title') or '').strip()
        handle = prod.get('handle', '')
        if not full_title or not handle:
            continue
        url = f"{BASE}/products/{handle}"

        # Title format: "STYLE - COLOR"
        if ' - ' in full_title:
            parts = full_title.split(' - ', 1)
            title = parts[0].strip()
            color = parts[1].strip()
        else:
            title = full_title
            color = ''

        variants = prod.get('variants') or []
        price = ''
        if variants:
            raw = variants[0].get('price', '')
            try:
                price = f"${float(raw):.2f}" if raw else ''
            except ValueError:
                price = raw

        images = prod.get('images') or []
        image = images[0].get('src', '') if images else ''

        out.append({'title': title, 'price': price, 'color': color, 'url': url, 'image': image})
    return out


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
        pg = ctx.new_page()
        Stealth().apply_stealth_sync(pg)

        p("Loading homepage to establish session...")
        pg.goto(BASE, timeout=60000)
        pg.wait_for_timeout(4000)

        page_num = 1
        total_fetched = 0
        while True:
            raw = fetch_page(pg, page_num)
            if not raw:
                p(f"  Page {page_num}: no products — stopping")
                break
            products = parse_products(raw)
            total_fetched += len(raw)
            ins, skip = insert_products(TABLE, products)
            total_ins += ins
            total_skip += skip
            p(f"  Page {page_num}: {len(raw)} fetched -> {ins} inserted, {skip} skipped")
            if len(raw) < LIMIT:
                p(f"  Last page ({len(raw)} < {LIMIT})")
                break
            page_num += 1
            pg.wait_for_timeout(300)

        browser.close()

    p(f"\n{'='*50}")
    p(f"DONE! Total fetched: {total_fetched}, {total_ins} inserted, {total_skip} skipped")


if __name__ == "__main__":
    main()
