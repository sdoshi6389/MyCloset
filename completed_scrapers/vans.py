"""Vans scraper — Nuxt-rendered category PLP HTML via browser fetch.
Each category page (/en-us/c/<slug>?page=N) server-renders up to 12
product-card tiles per page; fetch raw HTML and parse directly (no JSON API).
Color isn't shown as text on the tile, only as a count ("9 colors"), so it's
recovered from the hero image's alt text: "{title} VANS {color} HERO".
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

from db_insert import insert_products, ensure_table

TABLE = "products_vans"
BASE  = "https://www.vans.com"

CATEGORIES = [
    # (path,                          label)
    ("/en-us/c/shoes-00081",          "shoes"),
    ("/en-us/c/clothing-00082",       "clothing"),
    ("/en-us/c/accessories-00083",    "accessories"),
    ("/en-us/c/mens-0001",            "mens"),
    ("/en-us/c/womens-0002",          "womens"),
    ("/en-us/c/kids-0003",            "kids"),
]


def p(*args):
    try:
        print(*args, flush=True)
    except UnicodeEncodeError:
        print(*(str(a).encode("ascii", "replace").decode() for a in args), flush=True)


FETCH_PAGE_JS = """
    async ({path, pg}) => {
        const sep = path.includes('?') ? '&' : '?';
        const url = `https://www.vans.com${path}${sep}page=${pg}`;
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
            const url2 = href ? 'https://www.vans.com' + href : '';

            const priceEl = card.querySelector('[data-test-id="product-card-pricing"]');
            const price = priceEl ? priceEl.textContent.replace(/\\s+/g, ' ').trim() : '';

            const imgEl = card.querySelector('picture[data-test-id="product-card-pic"] img');
            const img = imgEl ? (imgEl.getAttribute('src') || '') : '';
            const alt = imgEl ? (imgEl.getAttribute('alt') || '') : '';

            let color = '';
            if (alt) {
                let rest = alt;
                if (title && rest.startsWith(title)) rest = rest.slice(title.length).trim();
                rest = rest.replace(/^VANS\\s*/i, '').replace(/\\s*(HERO|ALT\\d*)$/i, '').trim();
                color = rest;
            }

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
        result = page.evaluate(FETCH_PAGE_JS, {"path": path, "pg": pg})
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

    p(f"  [{label}] done: {inserted} inserted, {skipped} skipped")
    return inserted, skipped


def main():
    p(f"Vans scraper -> table: {TABLE}")
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

        p("Loading vans.com...")
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
