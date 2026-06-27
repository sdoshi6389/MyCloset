"""Revolve scraper — lazyLoadProductsRevolve HTML API + DOM extraction."""
import sys, os, json, re
sys.path.insert(0, os.path.dirname(__file__))
from db_insert import ensure_table, insert_products
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

TABLE = "products_revolve"
BASE = "https://www.revolve.com"

# (label, listing_url_path, lazyLoad_alias_url)
# The listing page is navigated to first (establishes session context),
# then lazyLoadProductsRevolve is called with the aliasURL.
CATEGORIES = [
    (
        "women-clothing",
        "/clothing/br/3699fc/",
        "clothing/br/3699fc&s=c&c=Clothing",
    ),
]

def p(*args):
    try:
        print(*args, flush=True)
    except UnicodeEncodeError:
        print(*(str(a).encode("ascii", "replace").decode() for a in args), flush=True)


def color_from_url(url):
    """Extract color from Revolve product URL slug like '.../brand-product-in-color/dp/...'"""
    try:
        slug = url.rstrip('/').split('/dp/')[0].rsplit('/', 1)[-1]
        if '-in-' in slug:
            color_part = slug.rsplit('-in-', 1)[1]
            return ' '.join(w.capitalize() for w in color_part.split('-'))
    except Exception:
        pass
    return ''


def extract_products_from_html(browser_page, html_chunk):
    """Insert HTML into a temp div and extract product data."""
    result = browser_page.evaluate(f"""
        (html) => {{
            const BASE = '{BASE}';
            const div = document.createElement('div');
            div.innerHTML = html;
            const items = [];
            div.querySelectorAll('li.plp__product').forEach(el => {{
                const code = el.id || '';
                if (!code) return;

                // URL
                const linkEl = el.querySelector('a.js-plp-pdp-link, a[href*="/dp/"]');
                const url = linkEl ? (BASE + linkEl.getAttribute('href').split('?')[0]) : '';
                if (!url) return;

                // Image (primary image)
                const imgEl = el.querySelector('img.plp-image, img.js-plp-image');
                const image = imgEl ? (imgEl.getAttribute('src') || '') : '';

                // Product name
                const nameEl = el.querySelector('.js-plp-product-name, [class*="product-name"]');
                const name = nameEl ? nameEl.innerText.trim() : '';

                // Brand
                const brandEl = el.querySelector('.js-plp-brand, [class*="brand-name"]');
                const brand = brandEl ? brandEl.innerText.trim() : '';

                // Title: brand + name
                const title = brand && name ? (brand + ' ' + name) : (name || brand);

                // Price
                const priceEl = el.querySelector('.js-plp-retail, [class*="price"]');
                let price = priceEl ? priceEl.innerText.trim().split('\\n')[0] : '';
                // Normalize: "$158.00" or "$158" → keep as-is
                if (price && !price.startsWith('$')) price = '$' + price;

                items.push({{code, title, price, url, image}});
            }});
            return items;
        }}
    """, html_chunk)
    return result or []


def extract_products_from_dom(browser_page):
    """Extract products already rendered in the page DOM."""
    return browser_page.evaluate(f"""
        () => {{
            const BASE = '{BASE}';
            const items = [];
            document.querySelectorAll('li.plp__product').forEach(el => {{
                const code = el.id || '';
                if (!code) return;

                const linkEl = el.querySelector('a.js-plp-pdp-link, a[href*="/dp/"]');
                const url = linkEl ? (BASE + linkEl.getAttribute('href').split('?')[0]) : '';
                if (!url) return;

                const imgEl = el.querySelector('img.plp-image, img.js-plp-image');
                const image = imgEl ? (imgEl.getAttribute('src') || '') : '';

                const nameEl = el.querySelector('.js-plp-product-name, [class*="product-name"]');
                const name = nameEl ? nameEl.innerText.trim() : '';

                const brandEl = el.querySelector('.js-plp-brand, [class*="brand-name"]');
                const brand = brandEl ? brandEl.innerText.trim() : '';
                const title = brand && name ? (brand + ' ' + name) : (name || brand);

                const priceEl = el.querySelector('.js-plp-retail, [class*="price"]');
                let price = priceEl ? priceEl.innerText.trim().split('\\n')[0] : '';
                if (price && !price.startsWith('$')) price = '$' + price;

                items.push({{code, title, price, url, image}});
            }});
            return items;
        }}
    """) or []


