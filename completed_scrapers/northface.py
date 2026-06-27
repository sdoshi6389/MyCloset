"""The North Face scraper — Nuxt-rendered category PLP HTML via browser fetch.
Same VF Corp storefront platform as Vans (Bloomreach Discovery, server-rendered
product-card tiles, ?page=N pagination, 12 per page). Cleaner than Vans here:
color is a real swatch name (not parsed from alt text) via the active
[data-test-id="vf-color-picker"][aria-current="true"] swatch's .sr-only text.
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(__file__))

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

from db_insert import insert_products, ensure_table

TABLE = "products_northface"
BASE  = "https://www.thenorthface.com"

CATEGORIES = [
    # (path,                                                  label)
    ("/en-us/c/mens/mens-jackets-and-vests-211702",           "mens-jackets-vests"),
    ("/en-us/c/mens/mens-tops-211703",                        "mens-tops"),
    ("/en-us/c/mens/mens-bottoms-211704",                     "mens-bottoms"),
    ("/en-us/c/mens/mens-footwear-211706",                    "mens-footwear"),
    ("/en-us/c/mens/mens-accessories-211707",                 "mens-accessories"),
    ("/en-us/c/womens/womens-jackets-and-vests-211719",       "womens-jackets-vests"),
    ("/en-us/c/womens/womens-tops-211720",                    "womens-tops"),
    ("/en-us/c/womens/womens-bottoms-211721",                 "womens-bottoms"),
    ("/en-us/c/womens/womens-footwear-211723",                "womens-footwear"),
    ("/en-us/c/womens/womens-accessories-211724",             "womens-accessories"),
    ("/en-us/c/kids/girls-apparel-211741",                    "girls-apparel"),
    ("/en-us/c/kids/girls-accessories-211746",                "girls-accessories"),
    ("/en-us/c/kids/girls-footwear-211745",                   "girls-footwear"),
    ("/en-us/c/kids/boys-apparel-211735",                     "boys-apparel"),
    ("/en-us/c/kids/boys-accessories-211740",                 "boys-accessories"),
    ("/en-us/c/kids/boys-footwear-211739",                    "boys-footwear"),
    ("/en-us/c/bags-and-gear/backpacks-224451",               "backpacks"),
    ("/en-us/c/bags-and-gear/bags-829872",                    "bags"),
    ("/en-us/c/bags-and-gear/technical-packs-224452",         "technical-packs"),
    ("/en-us/c/bags-and-gear/luggage-and-duffels-224453",     "luggage-duffels"),
]


def p(*args):
    try:
        print(*args, flush=True)
    except UnicodeEncodeError:
        print(*(str(a).encode("ascii", "replace").decode() for a in args), flush=True)


FETCH_PAGE_JS = """
    async ({path, pg}) => {
        const sep = path.includes('?') ? '&' : '?';
        const url = `https://www.thenorthface.com${path}${sep}page=${pg}`;
        const r = await fetch(url);
        const html = await r.text();
        const parser = new DOMParser();
        const doc = parser.parseFromString(html, 'text/html');
        const cards = doc.querySelectorAll('[data-test-id="product-card"]');
        const prods = [];
        for (const card of cards) {
            const titleEl = card.querySelector('[data-test-id="product-card-title"]');
            if (!titleEl) continue;
            const title = titleEl.textContent.trim();
            const pid = titleEl.id || '';
            const href = titleEl.getAttribute('href') || '';
            const url2 = href ? 'https://www.thenorthface.com' + href.split('?')[0] : '';

            const priceEl = card.querySelector('[data-test-id="product-card-pricing"]');
            const price = priceEl ? priceEl.textContent.replace(/\\s+/g, ' ').trim() : '';

            const activeSwatch = card.querySelector('[data-test-id="vf-color-picker"][aria-current="true"] .sr-only');
            const color = activeSwatch ? activeSwatch.textContent.trim() : '';

            const imgEl = card.querySelector('picture[data-test-id="product-card-pic"] img');
            const img = imgEl ? (imgEl.getAttribute('src') || '') : '';

            if (pid && title) {
                prods.push({ pid, title, color, price, img, url: url2 });
            }
        }
        return { cardCount: cards.length, prods };
    }
"""


def scrape_category(page, path, label):
    p(f"\n  [{label}] path={path}")
    inserted = skipped = 0
    pg = 1

    while True:
        result = None
        for attempt in range(5):
            try:
                result = page.evaluate(FETCH_PAGE_JS, {"path": path, "pg": pg})
                break
            except Exception as e:
                wait_s = 5 * (attempt + 1)
                p(f"    page={pg}: fetch error ({e.__class__.__name__}), retrying in {wait_s}s...")
                page.wait_for_timeout(wait_s * 1000)
        if result is None:
            p(f"    page={pg}: giving up after retries, stopping category")
            break

        card_count = result.get("cardCount", 0)
        prods = result.get("prods", [])

        if card_count == 0:
            break

        rows = []
        for prod in prods:
            rows.append({
                "title": prod["title"],
                "color": prod["color"],
                "price": prod["price"],
                "image": prod["img"],
                "url":   prod["url"],
            })

        ins = skip = 0
        if rows:
            ins, skip = insert_products(TABLE, rows)
            inserted += ins
            skipped  += skip

        p(f"    page={pg}: {card_count} cards -> {len(rows)} rows -> {ins} ins, {skip} skip")
        pg += 1
        page.wait_for_timeout(1200)

    p(f"  [{label}] done: {inserted} inserted, {skipped} skipped")
    return inserted, skipped


def main():
    p(f"The North Face scraper -> table: {TABLE}")
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

        p("Loading thenorthface.com...")
        page.goto(BASE + "/en-us", timeout=60000)
        page.wait_for_timeout(6000)

        for path, label in CATEGORIES:
            ins, skip = scrape_category(page, path, label)
            total_ins  += ins
            total_skip += skip

        browser.close()

    p(f"\n{'='*60}")
    p(f"DONE! {total_ins} inserted, {total_skip} skipped")


if __name__ == "__main__":
    main()
