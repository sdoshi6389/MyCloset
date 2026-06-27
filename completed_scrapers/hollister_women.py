"""Hollister women's scraper — discovers all category pages then scrapes each."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from db_insert import ensure_table, insert_products
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

TABLE = "products_hollister_womens"
BASE = "https://www.hollisterco.com"

def p(*args):
    try:
        print(*args, flush=True)
    except UnicodeEncodeError:
        print(*(str(a).encode("ascii", "replace").decode() for a in args), flush=True)


def get_category_urls(page):
    """Discover all women's category URLs from the main women's landing page."""
    page.goto(f"{BASE}/shop/us/womens", timeout=60000)
    page.wait_for_timeout(5000)
    links = page.evaluate("""
        () => {
            const seen = new Set();
            document.querySelectorAll('a[href*="/shop/us/womens-"]').forEach(a => {
                const h = a.getAttribute('href');
                if (h) seen.add(h.split('?')[0]);
            });
            return [...seen].sort();
        }
    """)
    skip_keywords = ['fragrance', 'body', 'bestsellers', 'top-rated', 'new-arrivals']
    filtered = [l for l in links if not any(k in l for k in skip_keywords)]
    p(f"Found {len(filtered)} category URLs (from {len(links)} total)")
    return filtered


def scroll_to_bottom(page, max_scrolls=80):
    previous_height = 0
    for _ in range(max_scrolls):
        page.mouse.wheel(0, 3000)
        page.wait_for_timeout(1200)
        current_height = page.evaluate("document.body.scrollHeight")
        if current_height == previous_height:
            break
        previous_height = current_height


def extract_products(page):
    cards = page.query_selector_all("li[data-testid='catalog-product-card']")
    products = []
    for card in cards:
        try:
            title_el = card.query_selector("h2[data-testid='catalog-product-card-name']")
            title = title_el.inner_text().strip() if title_el else ""

            price_el = card.query_selector("span[data-testid='product-price-text-wrapper']")
            price = price_el.inner_text().strip() if price_el else ""

            img_el = card.query_selector("img")
            alt = img_el.get_attribute("alt") if img_el else ""
            color = alt.split(",")[1].strip() if alt and "," in alt else ""

            link_el = card.query_selector("a[href*='/shop/us/p/']")
            href = link_el.get_attribute("href") if link_el else None
            url = f"{BASE}{href}" if href else ""

            image = img_el.get_attribute("src") if img_el else ""

            if not title or not url:
                continue
            products.append({"title": title, "price": price, "color": color,
                              "url": url, "image": image})
        except Exception as e:
            p(f"  Card error: {e}")
    return products


def scrape_category(ctx, cat_path):
    url = f"{BASE}{cat_path}"
    p(f"\n  {cat_path}")
    page = ctx.new_page()
    try:
        page.goto(url, timeout=60000)
        page.wait_for_timeout(3000)
        scroll_to_bottom(page)
        products = extract_products(page)
        p(f"    {len(products)} cards")
        return products
    except Exception as e:
        p(f"    Error: {e}")
        return []
    finally:
        page.close()


def main():
    ensure_table(TABLE)
    total_ins = 0
    total_skip = 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            locale="en-US", viewport={"width": 1280, "height": 900},
        )
        primer = ctx.new_page()
        Stealth().apply_stealth_sync(primer)

        p("Discovering women's categories...")
        categories = get_category_urls(primer)
        primer.close()

        p(f"\nScraping {len(categories)} categories:")
        for cat in categories:
            products = scrape_category(ctx, cat)
            if products:
                ins, skip = insert_products(TABLE, products)
                total_ins += ins
                total_skip += skip
                p(f"    DB: {ins} inserted, {skip} skipped")

        ctx.close()
        browser.close()

    p(f"\n{'='*50}")
    p(f"DONE! {total_ins} inserted, {total_skip} skipped (duplicates)")


if __name__ == "__main__":
    main()
