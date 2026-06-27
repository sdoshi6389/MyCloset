from playwright.sync_api import sync_playwright
import time
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from db_insert import ensure_table, insert_products

TABLE = "products_zara_mens"
START_URL = "https://www.zara.com/us/en/man-all-products-l7465.html?v1=2443335"
BASE_URL = "https://www.zara.com"

def infinite_scroll(page, max_scrolls=200, buffer_time=3):
    print("📜 Scrolling until layout-footer is visible...")

    last_count = 0
    stagnant_scrolls = 0

    for i in range(max_scrolls):
        print(f"🔄 Scroll step {i + 1}")

        # Scroll layout-footer into view (triggers product load)
        try:
            page.evaluate("""
                () => {
                    const footer = document.querySelector('.layout-footer');
                    if (footer) {
                        footer.scrollIntoView({ behavior: 'smooth', block: 'end' });
                    }
                }
            """)
        except Exception as e:
            print(f"⚠️ Failed to scroll to footer: {e}")

        # Flicker viewport to help observer trigger
        page.set_viewport_size({"width": 1200, "height": 720 + (i % 2)})
        time.sleep(buffer_time)

        current_count = page.locator("li.product-grid-product").count()
        print(f"🧮 Products loaded: {current_count}")

        if current_count == last_count:
            stagnant_scrolls += 1
            if stagnant_scrolls >= 5:
                print("✅ No more products loading.")
                break
        else:
            stagnant_scrolls = 0

        last_count = current_count


def extract_products(page):
    print("🛍️ Extracting product data...")
    cards = page.query_selector_all("li.product-grid-product")
    products = []

    for card in cards:
        try:
            # Title
            title_elem = card.query_selector("div.product-grid-product__name")
            title = title_elem.inner_text().strip() if title_elem else "MISSING_TITLE"

            # Price
            price_elem = card.query_selector("span.price-current") or card.query_selector("span.price__amount")
            price = price_elem.inner_text().strip() if price_elem else "MISSING_PRICE"

            # Color
            color_elem = card.query_selector("div.product-grid-product__color")
            color = color_elem.inner_text().strip() if color_elem else "MISSING_COLOR"

            # URL
            link_elem = card.query_selector("a.product-link")
            href = link_elem.get_attribute("href") if link_elem else None
            full_url = href if href and href.startswith("http") else f"{BASE_URL}{href}" if href else "MISSING_URL"

            # Image
            img_elem = card.query_selector("img.media-image__image")
            image_url = img_elem.get_attribute("src") if img_elem else "MISSING_IMAGE"

            products.append({
                "title": title,
                "price": price,
                "color": color,
                "url": full_url,
                "image": image_url
            })

        except Exception as e:
            print(f"⚠️ Error extracting a product: {e}")

    print(f"✅ Extracted {len(products)} products.")
    return products

def main():
    all_products = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(START_URL, timeout=60000)
        page.wait_for_timeout(3000)

        infinite_scroll(page)
        all_products = extract_products(page)

        browser.close()

    ensure_table(TABLE)
    ins, skip = insert_products(TABLE, all_products)
    print(f"\nDone! {ins} inserted, {skip} skipped (already in DB).")

if __name__ == "__main__":
    main()
