"""Supreme scraper — extracts from collections/all DOM (single page, current season)."""
import sys, os, json
sys.path.insert(0, os.path.dirname(__file__))
from db_insert import ensure_table, insert_products
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

TABLE = "products_supreme"
BASE = "https://us.supreme.com"

def p(*args):
    try:
        print(*args, flush=True)
    except UnicodeEncodeError:
        print(*(str(a).encode("ascii", "replace").decode() for a in args), flush=True)


def extract_products(page):
    return page.evaluate(f"""
        () => {{
            const BASE = '{BASE}';
            const seen = new Set();
            const items = [];

            document.querySelectorAll('a[href*="/products/"]').forEach(a => {{
                const href = a.getAttribute('href').split('?')[0];
                if (seen.has(href)) return;
                seen.add(href);

                const url = href.startsWith('http') ? href : BASE + href;

                // Title + color from img alt: "Title - Color"
                const img = a.querySelector('img');
                const alt = img ? (img.getAttribute('alt') || '') : '';
                let title = '', color = '';
                if (alt.includes(' - ')) {{
                    const dashIdx = alt.lastIndexOf(' - ');
                    title = alt.substring(0, dashIdx).trim();
                    color = alt.substring(dashIdx + 3).trim();
                }} else {{
                    // fallback: aria-label="... product link"
                    const aria = a.getAttribute('aria-label') || '';
                    title = aria.replace(/ product link$/i, '').trim() || alt.trim();
                }}

                // Price from aria-label="product price" span
                const priceEl = a.querySelector('[aria-label="product price"]');
                const price = priceEl ? priceEl.textContent.trim() : '';

                const image = img ? (img.src || '') : '';

                if (!title || !url) return;
                items.push({{ title, price, color, url, image }});
            }});
            return items;
        }}
    """)


def main():
    ensure_table(TABLE)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            locale="en-US", viewport={"width": 1280, "height": 900},
        )
        page = ctx.new_page()
        Stealth().apply_stealth_sync(page)

        p("Loading collections/all...")
        page.goto(f"{BASE}/collections/all", timeout=60000)
        page.wait_for_timeout(8000)

        # Scroll to ensure all lazy-loaded products are rendered
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(3000)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(2000)

        products = extract_products(page)
        p(f"Extracted {len(products)} products from DOM")

        if products:
            p(f"Sample: {products[0]}")
            ins, skip = insert_products(TABLE, products)
            p(f"\n{'='*50}")
            p(f"DONE! {ins} inserted, {skip} skipped (duplicates)")
        else:
            p("No products found!")

        browser.close()


if __name__ == "__main__":
    main()
