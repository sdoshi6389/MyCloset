"""Reformation scraper — SFCC Search-ShowAjax HTML, parses data-aggregate JSON."""
import sys, os, json, re
sys.path.insert(0, os.path.dirname(__file__))
from db_insert import ensure_table, insert_products
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

TABLE = "products_reformation"
BASE = "https://www.thereformation.com"
SFCC = f"{BASE}/on/demandware.store/Sites-reformation-us-Site/en_US"
PAGE_SIZE = 100

# (label, cgid) — start with clothing (covers all apparel), then shoes/accessories
CATEGORIES = [
    ("clothing", "clothing"),
    ("shoes", "shoes"),
    ("accessories", "accessories"),
]

def p(*args):
    try:
        print(*args, flush=True)
    except UnicodeEncodeError:
        print(*(str(a).encode("ascii", "replace").decode() for a in args), flush=True)


def fetch_page_html(browser_page, cgid, start):
    url = f"{SFCC}/Search-ShowAjax?cgid={cgid}&start={start}&sz={PAGE_SIZE}&format=page-element"
    return browser_page.evaluate(f"""
        async () => {{
            try {{
                const r = await fetch({json.dumps(url)}, {{
                    headers: {{
                        'Accept': 'text/html, */*',
                        'X-Requested-With': 'XMLHttpRequest',
                    }}
                }});
                if (!r.ok) return {{error: 'HTTP ' + r.status}};
                return {{html: await r.text()}};
            }} catch(e) {{
                return {{error: e.message}};
            }}
        }}
    """)


def parse_html_products(browser_page, html):
    """Insert HTML into temp div and extract product data from data-aggregate JSON."""
    return browser_page.evaluate(f"""
        (html) => {{
            const BASE = '{BASE}';
            const div = document.createElement('div');
            div.innerHTML = html;

            const items = [];
            div.querySelectorAll('[data-pid][data-aggregate]').forEach(el => {{
                const pid = el.getAttribute('data-pid') || '';
                if (!pid) return;

                // Parse data-aggregate JSON for name, price, color
                let name = '', price = '', color = '';
                try {{
                    const agg = JSON.parse(el.getAttribute('data-aggregate'));
                    const prods = agg?.trackObject?.ecommerce?.click?.products || [];
                    if (prods.length > 0) {{
                        name = prods[0].name || '';
                        const rawPrice = prods[0].price;
                        price = rawPrice ? '$' + rawPrice.toFixed(2) : '';
                        color = prods[0].dimension1 || '';
                    }}
                }} catch(e) {{}}

                // URL from anchor
                const link = el.querySelector('a[href*="/products/"]');
                const url = link ? (BASE + link.getAttribute('href').split('?')[0]) : '';

                // Image — primary product image
                const img = el.querySelector('img[src*="media.thereformation.com"], img[src*="PRD-SFCC"]');
                const image = img ? (img.getAttribute('src') || '') : '';

                if (name && url) {{
                    items.push({{name, price, color, url, image}});
                }}
            }});
            return items;
        }}
    """, html)


def scrape_category(pg, label, cgid):
    p(f"\n[{label}] Scraping cgid='{cgid}'...")
    total_ins = 0
    total_skip = 0
    total_fetched = 0
    start = 0

    while True:
        result = fetch_page_html(pg, cgid, start)
        if not isinstance(result, dict) or 'error' in result:
            p(f"  start={start} error: {result}")
            break
        html = result.get('html', '')
        if not html or len(html) < 500:
            p(f"  start={start}: empty response, stopping")
            break

        products = parse_html_products(pg, html)
        if not products:
            p(f"  start={start}: 0 products parsed, stopping")
            break

        rows = [{'title': p_['name'], 'price': p_['price'], 'color': p_['color'],
                 'url': p_['url'], 'image': p_['image']} for p_ in products]

        total_fetched += len(products)
        ins, skip = insert_products(TABLE, rows)
        total_ins += ins
        total_skip += skip
        p(f"  start={start}: {len(products)} parsed -> {ins} inserted, {skip} skipped")

        if len(products) < PAGE_SIZE:
            p(f"  Last page (got {len(products)} < {PAGE_SIZE})")
            break

        start += PAGE_SIZE
        pg.wait_for_timeout(400)

    p(f"  [{label}] Done: {total_fetched} fetched, {total_ins} inserted, {total_skip} skipped")
    return total_ins, total_skip


def main():
    ensure_table(TABLE)
    grand_ins = 0
    grand_skip = 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            locale="en-US", viewport={"width": 1280, "height": 900},
        )
        pg = ctx.new_page()
        Stealth().apply_stealth_sync(pg)

        p("Loading Reformation homepage to establish session...")
        pg.goto(BASE, timeout=60000)
        pg.wait_for_timeout(5000)

        for label, cgid in CATEGORIES:
            ins, skip = scrape_category(pg, label, cgid)
            grand_ins += ins
            grand_skip += skip

        browser.close()

    p(f"\n{'='*50}")
    p(f"DONE! Total: {grand_ins} inserted, {grand_skip} skipped")


if __name__ == "__main__":
    main()
