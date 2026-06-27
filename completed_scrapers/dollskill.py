"""Dolls Kill scraper — Shopify products.json, color from variant option1."""
import sys, os, json
sys.path.insert(0, os.path.dirname(__file__))
from db_insert import ensure_table, insert_products
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

TABLE = "products_dollskill"
BASE = "https://www.dollskill.com"
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
        title = (prod.get('title') or '').strip()
        handle = prod.get('handle', '')
        if not title or not handle:
            continue
        url = f"{BASE}/products/{handle}"

        images = prod.get('images') or []
        image = images[0].get('src', '') if images else ''

        # Find which option index is Color
        options = prod.get('options') or []
        color_idx = None
        for i, opt in enumerate(options):
            if (opt.get('name') or '').lower() == 'color':
                color_idx = i
                break

        # One row per unique color (variants may repeat color across sizes)
        seen_colors = set()
        variants = prod.get('variants') or []
        for variant in variants:
            if color_idx is not None:
                color_key = f"option{color_idx + 1}"
                color_raw = (variant.get(color_key) or '').strip()
            else:
                color_raw = ''

            if color_raw in seen_colors:
                continue
            seen_colors.add(color_raw)

            color = color_raw.title()

            price_raw = variant.get('price', '')
            try:
                price = f"${float(price_raw):.2f}" if price_raw else ''
            except ValueError:
                price = price_raw

            out.append({'title': title, 'price': price, 'color': color, 'url': url, 'image': image})

        # Fallback: no variants
        if not variants:
            out.append({'title': title, 'price': '', 'color': '', 'url': url, 'image': image})

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
            p(f"  Page {page_num}: {len(raw)} raw -> {len(products)} rows -> {ins} inserted, {skip} skipped")
            if len(raw) < LIMIT:
                p(f"  Last page ({len(raw)} < {LIMIT})")
                break
            page_num += 1
            pg.wait_for_timeout(300)

        browser.close()

    p(f"\n{'='*50}")
    p(f"DONE! Total raw: {total_fetched}, {total_ins} inserted, {total_skip} skipped")


if __name__ == "__main__":
    main()
