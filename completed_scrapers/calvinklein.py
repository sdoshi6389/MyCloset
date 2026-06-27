"""Calvin Klein scraper — SFCC Search-UpdateGrid HTML endpoint via browser fetch.
Returns 16 product tiles per call. Parses data-product-image-attr JSON for URL/image/name/color.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
import json, re

from db_insert import insert_products, ensure_table

TABLE   = "products_calvinklein"
BASE    = "https://www.calvinklein.us"
SITE    = "Sites-PVHCKUS-Site"
LOCALE  = "en_US"
SZ      = 16   # SFCC always returns max 16 tiles per UpdateGrid call

CATEGORIES = [
    # (cgid,            label)
    ("Tier_0000021",  "women/apparel"),        # 931 items
    ("Tier_0000024",  "men/apparel"),
    ("Tier_0000033",  "underwear"),
    ("Folder_0000088","underwear/women/bras"),
    ("Folder_0000039","women/denim"),
    ("Folder_0000035","women/dresses"),
    ("Folder_0000037","women/tops"),
    ("Folder_0000038","women/bottoms"),
]


def p(*args):
    try:
        print(*args, flush=True)
    except UnicodeEncodeError:
        print(*(str(a).encode("ascii", "replace").decode() for a in args), flush=True)


FETCH_GRID_JS = """
    async ({cgid, start}) => {
        const sz = 16;
        const url = `https://www.calvinklein.us/on/demandware.store/Sites-PVHCKUS-Site/en_US/Search-UpdateGrid?cgid=${cgid}&srule=featured&start=${start}&sz=${sz}&deviceType=desktop`;
        const r = await fetch(url);
        const html = await r.text();
        const parser = new DOMParser();
        const doc = parser.parseFromString(html, 'text/html');
        const tiles = doc.querySelectorAll('[data-pid]');
        const prods = [];
        for (const tile of tiles) {
            const pid = tile.dataset.pid || '';
            // Parse product image attr JSON
            const imgAttrEl = tile.querySelector('[data-product-image-attr]');
            let product = {};
            if (imgAttrEl) {
                try { product = JSON.parse(imgAttrEl.dataset.productImageAttr).product || {}; } catch(e) {}
            }
            const imgs = product.images || [];
            const firstImg = imgs[0] || {};
            const alt = firstImg.alt || '';
            // Alt format: "Product Name, Color Name"
            const commaIdx = alt.lastIndexOf(', ');
            const name  = commaIdx >= 0 ? alt.substring(0, commaIdx).trim() : alt.trim();
            const color = commaIdx >= 0 ? alt.substring(commaIdx + 2).trim() : '';
            // URL: strip journey param
            const rawUrl = (product.url || '');
            const prodUrl = rawUrl ? 'https://www.calvinklein.us' + rawUrl.replace(/\\?.*/, '') : '';
            // Image
            const img = firstImg.url || '';
            // Price: prefer .sales .value (current/sale price)
            const salesEl = tile.querySelector('.sales .value');
            const origEl  = tile.querySelector('.original .value, .strike-through .value');
            const salePrice = salesEl ? salesEl.textContent.trim() : '';
            const listPrice = origEl  ? origEl.textContent.trim()  : salePrice;
            const price = salePrice || listPrice;
            if (pid && name) {
                prods.push({ pid, name, color, price, img, url: prodUrl });
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
        result = page.evaluate(FETCH_GRID_JS, {"cgid": cgid, "start": start})
        tile_count = result.get("tileCount", 0)
        prods = result.get("prods", [])

        if tile_count == 0:
            break

        rows = []
        for prod in prods:
            rows.append({
                "title": prod["name"],
                "color": prod["color"],
                "price": prod["price"],
                "image": prod["img"],
                "url":   prod["url"],
            })

        if rows:
            ins, skip = insert_products(TABLE, rows)
            inserted += ins
            skipped  += skip

        p(f"    start={start}: {tile_count} tiles → {len(rows)} rows → "
          f"{ins if rows else 0} ins, {skip if rows else 0} skip")

        start += SZ
        if tile_count < SZ:
            break   # last partial page

    p(f"  [{label}] done: {inserted} inserted, {skipped} skipped")
    return inserted, skipped


def main():
    p(f"Calvin Klein scraper → table: {TABLE}")
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

        p("Loading calvinklein.us...")
        page.goto(BASE + "/en", timeout=60000)
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
