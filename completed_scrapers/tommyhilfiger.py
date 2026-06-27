"""Tommy Hilfiger scraper — SFCC Search-UpdateGrid HTML endpoint via browser fetch.
Same PVH platform as Calvin Klein (calvinklein.py); different site/domain/cgids.
Returns 16 product tiles per call. Parses data-product-image-attr JSON for URL/image/name/color.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
import json

from db_insert import insert_products, ensure_table

TABLE   = "products_tommyhilfiger"
BASE    = "https://usa.tommy.com"
SITE    = "Sites-PVHTHUS-Site"
LOCALE  = "en_US"
SZ      = 16   # SFCC always returns max 16 tiles per UpdateGrid call

CATEGORIES = [
    # (cgid,             label)
    ("Tier_18482839",  "women"),
    ("Tier_18482838",  "men"),
    ("Tier_18482840",  "kids"),
    ("Tier_19273351",  "underwear"),
    ("Folder_27345577","women/jeans"),
    ("Folder_27345504","men/jeans"),
]


def p(*args):
    try:
        print(*args, flush=True)
    except UnicodeEncodeError:
        print(*(str(a).encode("ascii", "replace").decode() for a in args), flush=True)


FETCH_GRID_JS = """
    async ({cgid, start}) => {
        const sz = 16;
        const url = `https://usa.tommy.com/on/demandware.store/Sites-PVHTHUS-Site/en_US/Search-UpdateGrid?cgid=${cgid}&srule=Featured&start=${start}&sz=${sz}&deviceType=desktop`;
        const r = await fetch(url);
        const html = await r.text();
        const parser = new DOMParser();
        const doc = parser.parseFromString(html, 'text/html');
        const tiles = doc.querySelectorAll('[data-pid]');
        const prods = [];
        for (const tile of tiles) {
            const pid = tile.dataset.pid || '';
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
            const rawUrl = (product.url || '');
            const prodUrl = rawUrl ? 'https://usa.tommy.com' + rawUrl.replace(/\\?.*/, '') : '';
            const img = firstImg.url || '';
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

        rows = [{
            "title": prod["name"],
            "color": prod["color"],
            "price": prod["price"],
            "image": prod["img"],
            "url":   prod["url"],
        } for prod in prods]

        ins = skip = 0
        if rows:
            ins, skip = insert_products(TABLE, rows)
            inserted += ins
            skipped  += skip

        p(f"    start={start}: {tile_count} tiles -> {len(rows)} rows -> {ins} ins, {skip} skip")

        start += SZ
        if tile_count < SZ:
            break

    p(f"  [{label}] done: {inserted} inserted, {skipped} skipped")
    return inserted, skipped


def main():
    p(f"Tommy Hilfiger scraper -> table: {TABLE}")
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

        p("Loading usa.tommy.com...")
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
