"""Nasty Gal scraper — women's clothing into Supabase."""
import sys, os, re, time
sys.path.insert(0, os.path.dirname(__file__))
from db_insert import ensure_table, insert_products
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

TABLE = "products_nastygal"
BASE = "https://www.nastygal.com"

CATEGORIES = [
    "/categories/womens-clothing",
    "/categories/womens-tops",
    "/categories/womens-dresses",
    "/categories/womens-denim",
    "/categories/womens-jeans",
    "/categories/womens-trousers",
    "/categories/womens-skirts",
    "/categories/womens-co-ords",
    "/categories/womens-swimwear",
    "/categories/womens-knitwear",
    "/categories/lingerie",
    "/categories/womens-plus-size",
    "/categories/womens-petite",
    "/categories/new-in",
]

def p(*args):
    try:
        print(*args, flush=True)
    except UnicodeEncodeError:
        print(*(str(a).encode("ascii", "replace").decode() for a in args), flush=True)


def dismiss_cookies(page):
    for sel in ["button:has-text('Accept All')", ".cky-btn-accept",
                "[data-cky-tag='accept-button']", "#onetrust-accept-btn-handler"]:
        try:
            btn = page.locator(sel)
            if btn.count() and btn.first.is_visible(timeout=2000):
                btn.first.click()
                page.wait_for_timeout(3000)
                return
        except Exception:
            pass


def load_all(page):
    """Click Load More until all products are on the page."""
    click = 0
    while True:
        before = page.evaluate(
            "() => document.querySelectorAll('a[data-test-id^=\"product-card-link\"]').length"
        )
        load_btn = page.locator("button:has-text('Load More')")
        if not load_btn.count():
            break
        try:
            load_btn.first.scroll_into_view_if_needed()
            page.wait_for_timeout(1500)
            if not load_btn.first.is_visible():
                break
            load_btn.first.click()
            page.wait_for_timeout(4500)
            click += 1
            after = page.evaluate(
                "() => document.querySelectorAll('a[data-test-id^=\"product-card-link\"]').length"
            )
            p(f"    Load More {click}: {before} -> {after}")
            if after <= before:
                break
        except Exception as e:
            p(f"    Load More error: {e}")
            break


def extract(page):
    return page.evaluate("""
        () => {
            const BASE = 'https://www.nastygal.com';
            const cards = Array.from(document.querySelectorAll('a[data-test-id^="product-card-link"]'));
            return cards.map(a => {
                const img = a.querySelector('img[src*="nastygal"]') || a.querySelector('img');
                const label = a.getAttribute('aria-label') || '';
                const title = label.replace(/^View product /i, '').trim();
                const href = a.getAttribute('href') || '';
                const cm = href.match(/[?&]colour=([^&]+)/);
                const color = cm ? decodeURIComponent(cm[1]) : '';
                const prices = (a.textContent || '').match(/\\$[\\d.]+/g) || [];
                const price = prices[0] || '';
                const url = href.startsWith('http') ? href : BASE + href;
                const imgSrc = img ? (img.src || img.getAttribute('src') || '') : '';
                return {title, price, color, url, image: imgSrc};
            }).filter(r => r.title);
        }
    """)


def scrape_category(page, cat_path):
    cat_name = cat_path.split("/")[-1]
    p(f"\n=== {cat_name} ===")
    page.goto(BASE + cat_path, timeout=60000)
    page.wait_for_timeout(7000)
    dismiss_cookies(page)

    # Confirm page loaded (not 404)
    title = page.title()
    if "404" in title or "not found" in title.lower():
        p(f"  SKIP — page not found")
        return []

    load_all(page)
    products = extract(page)
    p(f"  Extracted {len(products)} products")
    return products


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
        dismiss_cookies(page)

        for cat_path in CATEGORIES:
            products = scrape_category(page, cat_path)
            if products:
                ins, skip = insert_products(TABLE, products)
                total_ins += ins
                total_skip += skip
                p(f"  DB: {ins} inserted, {skip} skipped")

        browser.close()

    p(f"\n{'='*50}")
    p(f"DONE! Total: {total_ins} inserted, {total_skip} skipped (duplicates)")


if __name__ == "__main__":
    main()