def scrape_category(pg, label, listing_path, alias_url):
    p(f"\n[{label}] Loading listing page...")
    pg.goto(f"{BASE}{listing_path}", timeout=60000)
    pg.wait_for_timeout(10000)

    # Collect from DOM (pre-rendered + lazyLoad that already fired)
    dom_items = extract_products_from_dom(pg)
    p(f"  DOM products: {len(dom_items)}")

    # Also call lazyLoadProductsRevolve explicitly to capture any missed products
    lazy_html = pg.evaluate(f"""
        async () => {{
            const aliasUrl = encodeURIComponent('https://www.revolve.com/r/Brands.jsp?aliasURL={alias_url}');
            const apiUrl = '/content/products/lazyLoadProductsRevolve?url=' + aliasUrl
                + '&sortBy=featured&productsPerRow=4&preLoadCategory=&preLoadDesigner='
                + '&lazyLang=en&lazyCountryCode=US&lazyCurrency=USD';
            try {{
                const r = await fetch(apiUrl, {{headers: {{'X-Requested-With': 'XMLHttpRequest'}}}});
                return await r.text();
            }} catch(e) {{
                return '';
            }}
        }}
    """)
    lazy_items = extract_products_from_html(pg, lazy_html) if lazy_html else []
    p(f"  lazyLoad HTML products: {len(lazy_items)}")

    # Merge by code
    seen = {}
    for item in dom_items + lazy_items:
        code = item.get('code', '')
        if code and code not in seen:
            seen[code] = item

    all_items = list(seen.values())
    p(f"  Unique products: {len(all_items)}")

    # Add color from URL slug
    rows = []
    for item in all_items:
        color = color_from_url(item.get('url', ''))
        rows.append({
            'title': item.get('title', ''),
            'price': item.get('price', ''),
            'color': color,
            'url': item.get('url', ''),
            'image': item.get('image', ''),
        })

    # Filter rows with at least title and url
    rows = [r for r in rows if r['title'] and r['url']]

    ins, skip = insert_products(TABLE, rows)
    p(f"  [{label}] {len(rows)} rows → {ins} inserted, {skip} skipped")
    return ins, skip


def discover_mens_category(pg):
    """Navigate to men's section and find the all-clothing listing URL."""
    p("\nDiscovering men's category URL...")
    pg.goto(f"{BASE}/mens/", timeout=60000)
    pg.wait_for_timeout(5000)

    links = pg.evaluate("""
        () => {
            const seen = new Set();
            document.querySelectorAll('a[href]').forEach(a => {
                const h = a.getAttribute('href') || '';
                // Men's clothing listing pages have /mens/ and /br/ pattern
                if (h.startsWith('/mens/') && h.includes('/br/') && !h.includes('navsrc')) seen.add(h.split('?')[0]);
            });
            return [...seen].slice(0, 20);
        }
    """)
    p(f"Men's /br/ links: {links}")

    # Also look for the main men's "all clothing" link
    all_clothing = pg.evaluate("""
        () => {
            const links = [];
            document.querySelectorAll('a[href]').forEach(a => {
                const h = a.getAttribute('href') || '';
                const text = (a.innerText || '').trim().toLowerCase();
                if (h.startsWith('/mens/') && h.includes('/br/') &&
                    (text.includes('all') || text.includes('clothing'))) {
                    links.push({href: h, text});
                }
            });
            return links.slice(0, 10);
        }
    """)
    p(f"Men's 'all clothing' links: {all_clothing}")
    return links, all_clothing


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

        p("Loading Revolve homepage...")
        pg.goto(BASE, timeout=60000)
        pg.wait_for_timeout(4000)

        # Scrape pre-configured women's categories
        for label, listing_path, alias_url in CATEGORIES:
            ins, skip = scrape_category(pg, label, listing_path, alias_url)
            grand_ins += ins
            grand_skip += skip

        # Discover and scrape men's section
        mens_links, mens_clothing = discover_mens_category(pg)

        # Find men's all-clothing page
        mens_clothing_url = None
        for l in mens_clothing:
            href = l.get('href', '') if isinstance(l, dict) else l
            if 'clothing' in href.lower() or 'all' in href.lower():
                mens_clothing_url = href.split('?')[0]
                break
        if not mens_clothing_url and mens_links:
            # Try the first non-accessories non-shoes link
            for href in mens_links:
                if not any(x in href for x in ['/shoes/', '/bags/', '/accessories/', '/new/']):
                    mens_clothing_url = href
                    break

        if mens_clothing_url:
            # Extract alias URL from the href pattern /mens/CATEGORY/br/HASH/
            # aliasURL = "mens/CATEGORY/br/HASH&s=c&c=CATEGORY"
            path = mens_clothing_url.strip('/')
            parts = path.split('/')
            if len(parts) >= 2:
                cat = parts[1] if len(parts) > 2 else parts[0]
                alias = path + '&s=c&c=' + cat
                p(f"\nMen's clothing URL: {mens_clothing_url}")
                ins, skip = scrape_category(pg, 'men-clothing', mens_clothing_url, alias)
                grand_ins += ins
                grand_skip += skip
        else:
            p("Could not discover men's clothing URL")

        browser.close()

    p(f"\n{'='*50}")
    p(f"DONE! Total: {grand_ins} inserted, {grand_skip} skipped")


if __name__ == "__main__":
    main()
