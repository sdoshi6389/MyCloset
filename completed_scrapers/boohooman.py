from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from playwright_stealth import Stealth
from urllib.parse import urlparse, parse_qs
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from db_insert import ensure_table, insert_products
import time
import random

BASE_URL  = "https://www.boohooman.com"
TABLE     = "products_boohooman"
CARD_SEL  = "a[data-test-id*='product-card-link']"
LOAD_MORE_SEL = "button[data-test-id='pagination-load-more']"

CATEGORY_URLS = [
    f"{BASE_URL}/categories/mens-tops-t-shirts",
    f"{BASE_URL}/categories/mens-jeans",
    f"{BASE_URL}/categories/mens-shorts",
    f"{BASE_URL}/categories/mens-hoodies-sweatshirts",
    f"{BASE_URL}/categories/mens-shirts",
    f"{BASE_URL}/categories/mens-trousers",
    f"{BASE_URL}/categories/mens-co-ords-sets",
    f"{BASE_URL}/categories/mens-coats-jackets",
    f"{BASE_URL}/categories/mens-tracksuits",
    f"{BASE_URL}/categories/mens-joggers",
    f"{BASE_URL}/categories/mens-knitwear",
    f"{BASE_URL}/categories/mens-swimwear",
    f"{BASE_URL}/categories/mens-suits",
    f"{BASE_URL}/categories/mens-polo-shirts",
    f"{BASE_URL}/categories/mens-tops-vests",
    f"{BASE_URL}/categories/mens-loungewear",
]


def accept_cookies(page):
    try:
        btn = page.locator("button#onetrust-accept-btn-handler")
        if btn.is_visible():
            btn.click()
            page.wait_for_timeout(1500)
    except Exception:
        pass


def extract_color_from_url(href):
    try:
        qs = parse_qs(urlparse(href).query)
        colour = qs.get("colour", qs.get("color", [""]))
        return colour[0].strip().title() if colour else ""
    except Exception:
        return ""


def extract_products(page):
    cards = page.query_selector_all(CARD_SEL)
    products = []
    for card in cards:
        try:
            title_el = card.query_selector("span[data-test-id='product-card-title']")
            price_el = card.query_selector("span[data-test-id='product-price-current']")
            img_el   = card.query_selector("video[data-test-id='video-element']")
            if not img_el:
                img_el = card.query_selector("img")

            title = title_el.inner_text().strip() if title_el else ""
            price = price_el.inner_text().strip() if price_el else ""
            href  = card.get_attribute("href") or ""
            url   = (BASE_URL + href) if href.startswith("/") else href
            image = (img_el.get_attribute("poster") or img_el.get_attribute("src") or "") if img_el else ""
            color = extract_color_from_url(href)

            if title:
                products.append({"title": title, "price": price, "color": color, "url": url, "image": image})
        except Exception as e:
            print(f"  Card error: {e}", flush=True)
    return products


def load_all_products(page):
    """Click Load More until button disappears, using JS click to bypass overlays."""
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    time.sleep(2)
    clicks = 0
    while True:
        lm = page.query_selector(LOAD_MORE_SEL)
        if not lm:
            break
        try:
            prev_count = page.locator(CARD_SEL).count()
            page.evaluate("document.querySelector(\"button[data-test-id='pagination-load-more']\").click()")
            time.sleep(3)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(1)
            new_count = page.locator(CARD_SEL).count()
            clicks += 1
            if new_count == prev_count:
                break
        except Exception as e:
            print(f"  Load More error: {e}", flush=True)
            break
    return clicks


def scrape_category(page, url):
    print(f"\n  Loading: {url}", flush=True)
    try:
        page.goto(url, timeout=60000)
        page.wait_for_timeout(5000)
        accept_cookies(page)

        initial = page.locator(CARD_SEL).count()
        print(f"  Initial cards: {initial}", flush=True)

        clicks = load_all_products(page)
        total  = page.locator(CARD_SEL).count()
        print(f"  Load More clicks: {clicks} | Total cards: {total}", flush=True)

        products = extract_products(page)
        print(f"  Scraped: {len(products)} products", flush=True)
        return products
    except PWTimeout:
        print(f"  Timeout — skipping", flush=True)
        return []
    except Exception as e:
        print(f"  Error: {e}", flush=True)
        return []


def main():
    print("Connecting to Supabase...", flush=True)
    ensure_table(TABLE)
    print(f"Table '{TABLE}' ready.", flush=True)

    total_inserted = 0
    total_skipped  = 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        print("Warming up on homepage...", flush=True)
        page.goto(BASE_URL, timeout=60000)
        page.wait_for_timeout(5000)
        accept_cookies(page)

        for url in CATEGORY_URLS:
            products = scrape_category(page, url)
            if products:
                ins, skip = insert_products(TABLE, products)
                total_inserted += ins
                total_skipped  += skip
                print(f"  DB: {ins} inserted, {skip} skipped", flush=True)
            time.sleep(random.uniform(3, 6))

        browser.close()

    print("\n" + "=" * 50, flush=True)
    print(f"  Table : {TABLE}", flush=True)
    print(f"  Inserted : {total_inserted}", flush=True)
    print(f"  Skipped  : {total_skipped}  (already in DB)", flush=True)
    print("=" * 50, flush=True)


if __name__ == "__main__":
    main()
