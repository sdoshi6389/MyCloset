"""Tory Burch scraper — custom REST API (api/prod-r2/v11) via browser-context fetch.
Requires an Authorization bearer token + x-api-key header, both captured from a natural
page navigation (the visitor session token expires after ~30 min, so we refresh it before
each category rather than once for the whole run).
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
import json

from db_insert import insert_products, ensure_table

TABLE      = "products_toryburch"
BASE       = "https://www.toryburch.com"
API_BASE   = "https://www.toryburch.com/api/prod-r2/v11"
IMAGE_BASE = "https://s7.toryburch.com/is/image/ToryBurch"
LIMIT      = 100

CATEGORIES = [
    "clothing-view-all",
    "handbags-view-all",
    "shoes-view-all",
    "accessories-view-all",
    "sale-view-all",
    "beauty-view-all",
    "home-view-all",
]


def p(*args):
    try:
        print(*args, flush=True)
    except UnicodeEncodeError:
        print(*(str(a).encode("ascii", "replace").decode() for a in args), flush=True)


def capture_auth(page):
    """Navigate to a real page and sniff the Authorization/x-api-key headers
    the site's own JS attaches to its product-list fetch calls."""
    captured = {}

    def on_request(req):
        if "/api/prod-r2/v11/categories/" in req.url and "/products" in req.url and not captured:
            h = dict(req.headers)
            captured["authorization"] = h.get("authorization", "")
            captured["x-api-key"] = h.get("x-api-key", "")

    page.on("request", on_request)
    page.goto(BASE + "/en-us/clothing/", timeout=60000)
    page.wait_for_timeout(6000)
    page.remove_listener("request", on_request)
    return captured


def parse_products(products):
    rows = []
    for prod in products:
        title = (prod.get("name") or "").strip()
        style_id = prod.get("styleId") or prod.get("id") or ""
        static_url = prod.get("staticURL") or ""
        if not title or not style_id or not static_url:
            continue

        for swatch in prod.get("swatches") or []:
            color = (swatch.get("colorName") or "").strip()
            color_number = swatch.get("colorNumber") or ""

            price_obj = swatch.get("price") or prod.get("price") or {}
            try:
                price = f"${float(price_obj.get('min', 0)):.2f}"
            except (ValueError, TypeError):
                price = ""

            images = swatch.get("images") or []
            img_code = images[0] if images else swatch.get("imageCode", "")
            image = f"{IMAGE_BASE}/{img_code}" if img_code else ""

            url = f"{BASE}/en-us/{static_url}/{style_id}.html?color={color_number}"

            rows.append({
                "title": title,
                "color": color,
                "price": price,
                "image": image,
                "url":   url,
            })
    return rows


def fetch_page(page, auth_headers, category, offset):
    headers_json = json.dumps(auth_headers)
    url = (
        f"{API_BASE}/categories/{category}/products"
        f"?site=ToryBurch_US&locale=en-us&pip=true&limit={LIMIT}&offset={offset}"
    )
    return page.evaluate(f"""
        async () => {{
            const r = await fetch({json.dumps(url)}, {{headers: {headers_json}}});
            return await r.json();
        }}
    """)


def scrape_category(page, category):
    p(f"\n  [{category}]")
    auth_headers = capture_auth(page)
    if not auth_headers.get("authorization"):
        p("    Could not capture auth headers, skipping category")
        return 0, 0

    offset = 0
    inserted = skipped = 0
    total = None

    while True:
        data = fetch_page(page, auth_headers, category, offset)
        if total is None:
            total = int(data.get("total") or 0)
            p(f"    total={total}")

        products = data.get("products") or []
        if not products:
            break

        rows = parse_products(products)
        ins, skip = insert_products(TABLE, rows) if rows else (0, 0)
        inserted += ins
        skipped  += skip
        p(f"    offset={offset}: {len(products)} products -> {len(rows)} rows -> {ins} ins, {skip} skip")

        offset += LIMIT
        if offset >= total or len(products) < LIMIT:
            break

    p(f"  [{category}] done: {inserted} inserted, {skipped} skipped")
    return inserted, skipped


def main():
    p(f"Tory Burch scraper -> table: {TABLE}")
    ensure_table(TABLE)

    total_ins = total_skip = 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.new_page()
        Stealth().apply_stealth_sync(page)

        p("Loading toryburch.com...")
        page.goto(BASE, timeout=60000)
        page.wait_for_timeout(5000)

        for category in CATEGORIES:
            ins, skip = scrape_category(page, category)
            total_ins  += ins
            total_skip += skip

        browser.close()

    p(f"\n{'='*60}")
    p(f"DONE! {total_ins} inserted, {total_skip} skipped")


if __name__ == "__main__":
    main()
