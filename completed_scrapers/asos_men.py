from playwright.sync_api import sync_playwright
import time
import re
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from db_insert import ensure_table, insert_products

TABLE = "products_asos_mens"
BASE_URL = "https://www.asos.com/us/men/new-in/cat/?cid=27110"
PRD_SEL = "a[href*='/prd/']"


def accept_cookies(page):
    try:
        btn = page.locator("button#onetrust-accept-btn-handler")
        if btn.is_visible():
            btn.click()
            page.wait_for_timeout(2000)
            print("Accepted cookie banner")
    except Exception:
        pass


def load_all_products(page):
    """Keep scrolling and clicking Load More until no more button appears."""
    print("📜 Loading all products...")
    page_num = 1

    while True:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(2)

        lm = page.query_selector("[data-auto-id='loadMoreProducts']")
        if not lm or not lm.is_visible():
            print("✅ No more pages to load.")
            break

        prev_count = page.locator(PRD_SEL).count()
        lm.scroll_into_view_if_needed()
        lm.click()
        page_num += 1
        time.sleep(4)

        new_count = page.locator(PRD_SEL).count()
        print(f"  Page {page_num}: {prev_count} → {new_count} products")

        if new_count == prev_count:
            print("✅ Count stopped growing.")
            break


def extract_color_from_image(src):
    """Pull color name from ASOS image filename: .../PRODUCTID-1-colorname/..."""
    try:
        match = re.search(r"-1-([^/?]+)", src)
        if match:
            raw = match.group(1).replace("-", " ").strip()
            return raw.title() if raw else "MISSING_COLOR"
    except Exception:
        pass
    return "MISSING_COLOR"


def extract_products(page):
    cards = page.query_selector_all(PRD_SEL)
    print(f"🛍️  Extracting from {len(cards)} product cards...")
    products = []

    for card in cards:
        try:
            # aria-label contains both title and price: "Product Name, Price $XX.XX"
            aria = card.get_attribute("aria-label") or ""
            if ", Price " in aria:
                title, price_raw = aria.rsplit(", Price ", 1)
                price = price_raw.strip()
            else:
                title = aria.strip() or "MISSING_TITLE"
                price = "MISSING_PRICE"

            # URL
            url = card.get_attribute("href") or "MISSING_URL"

            # Image — src starts with "//" so prepend https:
            img = card.query_selector("img")
            raw_src = img.get_attribute("src") if img else ""
            image = ("https:" + raw_src) if raw_src.startswith("//") else (raw_src or "MISSING_IMAGE")

            # Color — extracted from image filename
            color = extract_color_from_image(raw_src)

            products.append({
                "title": title.strip(),
                "price": price,
                "color": color,
                "url": url,
                "image": image,
            })

        except Exception as e:
            print(f"⚠️  Error on card: {e}")

    print(f"✅ Extracted {len(products)} products.")
    return products


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
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

        # Accept cookies on homepage first to establish session
        print("🌐 Loading ASOS homepage...")
        page.goto("https://www.asos.com/us/", timeout=60000)
        page.wait_for_timeout(4000)
        accept_cookies(page)

        # Navigate to men's category
        print(f"\n🌐 Navigating to men's new in: {BASE_URL}")
        page.goto(BASE_URL, timeout=60000)
        page.wait_for_timeout(8000)
        print(f"Title: {page.title()}")
        print(f"Initial products: {page.locator(PRD_SEL).count()}")

        load_all_products(page)
        products = extract_products(page)

        browser.close()

    ensure_table(TABLE)
    ins, skip = insert_products(TABLE, products)
    print(f"\nDone! {ins} inserted, {skip} skipped (already in DB).")


if __name__ == "__main__":
    main()
