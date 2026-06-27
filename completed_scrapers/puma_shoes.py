"""Puma — scrape shoe categories missed in main run."""
import sys, os, json, re
sys.path.insert(0, os.path.dirname(__file__))
from db_insert import ensure_table, insert_products
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

TABLE = "products_puma"
BASE = "https://us.puma.com"
SITE = f"{BASE}/us/en"

# Try multiple shoe URL patterns
SHOE_CATEGORIES = [
    "/women/shoes",
    "/men/shoes",
    "/women/sneakers",
    "/men/sneakers",
    "/women/footwear/all",
    "/men/footwear/all",
]


def p(*args):
    try:
        print(*args, flush=True)
    except UnicodeEncodeError:
        print(*(str(a).encode("ascii", "replace").decode() for a in args), flush=True)


def slugify(name):
    s = name.lower()
    s = re.sub(r"['\"']", "", s)
    s = re.sub(r"[^a-z0-9\s\-]", " ", s)
    s = re.sub(r"\s+", "-", s.strip())
    return re.sub(r"-+", "-", s)


def parse_items(items, seen_keys):
    out = []
    for item in items:
        hit = item.get('productSearchHit') or {}
        master_id = hit.get('masterId', '')
        mp = hit.get('masterProduct') or {}
        name = (mp.get('name') or '').strip()
        if not name or not master_id:
            continue
        slug = slugify(name)
        vp = hit.get('variantProduct') or {}
        pp = vp.get('productPrice') or {}
        price_raw = pp.get('price') or pp.get('salePrice') or pp.get('bestPrice')
        price = f"${float(price_raw):.2f}" if price_raw is not None else ''
        colors = mp.get('colors') or []
        if colors:
            for col in colors:
                color_name = (col.get('name') or '').strip()
                color_val = (col.get('value') or '').strip()
                img_data = col.get('image') or {}
                image = img_data.get('href', '')
                url = f"{SITE}/pd/{slug}/{master_id}"
                key = f"{master_id}|{color_val}"
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                out.append({'title': name, 'price': price, 'color': color_name, 'url': url, 'image': image})
        else:
            url = f"{SITE}/pd/{slug}/{master_id}"
            key = f"{master_id}|"
            if key not in seen_keys:
                seen_keys.add(key)
                mp_img = mp.get('image') or {}
                out.append({'title': name, 'price': price, 'color': '', 'url': url, 'image': mp_img.get('href', '')})
    return out


def main():
    ensure_table(TABLE)
    total_ins = 0
    total_skip = 0
    seen_keys = set()
    current_responses = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            locale="en-US", viewport={"width": 1280, "height": 900},
        )
        pg = ctx.new_page()
        Stealth().apply_stealth_sync(pg)

        def handle_route(route):
            req = route.request
            if req.method == 'POST' and 'graphql' in req.url:
                try:
                    b = json.loads(req.post_data or '{}')
                    if b.get('operationName') == 'searchProducts':
                        resp = route.fetch()
                        current_responses.append(resp.text())
                        route.fulfill(response=resp)
                        return
                except Exception:
                    pass
            try:
                route.continue_()
            except Exception:
                pass

        pg.route('**/*', handle_route)

        p("Establishing session...")
        pg.goto(BASE, timeout=60000)
        pg.wait_for_timeout(5000)

        for cat in SHOE_CATEGORIES:
            p(f"\nTrying: {cat}")
            current_responses.clear()
            try:
                pg.goto(f"{SITE}{cat}", timeout=30000)
            except Exception as e:
                p(f"  Nav error: {e}")
                continue
            pg.wait_for_timeout(5000)
            final_url = pg.url
            p(f"  Final URL: {final_url}")

            # Scroll to load
            stable = 0
            prev = 0
            for _ in range(60):
                pg.evaluate("window.scrollBy(0, 1500)")
                pg.wait_for_timeout(600)
                if len(current_responses) == prev:
                    stable += 1
                    if stable >= 5:
                        break
                else:
                    stable = 0
                    prev = len(current_responses)

            p(f"  Captured {len(current_responses)} GQL responses")
            if not current_responses:
                p("  Skipping (no products)")
                continue

            cat_products = []
            for resp_body in current_responses:
                try:
                    data = json.loads(resp_body)
                    sp = data.get('data', {}).get('searchProducts', {})
                    items = sp.get('itemsSection', {}).get('items', [])
                    cat_products.extend(parse_items(items, seen_keys))
                except Exception as e:
                    p(f"  Parse err: {e}")

            if cat_products:
                ins, skip = insert_products(TABLE, cat_products)
                total_ins += ins
                total_skip += skip
                p(f"  {len(cat_products)} rows -> {ins} inserted, {skip} skipped")
            pg.wait_for_timeout(2000)

        browser.close()

    p(f"\n{'='*50}")
    p(f"DONE! {total_ins} new inserted, {total_skip} skipped")


if __name__ == "__main__":
    main()
