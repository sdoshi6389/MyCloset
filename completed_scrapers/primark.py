"""Primark scraper — intercepts server-side getPlpProducts response via ?page=N URLs."""
import sys, os, json, re
sys.path.insert(0, os.path.dirname(__file__))
from db_insert import ensure_table, insert_products
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

TABLE = "products_primark"
BASE = "https://www.primark.com"
ROWS = 24  # server always returns 24 per page

CATEGORIES = [
    "/en-us/c/women/clothing",
    "/en-us/c/women/sleepwear-and-lingerie",
    "/en-us/c/women/gymwear-and-leisure",
    "/en-us/c/women/occasionwear",
    "/en-us/c/women/accessories",
    "/en-us/c/women/shoes",
]

def p(*args):
    try:
        print(*args, flush=True)
    except UnicodeEncodeError:
        print(*(str(a).encode("ascii", "replace").decode() for a in args), flush=True)


def docs_to_products(docs):
    out = []
    for doc in docs:
        slug = doc.get('url', '')
        if not slug:
            continue
        url = f"{BASE}/en-us/p/{slug}"
        title = doc.get('title', '').strip()
        if not title:
            continue
        sale_price = doc.get('sale_price') or doc.get('price') or 0
        price = f"${sale_price / 100:.2f}"
        color_match = re.search(r'-([a-z][a-z-]*)-\d{10,13}$', slug, re.IGNORECASE)
        color = color_match.group(1).replace('-', ' ') if color_match else ''
        thumb = doc.get('thumb_image', '')
        image = f"{thumb}?w=400&fmt=auto" if thumb else ''
        out.append({'title': title, 'price': price, 'color': color, 'url': url, 'image': image})
    return out


def scrape_category(page, cat_path):
    cat_name = cat_path.split("/en-us/c/")[-1]
    p(f"\n=== {cat_name} ===")

    all_products = []
    num_found = None
    expected_start = 0
    page_num = 1

    while True:
        url = f"{BASE}{cat_path}?page={page_num}"
        docs = None
        start_returned = None
        nf = None

        try:
            with page.expect_response(
                lambda r: 'getPlpProducts' in r.url,
                timeout=15000
            ) as resp_info:
                page.goto(url, timeout=60000)
            resp = resp_info.value
            body = resp.json()
            response = body['data']['categoryNavItem']['props']['productsData']['response']
            docs = response.get('docs', [])
            nf = response.get('numFound', 0)
            start_returned = response.get('start', 0)
        except Exception as e:
            p(f"  Page {page_num}: no API response ({type(e).__name__}) — stopping")
            break

        # Validate we got the right page (CDN cached pages can return wrong start)
        if start_returned != expected_start:
            p(f"  Page {page_num}: expected start={expected_start}, got {start_returned} — CDN cache hit, stopping")
            break

        if num_found is None:
            num_found = nf
            p(f"  Total available: {num_found}")

        if not docs:
            p(f"  Page {page_num}: empty docs — stopping")
            break

        batch = docs_to_products(docs)
        if not batch:
            p(f"  Page {page_num}: no valid products — stopping")
            break

        all_products.extend(batch)
        p(f"  Page {page_num} (start={start_returned}): {len(batch)} products (total {len(all_products)})")

        if len(all_products) >= num_found:
            p(f"  Collected all {num_found} products")
            break

        expected_start += ROWS
        page_num += 1
        page.wait_for_timeout(500)

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
            locale="en-US",
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.new_page()
        Stealth().apply_stealth_sync(page)

        p("Warming up on homepage...")
        page.goto(f"{BASE}/en-us", timeout=60000)
        page.wait_for_timeout(4000)
        for sel in ["button:has-text('Accept All')", "#onetrust-accept-btn-handler"]:
            try:
                btn = page.locator(sel)
                if btn.count() and btn.first.is_visible():
                    btn.first.click()
                    page.wait_for_timeout(2000)
                    break
            except Exception:
                pass

        for cat_path in CATEGORIES:
            products = scrape_category(page, cat_path)
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
