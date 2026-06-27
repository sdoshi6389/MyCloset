"""Edikted scraper — all women's clothing into Supabase."""
import sys, os, time
sys.path.insert(0, os.path.dirname(__file__))
from db_insert import ensure_table, insert_products
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

TABLE = "products_edikted"
BASE = "https://edikted.com"
COLLECTION = "/collections/all"

def p(*args):
    try:
        print(*args, flush=True)
    except UnicodeEncodeError:
        print(*(str(a).encode("ascii", "replace").decode() for a in args), flush=True)


def dismiss(page):
    for sel in ["button:has-text('Accept')", "button:has-text('No thanks')",
                "[aria-label*='close' i]", "[class*='popup'] [class*='close']"]:
        try:
            btn = page.locator(sel)
            if btn.count() and btn.first.is_visible():
                btn.first.click()
                page.wait_for_timeout(1500)
                return
        except Exception:
            pass


def extract(page):
    return page.evaluate(f"""
        () => {{
            const BASE = '{BASE}';
            const titles = Array.from(document.querySelectorAll('.product-card__title'));
            return titles.map(titleEl => {{
                const title = titleEl.textContent.trim();
                // Walk up to find a container that has a product link
                let container = titleEl.parentElement;
                for (let i = 0; i < 8; i++) {{
                    if (!container || container.tagName === 'BODY') break;
                    if (container.querySelector('a[href*="/products/"]')) break;
                    container = container.parentElement;
                }}
                const linkEl = container ? container.querySelector('a[href*="/products/"]') : null;
                const href = linkEl ? linkEl.getAttribute('href') : '';
                const url = href.startsWith('http') ? href : BASE + href.split('?')[0];
                const priceEl = container ? container.querySelector('.price-highlight') : null;
                const price = priceEl ? priceEl.textContent.trim() : '';
                const imgEl = container ? container.querySelector('img') : null;
                let imgSrc = imgEl ? (imgEl.getAttribute('src') || imgEl.getAttribute('data-src') || '') : '';
                if (imgSrc.startsWith('//')) imgSrc = 'https:' + imgSrc;
                return {{title, price, color: '', url, image: imgSrc}};
            }}).filter(r => r.title && r.url && r.url !== BASE);
        }}
    """)


def has_next_page(page):
    """Return True if a Next pagination link is visible."""
    try:
        nxt = page.locator("a[aria-label='Next page'], a:has-text('Next'), [class*='pagination'] a[rel='next']")
        return nxt.count() > 0 and nxt.first.is_visible()
    except Exception:
        return False


def main():
    ensure_table(TABLE)
    total_ins = 0
    total_skip = 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            locale="en-US",
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.new_page()
        Stealth().apply_stealth_sync(page)

        p("Warming up on homepage...")
        page.goto(BASE, timeout=60000)
        page.wait_for_timeout(5000)
        dismiss(page)

        page_num = 1
        while page_num <= 200:
            url = f"{BASE}{COLLECTION}?page={page_num}"
            page.goto(url, timeout=60000)
            page.wait_for_timeout(7000)
            dismiss(page)

            products = extract(page)
            if not products:
                p(f"  Page {page_num}: no products — stopping")
                break

            ins, skip = insert_products(TABLE, products)
            total_ins += ins
            total_skip += skip
            p(f"  Page {page_num}: {len(products)} products | {ins} inserted, {skip} skipped")

            if not has_next_page(page):
                p(f"  No next page — done")
                break
            page_num += 1

        browser.close()

    p(f"\n{'='*50}")
    p(f"DONE! Total: {total_ins} inserted, {total_skip} skipped (duplicates)")


if __name__ == "__main__":
    main()
