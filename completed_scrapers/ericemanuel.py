"""Eric Emanuel scraper — standard Shopify products.json via browser-context fetch.
Color is embedded in tags[] as "Primary Color: X" (cleaner than Club Monaco's
unlabeled tags, no hardcoded color-name list needed).
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

from db_insert import insert_products, ensure_table

TABLE = "products_ericemanuel"
BASE  = "https://www.ericemanuel.com"
LIMIT = 250


def p(*args):
    try:
        print(*args, flush=True)
    except UnicodeEncodeError:
        print(*(str(a).encode("ascii", "replace").decode() for a in args), flush=True)


def find_color(tags):
    for tag in tags:
        if tag.strip().lower().startswith("primary color:"):
            return tag.split(":", 1)[1].strip()
    return ""


def parse_products(products):
    rows = []
    for prod in products:
        title = (prod.get("title") or "").strip()
        handle = prod.get("handle") or ""
        if not title or not handle:
            continue

        tags = prod.get("tags") or []
        color = find_color(tags)

        variants = prod.get("variants") or []
        price = ""
        if variants:
            try:
                price = f"${float(variants[0].get('price', 0)):.2f}"
            except (ValueError, TypeError):
                price = ""

        images = prod.get("images") or []
        image = images[0].get("src", "") if images else ""

        url = f"{BASE}/products/{handle}"

        rows.append({
            "title": title,
            "color": color,
            "price": price,
            "image": image,
            "url":   url,
        })
    return rows


def scrape_all(page):
    inserted = skipped = 0
    pg = 1
    while True:
        result = page.evaluate(f"""
            async () => {{
                const r = await fetch('/products.json?limit={LIMIT}&page={pg}');
                return await r.json();
            }}
        """)
        products = result.get("products") or []
        if not products:
            break

        rows = parse_products(products)
        ins, skip = insert_products(TABLE, rows) if rows else (0, 0)
        inserted += ins
        skipped  += skip
        p(f"  Page {pg}: {len(products)} products -> {len(rows)} rows -> {ins} inserted, {skip} skipped")

        if len(products) < LIMIT:
            break
        pg += 1

    return inserted, skipped


def main():
    p(f"Eric Emanuel scraper -> table: {TABLE}")
    ensure_table(TABLE)

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

        p("Loading ericemanuel.com...")
        page.goto(BASE, timeout=60000)
        page.wait_for_timeout(5000)

        total_ins, total_skip = scrape_all(page)

        browser.close()

    p(f"\n{'='*60}")
    p(f"DONE! {total_ins} inserted, {total_skip} skipped")


if __name__ == "__main__":
    main()
