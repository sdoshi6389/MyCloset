"""Coofandy scraper — men's clothing into Supabase."""
import sys, os, time
sys.path.insert(0, os.path.dirname(__file__))
from db_insert import ensure_table, insert_products
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

TABLE = "products_coofandy"
BASE = "https://coofandy.com"
COLLECTION = "/collections/all"

def p(*args):
    try:
        print(*args, flush=True)
    except UnicodeEncodeError:
        print(*(str(a).encode("ascii", "replace").decode() for a in args), flush=True)


def dismiss(page):
    for sel in ["button:has-text('No thanks')", "button:has-text('×')",
                "[aria-label*='close' i]", ".popup__close", ".newsletter-popup__close"]:
        try:
            btn = page.locator(sel)
            if btn.count() and btn.first.is_visible():
                btn.first.click()
                page.wait_for_timeout(1000)
        except Exception:
            pass


def extract(page):
    return page.evaluate(f"""
        () => {{
            const BASE = '{BASE}';
            const items = Array.from(document.querySelectorAll('.grid__item'))
                .filter(item => item.querySelector('a[href*="/products/"]'));

            return items.map(item => {{
                const linkEl = item.querySelector('a[href*="/products/"]');
                const href = linkEl ? linkEl.getAttribute('href') : '';
                const url = href.startsWith('http') ? href : BASE + href.split('?')[0];

                // Title
                const titleEl = item.querySelector(
                    '.grid-product__title, [class*="product-title"], h2, h3'
                );
                const title = titleEl ? titleEl.textContent.trim() : '';

                // Price — try grid-product price elements, then any money span
                let price = '';
                const priceWrap = item.querySelector('.grid-product__price-wrap, .grid-product__price, [class*="price-wrap"]');
                if (priceWrap) {{
                    // Prefer sale price (current price)
                    const saleEl = priceWrap.querySelector('[class*="sale"], [class*="current"], [class*="final"]');
                    price = saleEl ? saleEl.textContent.trim() : priceWrap.textContent.trim().split('\\n')[0].trim();
                }} else {{
                    const moneyEl = item.querySelector('[class*="money"], [class*="price"]');
                    if (moneyEl) price = moneyEl.textContent.trim();
                }}
                // Clean price — keep only first $XX.XX
                const priceMatch = price.match(/\\$[\\d,]+\\.?\\d*/);
                price = priceMatch ? priceMatch[0] : price.substring(0, 20).trim();

                // Image — parse from srcset or src
                const imgEl = item.querySelector('img.grid-product__image, img[class*="product"]');
                let imgSrc = '';
                if (imgEl) {{
                    const srcset = imgEl.getAttribute('srcset') || '';
                    if (srcset) {{
                        // First entry in srcset: "//url.jpg 360w, ..." → take the 540w or 720w version
                        const entries = srcset.split(',').map(s => s.trim());
                        const medium = entries.find(e => e.includes('540w') || e.includes('720w')) || entries[0];
                        imgSrc = medium.trim().split(' ')[0];
                    }} else {{
                        imgSrc = imgEl.getAttribute('src') || imgEl.getAttribute('data-src') || '';
                    }}
                    if (imgSrc.startsWith('//')) imgSrc = 'https:' + imgSrc;
                }}

                return {{title, price, color: '', url, image: imgSrc}};
            }}).filter(r => r.title && r.url && r.url !== BASE);
        }}
    """)


def has_next_page(page):
    """Return True if a Next pagination link is visible (by rel=next or text)."""
    try:
        # Check rel=next attribute
        nxt = page.locator("a[rel='next']")
        if nxt.count() and nxt.first.is_visible():
            return True
        # Check by text "Next" in pagination
        result = page.evaluate("""
            () => {
                const links = document.querySelectorAll('[class*="pagination"] a, .pagination a, ul[class*="pag"] a');
                return Array.from(links).some(a =>
                    a.textContent.trim().toLowerCase() === 'next' && a.getAttribute('href')
                );
            }
        """)
        return bool(result)
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
        while page_num <= 100:
            url = f"{BASE}{COLLECTION}?page={page_num}"
            # Retry navigation up to 3 times on timeout
            loaded = False
            for attempt in range(3):
                try:
                    page.goto(url, timeout=90000)
                    page.wait_for_timeout(5000)
                    loaded = True
                    break
                except Exception as e:
                    p(f"  Page {page_num} attempt {attempt+1} failed: {type(e).__name__} — retrying...")
                    page.wait_for_timeout(5000)
            if not loaded:
                p(f"  Page {page_num}: navigation failed after 3 attempts — stopping")
                break

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
                p("  No next page — done")
                break
            page_num += 1

        browser.close()

    p(f"\n{'='*50}")
    p(f"DONE! Total: {total_ins} inserted, {total_skip} skipped (duplicates)")


if __name__ == "__main__":
    main()
