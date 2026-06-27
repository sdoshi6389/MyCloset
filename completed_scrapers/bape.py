"""BAPE scraper — Shopify products.json via browser context, one row per color."""
import sys, os, json
sys.path.insert(0, os.path.dirname(__file__))
from db_insert import ensure_table, insert_products
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

TABLE = "products_bape"
BASE = "https://us.bape.com"
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

        variants = prod.get('variants') or []
        options = prod.get('options') or []
        images = prod.get('images') or []

        # Find color option index
        color_idx = None
        for i, opt in enumerate(options):
            if opt.get('name', '').lower() == 'color':
                color_idx = i
                break

        # Fallback image map: variant_id → image src
        vid_to_img = {}
        for img in images:
            for vid in (img.get('variant_ids') or []):
                vid_to_img[vid] = img.get('src', '')
        first_img = images[0].get('src', '') if images else ''

        seen_colors = set()
        for variant in variants:
            color = ''
            if color_idx is not None:
                color = (variant.get(f'option{color_idx + 1}') or '').strip()

            if color in seen_colors:
                continue
            seen_colors.add(color)

            raw_price = variant.get('price', '')
            try:
                price = f"${float(raw_price):.2f}" if raw_price else ''
            except ValueError:
                price = raw_price

            # Prefer variant's featured_image, then vid_to_img, then first_img
            fi = variant.get('featured_image') or {}
            image = fi.get('src', '') or vid_to_img.get(variant.get('id'), first_img) or first_img

            out.append({'title': title, 'price': price, 'color': color, 'url': url, 'image': image})

        if not seen_colors:
            price = ''
            if variants:
                raw = variants[0].get('price', '')
                try:
                    price = f"${float(raw):.2f}" if raw else ''
                except ValueError:
                    price = raw
            out.append({'title': title, 'price': price, 'color': '', 'url': url, 'image': first_img})

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
            p(f"  Page {page_num}: {len(raw)} products → {len(products)} rows → {ins} inserted, {skip} skipped")
            if len(raw) < LIMIT:
                p(f"  Last page ({len(raw)} < {LIMIT})")
                break
            page_num += 1
            pg.wait_for_timeout(300)

        browser.close()

    p(f"\n{'='*50}")
    p(f"DONE! {total_fetched} products fetched, {total_ins} rows inserted, {total_skip} skipped")


if __name__ == "__main__":
    main()
