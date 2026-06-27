"""Reformation accessories retry — longer delays to avoid 429."""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(__file__))
from db_insert import ensure_table, insert_products
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

TABLE = "products_reformation"
BASE = "https://www.thereformation.com"
SFCC = f"{BASE}/on/demandware.store/Sites-reformation-us-Site/en_US"
PAGE_SIZE = 100

def p(*args):
    try:
        print(*args, flush=True)
    except UnicodeEncodeError:
        print(*(str(a).encode("ascii", "replace").decode() for a in args), flush=True)


def fetch_page_html(browser_page, cgid, start, retries=3):
    url = f"{SFCC}/Search-ShowAjax?cgid={cgid}&start={start}&sz={PAGE_SIZE}&format=page-element"
    for attempt in range(retries):
        result = browser_page.evaluate(f"""
            async () => {{
                try {{
                    const r = await fetch({json.dumps(url)}, {{
                        headers: {{
                            'Accept': 'text/html, */*',
                            'X-Requested-With': 'XMLHttpRequest',
                        }}
                    }});
                    return {{status: r.status, html: await r.text()}};
                }} catch(e) {{
                    return {{error: e.message}};
                }}
            }}
        """)
        status = result.get('status')
        if status == 429:
            wait = 15 * (attempt + 1)
            p(f"    429 rate limit — waiting {wait}s (attempt {attempt+1}/{retries})...")
            browser_page.wait_for_timeout(wait * 1000)
            continue
        if 'error' in result:
            p(f"    Error: {result['error']}")
            return None
        if status and status != 200:
            p(f"    HTTP {status}")
            return None
        return result.get('html', '')
    return None


def parse_html_products(browser_page, html):
    return browser_page.evaluate(f"""
        (html) => {{
            const BASE = '{BASE}';
            const div = document.createElement('div');
            div.innerHTML = html;
            const items = [];
            div.querySelectorAll('[data-pid][data-aggregate]').forEach(el => {{
                const pid = el.getAttribute('data-pid') || '';
                if (!pid) return;
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
                const link = el.querySelector('a[href*="/products/"]');
                const url = link ? (BASE + link.getAttribute('href').split('?')[0]) : '';
                const img = el.querySelector('img[src*="media.thereformation.com"], img[src*="PRD-SFCC"]');
                const image = img ? (img.getAttribute('src') || '') : '';
                if (name && url) items.push({{name, price, color, url, image}});
            }});
            return items;
        }}
    """, html)


def scrape_category(pg, label, cgid, start_from=0):
    p(f"\n[{label}] Scraping cgid='{cgid}' from start={start_from}...")
    total_ins = 0
    total_skip = 0
    total_fetched = 0
    start = start_from

    while True:
        html = fetch_page_html(pg, cgid, start)
        if html is None:
            p(f"  start={start}: failed after retries, stopping")
            break
        if len(html) < 500:
            p(f"  start={start}: empty response, stopping")
            break

        products = parse_html_products(pg, html)
        if not products:
            p(f"  start={start}: 0 products parsed, stopping")
            break

        rows = [{'title': pr['name'], 'price': pr['price'], 'color': pr['color'],
                 'url': pr['url'], 'image': pr['image']} for pr in products]

        total_fetched += len(products)
        ins, skip = insert_products(TABLE, rows)
        total_ins += ins
        total_skip += skip
        p(f"  start={start}: {len(products)} parsed -> {ins} inserted, {skip} skipped")

        if len(products) < PAGE_SIZE:
            p(f"  Last page (got {len(products)} < {PAGE_SIZE})")
            break

        start += PAGE_SIZE
        pg.wait_for_timeout(2000)  # 2s between pages to stay under rate limit

    p(f"  [{label}] Done: {total_fetched} fetched, {total_ins} inserted, {total_skip} skipped")
    return total_ins, total_skip


def main():
    ensure_table(TABLE)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            locale="en-US", viewport={"width": 1280, "height": 900},
        )
        pg = ctx.new_page()
        Stealth().apply_stealth_sync(pg)

        p("Loading Reformation homepage...")
        pg.goto(BASE, timeout=60000)
        pg.wait_for_timeout(5000)

        # Resume accessories from start=100 (first page already inserted)
        ins, skip = scrape_category(pg, "accessories", "accessories", start_from=100)

        browser.close()

    p(f"\n{'='*50}")
    p(f"Accessories retry: {ins} inserted, {skip} skipped")


if __name__ == "__main__":
    main()
