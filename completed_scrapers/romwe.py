"""Romwe scraper — women's clothing into Supabase."""
import sys, os, time, re
sys.path.insert(0, os.path.dirname(__file__))
from db_insert import ensure_table, insert_products
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

TABLE = "products_romwe"
BASE = "https://us.romwe.com"

CATEGORIES = [
    "/womens-clothing/",
    "/Womens-Tops/",
    "/Womens-Dresses/",
    "/Womens-Bottoms/",
    "/Womens-Outerwear/",
    "/Womens-Swimwear/",
    "/Womens-Lingerie/",
    "/Plus-Size-Womens-Clothing/",
    "/Womens-Sets/",
    "/Womens-Jumpsuits/",
]

def p(*args):
    try:
        print(*args, flush=True)
    except UnicodeEncodeError:
        print(*(str(a).encode("ascii", "replace").decode() for a in args), flush=True)


def dismiss(page):
    for sel in ["[aria-label*='close' i]", ".sui-dialog__close",
                "[class*='close-btn']", "[class*='closeBtn']",
                "button:has-text('Accept')", "#onetrust-accept-btn-handler"]:
        try:
            btn = page.locator(sel)
            if btn.count() and btn.first.is_visible():
                btn.first.click()
                page.wait_for_timeout(1500)
                return
        except Exception:
            pass


def scroll_to_load(page, rounds=8, wait=2.5):
    """Scroll down to trigger lazy image loading."""
    for _ in range(rounds):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(wait)


def count_cards(page):
    try:
        return page.locator("[class*='S-product-item']").count()
    except Exception:
        return 0


def is_404(page):
    """Return True if current page is a Romwe 404 / not-found page."""
    try:
        body = page.evaluate("() => document.body.innerText").lower()
        return "cannot be found" in body or "page not found" in body
    except Exception:
        return False


def extract(page):
    return page.evaluate(f"""
        () => {{
            const BASE = '{BASE}';
            // Exclude cards inside recommendation / editorial sections
            const cards = Array.from(document.querySelectorAll('[class*="S-product-item"]'))
                .filter(card => {{
                    let el = card.parentElement;
                    while (el) {{
                        const cls = (el.className || '').toLowerCase();
                        if (cls.includes('recommend') || cls.includes('editorial') ||
                            cls.includes('j-recommend') || cls.includes('floor-tab')) {{
                            return false;
                        }}
                        el = el.parentElement;
                    }}
                    return true;
                }});
            return cards.map(card => {{
                const nameEl = card.querySelector('[class*="s-product-item__name"], [class*="product-item__name"]');
                const title = nameEl ? nameEl.textContent.trim() : '';
                const priceEl = card.querySelector('[class*="sale-price"], [class*="salePrice"]');
                const price = priceEl ? priceEl.textContent.trim() : '';
                const linkEl = card.querySelector('a[href]');
                const href = linkEl ? linkEl.getAttribute('href') : '';
                const url = href.startsWith('http') ? href : BASE + href.split('?')[0];
                const imgEl = card.querySelector('img');
                const imgSrc = imgEl ? (imgEl.getAttribute('data-src') || imgEl.src || '') : '';
                return {{title, price, color: '', url, image: imgSrc}};
            }}).filter(r => r.title && r.url && r.url !== BASE && !r.url.endsWith(BASE + '/'));
        }}
    """)


def scrape_category(page, cat_path):
    cat_name = cat_path.strip("/")
    p(f"\n=== {cat_name} ===")
    url = BASE + cat_path
    page.goto(url, timeout=60000)
    page.wait_for_timeout(7000)
    dismiss(page)

    # Check if page loaded (not 404 / empty)
    cards_before = count_cards(page)
    if cards_before == 0:
        p(f"  SKIP — no products found (possible 404 or wrong URL)")
        return []

    p(f"  Initial cards: {cards_before}")
    scroll_to_load(page)
    dismiss(page)

    # Always start pagination from page 1 (cleaner, avoids mixed recommendation blocks)
    products = []
    page_num = 1
    while page_num <= 50:
        pg_url = f"{url}?page={page_num}"
        page.goto(pg_url, timeout=60000)
        page.wait_for_timeout(6000)
        dismiss(page)

        # Stop if Romwe shows a 404 / not-found page
        if is_404(page):
            p(f"  Page {page_num}: 404 — stopping")
            break
        # Stop if redirected back to page 1
        if page.url == url or "page=1" in page.url:
            break
        cnt = count_cards(page)
        if cnt == 0:
            break

        scroll_to_load(page, rounds=4)
        new_prods = extract(page)
        if not new_prods:
            break
        products.extend(new_prods)
        p(f"  Page {page_num}: {len(new_prods)} products (total {len(products)})")
        page_num += 1

    p(f"  Total extracted: {len(products)}")
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
        dismiss(page)

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
