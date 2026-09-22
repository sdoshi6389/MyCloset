"""Madewell scraper — SSR Next.js/SFCC hybrid.
Category pages are server-rendered; each tile embeds style-id, title, price, and
colorCode (in gtm-prod-id) directly as HTML attributes. Color names are resolved via
a single SFCC /browse/products?ids=<id> call per unique style id, cached across pages.
Pagination uses ?offset=N (48 tiles/page).
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

from db_insert import insert_products, ensure_table

TABLE    = "products_madewell"
BASE     = "https://www.madewell.com"
PAGE_SIZE = 48
COLOR_BATCH = 5

CATEGORIES = [
    "/womens/clothing/jeans/",
    "/womens/clothing/tops-shirts/",
    "/womens/clothing/tees/",
    "/womens/clothing/sweaters/",
    "/womens/clothing/dresses/",
    "/womens/clothing/skirts/",
    "/womens/clothing/pants/",
    "/womens/clothing/matching-sets/",
    "/womens/clothing/jackets-coats/",
    "/womens/clothing/swim/",
    "/womens/pants-shorts/shorts/",
    "/womens/accessories/bags/",
    "/womens/accessories/jewelry/",
    "/womens/jewelry-charms/",
    "/womens/accessories/belts/",
    "/womens/accessories/hats/",
    "/womens/accessories/socks/",
    "/womens/accessories/sunglasses/",
    "/womens/accessories/pouches-wallets/",
    "/womens/shoes/",
    "/mens/clothing/jeans/",
    "/mens/clothing/shirts/",
    "/mens/clothing/tees/",
    "/mens/clothing/sweaters/",
    "/mens/clothing/pants-shorts/",
    "/mens/clothing/shorts/",
    "/mens/clothing/jackets/",
    "/mens/clothing/hoodies-sweatshirts/",
    "/mens/clothing/polo/",
    "/mens/accessories/belts/",
    "/mens/accessories/socks/",
    "/mens/accessories/sunglasses/",
    "/mens/shoes/",
]

color_cache = {}


def p(*args):
    try:
        print(*args, flush=True)
    except UnicodeEncodeError:
        print(*(str(a).encode("ascii", "replace").decode() for a in args), flush=True)


def parse_page(page, url):
    """Fetch a category page (raw HTML) and extract tile data via DOMParser."""
    return page.evaluate("""
        async (url) => {
            try {
                const r = await fetch(url);
                if (!r.ok) return [];
                const html = await r.text();
                const doc = new DOMParser().parseFromString(html, 'text/html');
                const tiles = doc.querySelectorAll('[data-cnstrc-item-id]');
                return Array.from(tiles).map(tile => {
                    const gtm   = tile.getAttribute('gtm-prod-id') || '';
                    const parts = gtm.split('_');
                    const styleId   = parts[0];
                    const colorCode = parts.slice(1).join('_');

                    const mainImg = tile.querySelector('picture img');
                    const image   = mainImg ? (mainImg.getAttribute('src') || '') : '';

                    const link = tile.querySelector('a[href*="/p/"]');
                    const href = link ? link.getAttribute('href') : '';
                    const purl = href ? href.split('?')[0] : '';

                    return {
                        id:        styleId,
                        title:     (tile.getAttribute('data-cnstrc-item-name') || '').trim(),
                        price:     tile.getAttribute('data-cnstrc-item-price') || '',
                        colorCode: colorCode,
                        image:     image,
                        url:       purl,
                    };
                }).filter(t => t.id && t.title);
            } catch(e) { return []; }
        }
    """, url)


def resolve_colors(page, ids):
    """Fetch color names for style ids not yet in cache; batches of COLOR_BATCH in parallel."""
    new_ids = [i for i in ids if i not in color_cache]
    if not new_ids:
        return
    for i in range(0, len(new_ids), COLOR_BATCH):
        batch = new_ids[i:i + COLOR_BATCH]
        result = page.evaluate("""
            async (ids) => {
                const res = await Promise.all(ids.map(async id => {
                    try {
                        const r = await fetch(
                            '/browse/products?expand=availability,variations,prices,options&ids=' + id + '&'
                        );
                        if (!r.ok) return [id, ''];
                        const d = await r.json();
                        const prod = (d.data || [])[0];
                        if (!prod) return [id, ''];
                        const ca = (prod.variationAttributes || []).find(a => a.id === 'color');
                        const name = ca && ca.values.length > 0 ? ca.values[0].name : '';
                        return [id, name];
                    } catch(e) { return [id, '']; }
                }));
                return Object.fromEntries(res);
            }
        """, batch)
        color_cache.update(result)


def scrape_category(page, cat_path):
    inserted = skipped = 0
    offset   = 0

    while True:
        url   = f"{BASE}{cat_path}" + (f"?offset={offset}" if offset > 0 else "")
        tiles = parse_page(page, url)
        if not tiles:
            break

        # de-dup within page (same style+colorCode shown twice in editorial groups)
        seen, unique = set(), []
        for t in tiles:
            key = t["id"] + "_" + t["colorCode"]
            if key not in seen:
                seen.add(key)
                unique.append(t)
        tiles = unique

        # resolve colors for all unique style ids on this page
        resolve_colors(page, list({t["id"] for t in tiles}))

        rows = []
        for t in tiles:
            if not t["url"]:
                continue
            try:
                price = f"${float(t['price']):.2f}" if t["price"] else ""
            except (ValueError, TypeError):
                price = ""
            full_url = (BASE + t["url"]) if t["url"].startswith("/") else t["url"]
            rows.append({
                "title": t["title"],
                "color": color_cache.get(t["id"], ""),
                "price": price,
                "image": t["image"],
                "url":   full_url,
            })

        ins, skip = insert_products(TABLE, rows) if rows else (0, 0)
        inserted += ins
        skipped  += skip

        if len(tiles) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    return inserted, skipped


def main():
    p(f"Madewell scraper -> table: {TABLE}")
    ensure_table(TABLE)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
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

        p("Loading madewell.com (initializing session)...")
        page.goto(BASE, timeout=60000)
        page.wait_for_timeout(6000)

        total_ins = total_skip = 0
        for i, cat in enumerate(CATEGORIES, 1):
            ins, skip = scrape_category(page, cat)
            total_ins  += ins
            total_skip += skip
            p(f"  [{i}/{len(CATEGORIES)}] {cat}: {ins} inserted, {skip} skipped")

        browser.close()

    p(f"\n{'='*60}")
    p(f"DONE! {total_ins} inserted, {total_skip} skipped")


if __name__ == "__main__":
    main()
