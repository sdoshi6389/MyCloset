"""Gymshark women's scraper — Shopify site (products.json is 404, so DOM scraping).
Collection URLs discovered from /pages/shop-women filtered to /womens paths.
Each collection page is fully scrolled to load all tiles.
PDP is visited once per product; all color swatches extracted from aria-label → one row per color.
"""
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
import time
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from db_insert import ensure_table, insert_products

TABLE = "products_gymshark_womens"
BASE  = "https://www.gymshark.com"
HUB   = f"{BASE}/pages/shop-women"

TEST = "--test" in sys.argv  # python gymshark_women.py --test  (1 collection, 3 PDPs)


def p(*args):
    try:
        print(*args, flush=True)
    except UnicodeEncodeError:
        print(*(str(a).encode("ascii", "replace").decode() for a in args), flush=True)


def make_page(context):
    page = context.new_page()
    Stealth().apply_stealth_sync(page)
    return page


def scroll_to_bottom(page):
    previous_height = 0
    for _ in range(40):
        page.mouse.wheel(0, 4000)
        time.sleep(1.2)
        current_height = page.evaluate("document.body.scrollHeight")
        if current_height == previous_height:
            break
        previous_height = current_height


def get_collection_links(page):
    p(f"Finding women's collections from {HUB}...")
    page.goto(HUB, timeout=60000)
    page.wait_for_timeout(4000)
    scroll_to_bottom(page)
    links = page.evaluate("""() => {
        return Array.from(document.querySelectorAll('a[href*="/collections/"]'))
            .map(a => a.href.split('?')[0])
            .filter(h => h.includes('/womens') || h.includes('womens-'));
    }""")
    links = list(set(links))
    p(f"Found {len(links)} women's collections")
    return links


def get_product_urls(page, collection_url):
    page.goto(collection_url, timeout=60000)
    page.wait_for_timeout(3000)
    scroll_to_bottom(page)
    urls = page.evaluate("""() => {
        return Array.from(document.querySelectorAll('a[href*="/products/"]'))
            .map(a => a.href.split('?')[0])
            .filter(h => h.includes('gymshark.com/products/'));
    }""")
    return list(set(urls))


def scrape_pdp(page, url):
    try:
        page.goto(url, timeout=60000)
        page.wait_for_timeout(2500)
        return page.evaluate("""(pageUrl) => {
            const titleEl = document.querySelector('h1');
            const title = titleEl ? titleEl.innerText.trim() : '';

            const priceEl = document.querySelector('[data-testid="product-price"]') ||
                            document.querySelector('[class*="product-price"]');
            const priceRaw = priceEl ? priceEl.innerText.trim() : '';
            const m = priceRaw.match(/\\$[\\d.]+/);
            const price = m ? m[0] : priceRaw.replace('Regular Price:', '').trim();

            // Collect all gallery images from Shopify analytics meta, fall back to DOM
            let images = [];
            try {
                const meta = window.ShopifyAnalytics?.meta?.product?.images;
                if (Array.isArray(meta) && meta.length) {
                    images = meta.map(u => u.startsWith('//') ? 'https:' + u : u);
                }
            } catch(e) {}
            if (!images.length) {
                const seen = new Set();
                document.querySelectorAll('img[src*="cdn.shopify.com"]').forEach(img => {
                    const src = img.src.split('?')[0];
                    if (src && !seen.has(src)) { seen.add(src); images.push(src); }
                });
            }
            const image = images[0] || '';

            const swatches = Array.from(document.querySelectorAll('a[aria-label][href*="/products/"]'));
            const rows = swatches.map(s => {
                const label = s.getAttribute('aria-label') || '';
                const color = label.includes(' in ') ? label.split(' in ').pop() : '';
                return {title, price, color, url: s.href.split('?')[0], image, images, gender: 'women'};
            }).filter(r => r.url && r.title);

            return rows.length ? rows : [{title, price, color: '', url: pageUrl, image, images, gender: 'women'}];
        }""", url)
    except Exception as e:
        p(f"  PDP error {url}: {e}")
        return []


def main():
    ensure_table(TABLE)
    p(f"Gymshark women's scraper -> {TABLE}" + (" [TEST MODE]" if TEST else ""))

    total_ins = total_skip = 0
    visited_urls = set()

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

        nav_page = make_page(ctx)
        collection_links = get_collection_links(nav_page)

        tested = 0
        for ci, collection_url in enumerate(collection_links, 1):
            p(f"\n[{ci}/{len(collection_links)}] Collection: {collection_url}")
            product_urls = get_product_urls(nav_page, collection_url)
            p(f"  {len(product_urls)} unique products found")
            if not product_urls:
                p("  (empty/editorial — skipping)")
                continue

            pdp_limit = 3 if TEST else len(product_urls)
            pdp_page = make_page(ctx)
            for i, pdp_url in enumerate(product_urls[:pdp_limit]):
                if pdp_url in visited_urls:
                    continue
                visited_urls.add(pdp_url)
                rows = scrape_pdp(pdp_page, pdp_url)
                if rows:
                    ins, skip = insert_products(TABLE, rows)
                    total_ins  += ins
                    total_skip += skip
                    p(f"  [{i+1}/{min(pdp_limit, len(product_urls))}] {rows[0]['title']} "
                      f"| {len(rows)} color(s) | {ins} ins, {skip} skip")
            pdp_page.close()

            if TEST:
                tested += 1
                if tested >= 1:
                    break

        nav_page.close()
        browser.close()

    p(f"\n{'='*60}")
    p(f"DONE! {total_ins} inserted, {total_skip} skipped")


if __name__ == "__main__":
    main()
