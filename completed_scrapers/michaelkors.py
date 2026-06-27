"""Michael Kors scraper — SFCC Search-UpdateGrid HTML endpoint via browser fetch.
Returns up to 24 product tiles per call. Parses tile HTML directly (no JSON blob,
unlike Calvin Klein/Tommy Hilfiger): title/url from h2.pdp-link a, price from
.sales/.original .value, color resolved by matching the tile's dwvar color id
against its swatch links.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

from db_insert import insert_products, ensure_table

TABLE  = "products_michaelkors"
BASE   = "https://www.michaelkors.com"
SITE   = "Sites-mk_us-Site"
LOCALE = "en_US"
SZ     = 24

CATEGORIES = [
    # (cgid,                label)
    ("womens-handbags",     "women/handbags"),
    ("womens-clothing",     "women/clothing"),
    ("womens-shoes",        "women/shoes"),
    ("womens-accessories",  "women/accessories"),
    ("womens-jewelry",      "women/jewelry"),
    ("womens-watches",      "women/watches"),
    ("womens-wallets",      "women/wallets"),
    ("mens-clothing",       "men/clothing"),
    ("mens-shoes",          "men/shoes"),
    ("mens-accessories",    "men/accessories"),
    ("mens-bags",           "men/bags"),
    ("mens-watches",        "men/watches"),
    ("mens-wallets",        "men/wallets"),
]


def p(*args):
    try:
        print(*args, flush=True)
    except UnicodeEncodeError:
        print(*(str(a).encode("ascii", "replace").decode() for a in args), flush=True)


FETCH_GRID_JS = """
    async ({cgid, start, sz}) => {
        const url = `https://www.michaelkors.com/on/demandware.store/Sites-mk_us-Site/en_US/Search-UpdateGrid?cgid=${cgid}&start=${start}&sz=${sz}`;
        const r = await fetch(url);
        const html = await r.text();
        const parser = new DOMParser();
        const doc = parser.parseFromString(html, 'text/html');
        const tiles = doc.querySelectorAll('[data-pid]');
        const prods = [];
        for (const tile of tiles) {
            const pid = tile.dataset.pid || '';
            const linkEl = tile.querySelector('h2.pdp-link a');
            const title = linkEl ? linkEl.textContent.trim() : '';
            const rawHref = linkEl ? linkEl.getAttribute('href') : '';
            const url = rawHref ? 'https://www.michaelkors.com' + rawHref.split('?')[0] : '';

            const colorMatch = rawHref ? rawHref.match(/color=([^&]+)/) : null;
            const colorId = colorMatch ? colorMatch[1] : '';
            let color = '';
            if (colorId) {
                const swatchImg = tile.querySelector(`a[href*="color=${colorId}"] img`);
                if (swatchImg) color = swatchImg.getAttribute('alt') || '';
            }

            const imgEl = tile.querySelector('img.tile-image');
            const img = imgEl ? (imgEl.getAttribute('data-src') || imgEl.getAttribute('src') || '') : '';

            const salesEl = tile.querySelector('.sales .value');
            const origEl  = tile.querySelector('.original .value, .strike-through .value');
            const salePrice = salesEl ? salesEl.textContent.replace(/\\s+/g, ' ').trim() : '';
            const listPrice = origEl  ? origEl.textContent.replace(/\\s+/g, ' ').trim()  : '';
            const price = salePrice || listPrice;

            if (pid && title) {
                prods.push({ pid, title, color, price, img, url });
            }
        }
        return { tileCount: tiles.length, prods };
    }
"""


def scrape_category(page, cgid, label):
    p(f"\n  [{label}] cgid={cgid}")
    inserted = skipped = 0
    start = 0

    while True:
        result = page.evaluate(FETCH_GRID_JS, {"cgid": cgid, "start": start, "sz": SZ})
        tile_count = result.get("tileCount", 0)
        prods = result.get("prods", [])

        if tile_count == 0:
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

        p(f"    start={start}: {tile_count} tiles -> {len(rows)} rows -> {ins} ins, {skip} skip")

        start += SZ
        if tile_count < SZ:
            break   # last partial page

    p(f"  [{label}] done: {inserted} inserted, {skipped} skipped")
    return inserted, skipped


def main():
    p(f"Michael Kors scraper -> table: {TABLE}")
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

        p("Loading michaelkors.com...")
        page.goto(BASE, timeout=60000)
        page.wait_for_timeout(6000)

        for cgid, label in CATEGORIES:
            ins, skip = scrape_category(page, cgid, label)
            total_ins  += ins
            total_skip += skip

        browser.close()

    p(f"\n{'='*60}")
    p(f"DONE! {total_ins} inserted, {total_skip} skipped")


if __name__ == "__main__":
    main()
