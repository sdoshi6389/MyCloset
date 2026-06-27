"""Champion scraper — Shopify /collections/all/products.json, one product per color."""
import sys, os, json
sys.path.insert(0, os.path.dirname(__file__))
from db_insert import ensure_table, insert_products
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

TABLE = "products_champion"
BASE = "https://www.champion.com"
LIMIT = 250


def p(*args):
    try:
        print(*args, flush=True)
    except UnicodeEncodeError:
        print(*(str(a).encode("ascii", "replace").decode() for a in args), flush=True)


def parse_products(raw):
    rows = []
    for prod in raw:
        title = (prod.get('title') or '').strip()
        handle = prod.get('handle', '')
        if not title or not handle:
            continue

        variants = prod.get('variants') or []
        images = prod.get('images') or []
        options = prod.get('options') or []

        # Color from first Color-named option
        color = ''
        color_option_pos = next(
            (opt['position'] for opt in options if opt.get('name', '').lower() == 'color'),
            None
        )
        if color_option_pos and variants:
            color = (variants[0].get(f"option{color_option_pos}") or '').strip()

        price_raw = variants[0].get('price') if variants else None
        price = f"${float(price_raw):.2f}" if price_raw else ''
        image = images[0].get('src', '') if images else ''
        url = f"{BASE}/products/{handle}"

        rows.append({'title': title, 'price': price, 'color': color, 'url': url, 'image': image})
    return rows


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

        page.goto(BASE, timeout=60000)
        page.wait_for_timeout(3000)

        pg_num = 1
        while True:
            raw = page.evaluate(f"""
                async () => {{
                    const r = await fetch('{BASE}/collections/all/products.json?limit={LIMIT}&page={pg_num}');
                    const d = await r.json();
                    return d.products || [];
                }}
            """)
            if not raw:
                break

            rows = parse_products(raw)
            ins, skip = insert_products(TABLE, rows)
            total_ins += ins
            total_skip += skip
            p(f"Page {pg_num}: {len(raw)} fetched -> {ins} inserted, {skip} skipped")

            if len(raw) < LIMIT:
                break
            pg_num += 1
            page.wait_for_timeout(400)

        browser.close()

    p(f"\n{'='*50}")
    p(f"DONE! {total_ins} inserted, {total_skip} skipped")


if __name__ == "__main__":
    main()
